import hashlib
import re
import uuid
from datetime import datetime, timezone

from analysis import (
    analyze_misconceptions,
    analyze_response,
    embed_misconception,
    generate_verified_materials,
)

REQUIRED_COLUMNS = (
    "class_name",
    "student_name",
    "subject",
    "topic",
    "question",
    "correct_answer",
    "student_answer",
)
VECTOR_INDEX_NAME = "misconception_vector_index"
VECTOR_COLLECTION_NAME = "misconception_vector_labels"
VECTOR_DIMENSIONS = 3072
VECTOR_MATCH_THRESHOLD = 0.82


def _now():
    return datetime.now(timezone.utc)


def log_agent_action(db, run_id, step, status, details=None):
    action = {
        "at": _now(),
        "step": step,
        "status": status,
    }
    if details:
        action["details"] = details
    db.agent_runs.update_one(
        {"run_id": run_id},
        {
            "$push": {"actions": action},
            "$set": {"updated_at": _now()},
        },
    )


def _record_failure(db, run_id, row_number, row, error):
    failure = {
        "row_number": row_number,
        "row": row,
        "response_id": row.get("_response_id"),
        "error": str(error),
        "retryable": all(str(row.get(column, "")).strip() for column in REQUIRED_COLUMNS),
    }
    db.agent_runs.update_one(
        {"run_id": run_id},
        {
            "$push": {"failed_rows": failure},
            "$inc": {"failed_count": 1},
        },
    )
    log_agent_action(
        db,
        run_id,
        "mark_response",
        "failed",
        {"row": row_number, "error": str(error)},
    )


def _mark_one_response(db, run_id, row_number, row, response_id=None):
    if response_id is None:
        raise ValueError("A saved response is required for Class Agent processing.")
    existing = db.responses.find_one(
        {"agent_run_id": run_id, "agent_row_number": row_number}
    )
    if existing:
        return existing
    normalized = {
        key: str(row.get(key, "")).strip()
        for key in REQUIRED_COLUMNS
    }
    missing = [key for key, value in normalized.items() if not value]
    if missing:
        raise ValueError(f"Missing required values: {', '.join(missing)}")

    assessment = analyze_response(
        normalized["topic"],
        normalized["question"],
        normalized["correct_answer"],
        normalized["student_answer"],
    )
    score_correct = assessment["score"] >= 50
    needs_review = (
        assessment["confidence"] != "high"
        or 40 <= assessment["score"] <= 60
        or score_correct != assessment["is_correct"]
    )

    response = {
        "is_correct": assessment["is_correct"],
        "agent_run_id": run_id,
        "agent_row_number": row_number,
        "analysis": {
            "source": "gemini_agent",
            "score": assessment["score"],
            "confidence": assessment["confidence"],
            "misconception": assessment.get("misconception"),
            "misconception_detail": assessment.get("misconception_detail"),
            "knowledge_gap": assessment.get("knowledge_gap"),
            "suggested_intervention": assessment.get("suggested_intervention"),
            "needs_review": needs_review,
        },
        "teacher_review": {
            "status": "pending" if needs_review else "not_required",
            "decision": None,
            "reviewed_at": None,
        },
    }
    saved_response = db.responses.find_one({"_id": response_id})
    if not saved_response:
        raise RuntimeError("The saved response no longer exists.")
    db.responses.update_one(
        {"_id": response_id},
        {"$set": response},
    )
    response["_id"] = response_id
    log_agent_action(
        db,
        run_id,
        "mark_response",
        "review_required" if needs_review else "succeeded",
        {"row": row_number, "response_id": str(response_id)},
    )
    return response


def _atlas_canonical_label(db, label, explanation):
    embedding = embed_misconception(f"{label}\n{explanation}")
    if len(embedding) != VECTOR_DIMENSIONS:
        raise RuntimeError(
            f"Embedding dimension mismatch: expected {VECTOR_DIMENSIONS}, "
            f"received {len(embedding)}."
        )
    normalized_label = re.sub(r"\s+", " ", label.strip().lower())
    label_key = hashlib.sha256(normalized_label.encode("utf-8")).hexdigest()
    vector_labels = db[VECTOR_COLLECTION_NAME]
    vector_labels.update_one(
        {"label_key": label_key},
        {
            "$set": {
                "label_key": label_key,
                "label": label.strip(),
                "explanation": explanation.strip(),
                "embedding": embedding,
                "updated_at": _now(),
            },
            "$setOnInsert": {"created_at": _now()},
        },
        upsert=True,
    )
    matches = list(
        vector_labels.aggregate(
            [
                {
                    "$vectorSearch": {
                        "index": VECTOR_INDEX_NAME,
                        "path": "embedding",
                        "queryVector": embedding,
                        "numCandidates": 50,
                        "limit": 10,
                    }
                },
                {"$match": {"label_key": {"$ne": label_key}}},
                {
                    "$project": {
                        "label": 1,
                        "score": {"$meta": "vectorSearchScore"},
                    }
                },
            ]
        )
    )
    for match in matches:
        if (
            match.get("label")
            and match.get("score", 0) >= VECTOR_MATCH_THRESHOLD
        ):
            return match["label"], match["score"]
    return label.strip(), None


def _group_and_draft_packs(db, run_id):
    db.agent_runs.update_one(
        {"run_id": run_id},
        {"$set": {"status": "grouping", "updated_at": _now()}},
    )
    log_agent_action(db, run_id, "group_misconceptions", "started")
    incorrect_responses = list(
        db.responses.find(
            {"agent_run_id": run_id, "is_correct": False},
            {"_id": 1, "subject": 1, "topic": 1, "question": 1,
             "correct_answer": 1, "student_answer": 1},
        )
    )
    packs = []
    vector_errors = []
    if incorrect_responses:
        examples = [
            {
                "index": index,
                "subject": item.get("subject", ""),
                "topic": item.get("topic", ""),
                "question": item.get("question", ""),
                "correct_answer": item.get("correct_answer", ""),
                "student_answer": item.get("student_answer", ""),
            }
            for index, item in enumerate(incorrect_responses)
        ]
        try:
            grouped = analyze_misconceptions(examples, range(len(examples)))
            log_agent_action(
                db,
                run_id,
                "group_misconceptions",
                "succeeded",
                {"patterns": len(grouped["patterns"])},
            )
        except Exception as error:
            log_agent_action(
                db,
                run_id,
                "group_misconceptions",
                "failed",
                {"error": str(error)},
            )
            db.agent_runs.update_one(
                {"run_id": run_id},
                {
                    "$set": {
                        "status": "paused_error",
                        "last_error": f"Could not group misconceptions: {error}",
                        "updated_at": _now(),
                    }
                },
            )
            return False

        semantic_groups = {}
        for pattern_index, pattern in enumerate(grouped["patterns"]):
            evidence = [
                examples[index]
                for index in pattern["evidence_indices"]
                if index < len(examples)
            ]
            if not evidence:
                continue
            topic = evidence[0]["topic"]
            subject = evidence[0]["subject"]
            try:
                canonical_label, vector_score = _atlas_canonical_label(
                    db,
                    pattern["label"],
                    pattern["explanation"],
                )
                log_agent_action(
                    db,
                    run_id,
                    "atlas_vector_group",
                    "succeeded",
                    {
                        "pattern": pattern_index,
                        "canonical_label": canonical_label,
                        "similarity": vector_score,
                    },
                )
            except Exception as error:
                canonical_label = pattern["label"]
                vector_score = None
                vector_errors.append(str(error))
                log_agent_action(
                    db,
                    run_id,
                    "atlas_vector_group",
                    "failed",
                    {"pattern": pattern_index, "error": str(error)},
                )

            group_key = (
                subject.casefold(),
                topic.casefold(),
                canonical_label.casefold(),
            )
            group = semantic_groups.setdefault(
                group_key,
                {
                    "pattern_index": pattern_index,
                    "pattern_indices": [],
                    "subject": subject,
                    "topic": topic,
                    "canonical_label": canonical_label,
                    "source_labels": [],
                    "evidence": [],
                    "vector_similarity": vector_score,
                },
            )
            group["pattern_indices"].append(pattern_index)
            group["source_labels"].append(pattern["label"])
            group["evidence"].extend(evidence)
            if vector_score is not None:
                group["vector_similarity"] = max(
                    group["vector_similarity"] or 0,
                    vector_score,
                )

        for group in semantic_groups.values():
            topic = group["topic"]
            canonical_label = group["canonical_label"]
            group["evidence"] = list(
                {
                    item["index"]: item
                    for item in group["evidence"]
                }.values()
            )
            try:
                verified_pack = generate_verified_materials(
                    topic,
                    canonical_label,
                    group["evidence"],
                )
                pack = {
                    "pattern_index": group["pattern_index"],
                    "pattern_indices": group["pattern_indices"],
                    "title": f"{canonical_label} — {topic} Revision Pack",
                    "subject": group["subject"],
                    "topic": topic,
                    "misconception": canonical_label,
                    "canonical_label": canonical_label,
                    "source_labels": group["source_labels"],
                    "vector_similarity": group["vector_similarity"],
                    "evidence_count": len(group["evidence"]),
                    **verified_pack,
                }
                packs.append(pack)
                log_agent_action(
                    db,
                    run_id,
                    "draft_and_verify_pack",
                    "verified" if pack["verified"] else "failed_verification",
                    {
                        "patterns": group["pattern_indices"],
                        "verification_attempts": pack["verification_attempts"],
                        "questions_passed": sum(
                            check["pass"] for check in pack["verification"]
                        ),
                        "questions_total": len(pack["verification"]),
                    },
                )
            except Exception as error:
                log_agent_action(
                    db,
                    run_id,
                    "draft_and_verify_pack",
                    "failed",
                    {"patterns": group["pattern_indices"], "error": str(error)},
                )
                packs.append(
                    {
                        "pattern_index": group["pattern_index"],
                        "pattern_indices": group["pattern_indices"],
                        "title": f"{canonical_label} — {topic} Revision Pack",
                        "subject": group["subject"],
                        "topic": topic,
                        "misconception": canonical_label,
                        "canonical_label": canonical_label,
                        "source_labels": group["source_labels"],
                        "vector_similarity": group["vector_similarity"],
                        "evidence_count": len(group["evidence"]),
                        "error": str(error),
                        "verified": False,
                        "verification": [],
                        "materials": None,
                    }
                )

    run_status = "awaiting_review" if packs else "completed"
    db.agent_runs.update_one(
        {"run_id": run_id},
        {
            "$set": {
                "status": run_status,
                "packs": packs,
                "vector_errors": vector_errors,
                "updated_at": _now(),
            },
            "$unset": {"last_error": ""},
        },
    )
    log_agent_action(
        db,
        run_id,
        "await_teacher_review",
        "pending" if packs else "not_required",
    )
    return True


def run_agent_saved_responses(db, responses):
    run_id = uuid.uuid4().hex
    db.agent_runs.insert_one(
        {
            "run_id": run_id,
            "status": "processing",
            "row_count": len(responses),
            "processed_count": 0,
            "failed_count": 0,
            "failed_rows": [],
            "packs": [],
            "actions": [],
            "created_at": _now(),
            "updated_at": _now(),
        }
    )
    log_agent_action(
        db,
        run_id,
        "load_saved_responses",
        "succeeded",
        {"responses": len(responses)},
    )
    for row_number, saved_response in enumerate(responses, start=1):
        row = {
            column: saved_response.get(column, "")
            for column in REQUIRED_COLUMNS
        }
        row["_response_id"] = saved_response["_id"]
        try:
            _mark_one_response(
                db,
                run_id,
                row_number,
                row,
                response_id=saved_response["_id"],
            )
            db.agent_runs.update_one(
                {"run_id": run_id},
                {"$inc": {"processed_count": 1}},
            )
        except Exception as error:
            _record_failure(db, run_id, row_number, row, error)
    _group_and_draft_packs(db, run_id)
    return run_id


def rebuild_agent_packs(db, run_id):
    if not db.agent_runs.find_one({"run_id": run_id}):
        raise RuntimeError("The selected agent run no longer exists.")
    log_agent_action(db, run_id, "retry_group_and_draft", "started")
    if not _group_and_draft_packs(db, run_id):
        raise RuntimeError("Misconception grouping failed; the run remains paused.")


def retry_agent_rows(db, run_id):
    run = db.agent_runs.find_one({"run_id": run_id})
    if not run:
        raise RuntimeError("The selected agent run no longer exists.")
    still_failed = []
    retried = 0
    for failure in run.get("failed_rows", []):
        if not failure.get("retryable"):
            still_failed.append(failure)
            continue
        try:
            _mark_one_response(
                db,
                run_id,
                failure["row_number"],
                failure["row"],
                response_id=failure.get("response_id"),
            )
            db.agent_runs.update_one(
                {"run_id": run_id},
                {
                    "$inc": {"processed_count": 1},
                    "$push": {
                        "actions": {
                            "at": _now(),
                            "step": "retry_mark_response",
                            "status": "succeeded",
                            "details": {"row": failure["row_number"]},
                        }
                    },
                },
            )
            retried += 1
        except Exception as error:
            failure["error"] = str(error)
            still_failed.append(failure)
            log_agent_action(
                db,
                run_id,
                "retry_mark_response",
                "failed",
                {"row": failure["row_number"], "error": str(error)},
            )
    db.agent_runs.update_one(
        {"run_id": run_id},
        {
            "$set": {
                "failed_rows": still_failed,
                "failed_count": len(still_failed),
                "updated_at": _now(),
            }
        },
    )
    if not _group_and_draft_packs(db, run_id):
        raise RuntimeError("Misconception grouping failed; the run remains paused.")
    return retried, len(still_failed)
