import hashlib
import json
import os
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from pymongo import MongoClient

from analysis import analyze_misconceptions, chat_about_misconceptions

load_dotenv()

st.set_page_config(page_title="TeachAssist AI", page_icon="📚", layout="wide")
st.markdown(
    "<style>img[alt='Running...'] { display: none !important; }</style>",
    unsafe_allow_html=True,
)
st.title("📚 TeachAssist AI")
st.caption(
    "Record student answers and correctness. Gemini identifies possible "
    "misconceptions in the make-up view."
)

SUBJECT_TOPICS = {
    "Maths": [
        "Algebra and functions",
        "Fractions and percentages",
        "Geometry and measures",
    ],
    "Chemistry": [
        "Atoms and elements",
        "Chemical reactions",
        "Acids and alkalis",
    ],
    "Physics": [
        "Forces and motion",
        "Electric circuits",
        "Energy and waves",
    ],
    "Biology": [
        "Cells and transport",
        "Inheritance",
        "Ecosystems",
    ],
}


@st.cache_resource
def get_db():
    uri = os.getenv("MONGODB_URI")
    if not uri:
        raise RuntimeError("MONGODB_URI not found in .env")
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    database = client["teaching_assistant"]
    database.classes.create_index("class_name", unique=True)
    database.students.create_index(
        [("class_name", 1), ("student_name", 1)],
        unique=True,
    )
    database.questions.create_index(
        [("subject", 1), ("topic", 1), ("question", 1)],
        unique=True,
    )
    return database


try:
    db = get_db()
except Exception as e:
    st.error(f"Could not connect to MongoDB: {e}")
    st.stop()


def load_df():
    docs = list(db.responses.find({}, {"_id": 0}).sort("created_at", -1))
    return pd.DataFrame(docs)


def reset_student_selection():
    st.session_state["student_select"] = None


def reset_subject_selection():
    st.session_state["topic_select"] = None
    st.session_state["question_select"] = None


def reset_question_selection():
    st.session_state["question_select"] = None


tab_add, tab_view, tab_insights, tab_chat = st.tabs(
    ["✏️ Add response", "📋 Responses", "📊 Class insights", "🧠 Misconception make-up"],
    key="main_navigation_tabs",
    on_change="rerun",
)

# ---------- Add response ----------
with tab_add:
    class_col, student_col = st.columns(2)
    with class_col:
        class_options = [
            item["class_name"]
            for item in db.classes.find({}, {"_id": 0, "class_name": 1}).sort(
                "class_name", 1
            )
        ]
        class_name = st.selectbox(
            "Class or group",
            class_options,
            index=None,
            placeholder="Search or add a class",
            accept_new_options=True,
            key="class_select",
            on_change=reset_student_selection,
        )
    with student_col:
        student_options = []
        if class_name:
            student_options = [
                item["student_name"]
                for item in db.students.find(
                    {"class_name": class_name},
                    {"_id": 0, "student_name": 1},
                ).sort("student_name", 1)
            ]
        student_name = st.selectbox(
            "Student name",
            student_options,
            index=None,
            placeholder="Search or add a student",
            accept_new_options=True,
            key="student_select",
            disabled=not class_name,
            help="Choose a student in the selected class or type a new student's name.",
        )

    subject_col, topic_col = st.columns(2)
    subject = subject_col.selectbox(
        "Subject",
        list(SUBJECT_TOPICS),
        key="subject_select",
        on_change=reset_subject_selection,
    )
    topic = topic_col.selectbox(
        "Topic",
        SUBJECT_TOPICS[subject],
        key="topic_select",
        placeholder="Choose a topic",
        on_change=reset_question_selection,
    )

    question_documents = list(
        db.questions.find(
            {"subject": subject, "topic": topic},
            {"_id": 0, "question": 1, "correct_answer": 1},
        ).sort("question", 1)
    )
    questions_by_text = {
        document["question"]: document for document in question_documents
    }
    question = st.selectbox(
        "Question",
        list(questions_by_text),
        index=None,
        placeholder="Search and select a saved question",
        key="question_select",
    )
    selected_question = questions_by_text.get(question) if question else None

    with st.expander("Add a question to this topic"):
        with st.form("question_form"):
            new_question = st.text_input("Question")
            new_correct_answer = st.text_area("Correct answer")
            add_question = st.form_submit_button("Save question")
        if add_question:
            if not new_question.strip() or not new_correct_answer.strip():
                st.warning("Enter both the question and its correct answer.")
            else:
                try:
                    db.questions.update_one(
                        {
                            "subject": subject,
                            "topic": topic,
                            "question": new_question.strip(),
                        },
                        {
                            "$setOnInsert": {
                                "subject": subject,
                                "topic": topic,
                                "question": new_question.strip(),
                                "correct_answer": new_correct_answer.strip(),
                                "created_at": datetime.now(timezone.utc),
                            }
                        },
                        upsert=True,
                    )
                    st.success("Question saved. Select it above to record an answer.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not save question: {e}")

    with st.form("answer_form", clear_on_submit=True):
        student_answer = st.text_area("Student's answer")
        is_correct = st.checkbox("Student's answer is correct")

        submitted = st.form_submit_button(
            "Save response",
            disabled=selected_question is None,
        )
    st.caption(
        "Misconceptions are identified by Gemini in Misconception make-up; "
        "you only mark whether the recorded answer is correct."
    )

    if submitted:
        fields = [
            class_name or "",
            student_name or "",
            subject or "",
            topic or "",
            question or "",
            student_answer,
        ]
        if not all(f.strip() for f in fields):
            st.warning("Please complete every field.")
        else:
            try:
                normalized_question = question.strip()
                normalized_answer = selected_question["correct_answer"]
                normalized_class = class_name.strip()
                normalized_student = student_name.strip()

                db.classes.update_one(
                    {"class_name": normalized_class},
                    {"$setOnInsert": {"class_name": normalized_class}},
                    upsert=True,
                )
                db.students.update_one(
                    {
                        "class_name": normalized_class,
                        "student_name": normalized_student,
                    },
                    {
                        "$setOnInsert": {
                            "class_name": normalized_class,
                            "student_name": normalized_student,
                        }
                    },
                    upsert=True,
                )

                db.responses.insert_one({
                    "class_name": normalized_class,
                    "student_name": normalized_student,
                    "subject": subject,
                    "topic": topic.strip(),
                    "question": normalized_question,
                    "correct_answer": normalized_answer,
                    "student_answer": student_answer.strip(),
                    "is_correct": is_correct,
                    "created_at": datetime.now(timezone.utc),
                    "analysis": None,
                })
                st.success("Response saved!")
            except Exception as e:
                st.error(f"Could not save: {e}")

# ---------- Responses ----------
with tab_view:
    df = load_df()
    if df.empty:
        st.info("No responses yet. Add one in the first tab.")
    else:
        wanted = ["created_at", "class_name", "student_name", "subject", "topic",
                  "question", "student_answer", "is_correct"]
        st.dataframe(df[[c for c in wanted if c in df.columns]], hide_index=True)

# ---------- Class insights ----------
with tab_insights:
    df = load_df()
    st.subheader("Explore class results")
    if df.empty or "is_correct" not in df.columns:
        st.info("Add some responses first.")
    else:
        df = df.dropna(subset=["is_correct"])
        if df.empty:
            st.info("Add some responses first.")
        else:
            df["is_correct"] = df["is_correct"].astype(bool)
            classes = sorted(df["class_name"].dropna().unique())
            if not classes:
                st.info("No class results are available yet.")
            else:
                selected_class = st.selectbox(
                    "Class",
                    classes,
                    key="insights_class_select",
                )
                class_df = df[df["class_name"] == selected_class].copy()
                mode = st.radio(
                    "Explore results",
                    ["Class overview", "Individual student", "Question analysis"],
                    horizontal=True,
                    key="insights_mode",
                )

                if mode == "Individual student":
                    students = sorted(class_df["student_name"].dropna().unique())
                    if not students:
                        st.info("No students are recorded in this class yet.")
                    else:
                        student_name = st.selectbox(
                            "Student",
                            students,
                            key="insights_student_select",
                        )
                        selected_df = class_df[
                            class_df["student_name"] == student_name
                        ].copy()
                        first, second = st.columns(2)
                        first.metric("Questions answered", len(selected_df))
                        accuracy = (
                            round(100 * selected_df["is_correct"].mean())
                            if not selected_df.empty
                            else 0
                        )
                        second.metric("Accuracy", f"{accuracy}%")
                        st.dataframe(
                            selected_df[
                                [
                                    column
                                    for column in [
                                        "subject",
                                        "topic",
                                        "question",
                                        "student_answer",
                                        "correct_answer",
                                        "is_correct",
                                    ]
                                    if column in selected_df.columns
                                ]
                            ],
                            hide_index=True,
                            width="stretch",
                        )
                elif mode == "Question analysis":
                    subject = st.selectbox(
                        "Subject",
                        list(SUBJECT_TOPICS),
                        key="insights_subject_select",
                    )
                    topic = st.selectbox(
                        "Topic",
                        SUBJECT_TOPICS[subject],
                        key="insights_topic_select",
                    )
                    question_options = sorted(
                        class_df.loc[
                            (class_df["subject"] == subject)
                            & (class_df["topic"] == topic),
                            "question",
                        ].dropna().unique()
                    )
                    if not question_options:
                        st.info("No responses for this subject and topic in this class.")
                    else:
                        question = st.selectbox(
                            "Question",
                            question_options,
                            key="insights_question_select",
                        )
                        question_df = class_df[
                            (class_df["subject"] == subject)
                            & (class_df["topic"] == topic)
                            & (class_df["question"] == question)
                        ].copy()
                        first, second, third = st.columns(3)
                        first.metric("Responses", len(question_df))
                        second.metric("Correct", int(question_df["is_correct"].sum()))
                        third.metric(
                            "Incorrect",
                            int((~question_df["is_correct"]).sum()),
                        )
                        st.dataframe(
                            question_df[
                                [
                                    column
                                    for column in [
                                        "student_name",
                                        "student_answer",
                                        "correct_answer",
                                        "is_correct",
                                    ]
                                    if column in question_df.columns
                                ]
                            ].sort_values("student_name"),
                            hide_index=True,
                            width="stretch",
                        )
                else:
                    first, second, third = st.columns(3)
                    first.metric("Students", class_df["student_name"].nunique())
                    second.metric("Responses", len(class_df))
                    third.metric(
                        "Accuracy",
                        f"{round(100 * class_df['is_correct'].mean())}%",
                    )

                    topic_accuracy = (
                        class_df.groupby(["subject", "topic"])["is_correct"]
                        .mean()
                        .mul(100)
                        .round(0)
                        .reset_index(name="accuracy")
                    )
                    topic_accuracy["subject_topic"] = (
                        topic_accuracy["subject"] + " / " + topic_accuracy["topic"]
                    )
                    st.subheader("Accuracy by subject and topic")
                    st.bar_chart(topic_accuracy, x="subject_topic", y="accuracy")

                    st.subheader("Students")
                    student_summary = (
                        class_df.groupby("student_name")
                        .agg(
                            questions_answered=("question", "count"),
                            correct_answers=("is_correct", "sum"),
                            accuracy=("is_correct", "mean"),
                        )
                        .reset_index()
                    )
                    student_summary["accuracy"] = (
                        student_summary["accuracy"] * 100
                    ).round(0)
                    st.dataframe(
                        student_summary.sort_values("student_name"),
                        hide_index=True,
                        width="stretch",
                    )

# ---------- Misconception make-up ----------
with tab_chat:
    st.subheader("Misconception make-up")
    st.caption(
        "Choose an analysis scope first. Gemini runs only after you click "
        "**Analyze misconceptions**."
    )

    target_type = st.radio(
        "Analyze",
        ["Individual student", "Whole class", "All classes"],
        horizontal=True,
        key="makeup_target_type",
    )
    class_options = sorted(db.classes.distinct("class_name"))
    selected_class = None
    selected_student = None
    target_query = {"is_correct": False}

    if target_type in ("Individual student", "Whole class"):
        if not class_options:
            st.info("Add a class and student responses to get started.")
        else:
            selected_class = st.selectbox(
                "Class",
                class_options,
                index=None,
                placeholder="Select a class",
                key="makeup_class_v2",
            )
            if selected_class:
                target_query["class_name"] = selected_class

    if target_type == "Individual student" and selected_class:
        student_options = sorted(
            db.students.distinct("student_name", {"class_name": selected_class})
        )
        selected_student = st.selectbox(
            "Student",
            student_options,
            index=None,
            placeholder="Select a student",
            key="makeup_student_v2",
        )
        if selected_student:
            target_query["student_name"] = selected_student

    subjects = sorted(db.responses.distinct("subject"))
    selected_subject = st.selectbox(
        "Subject",
        subjects,
        index=None,
        placeholder="Select a subject",
        key="makeup_subject_v2",
    )
    level = st.radio(
        "Question scope",
        ["Subject overview", "Topic", "Question"],
        horizontal=True,
        key="makeup_level_v2",
    )

    selected_topic = None
    selected_question = None
    if selected_subject and level in ("Topic", "Question"):
        topic_query = {
            key: value
            for key, value in target_query.items()
            if key != "is_correct"
        }
        topic_query["subject"] = selected_subject
        topic_options = sorted(
            topic
            for topic in db.responses.distinct("topic", topic_query)
            if topic
        )
        selected_topic = st.selectbox(
            "Topic",
            topic_options,
            index=None,
            placeholder="Select a topic",
            key="makeup_topic_v2",
        )

    if selected_subject and level == "Question" and selected_topic:
        question_query = {
            **target_query,
            "subject": selected_subject,
            "topic": selected_topic,
        }
        question_options = sorted(
            question
            for question in db.responses.distinct("question", question_query)
            if question
        )
        selected_question = st.selectbox(
            "Question",
            question_options,
            index=None,
            placeholder="Select a question",
            key="makeup_question_v2",
        )

    scope_ready = (
        bool(class_options)
        and (target_type == "All classes" or bool(selected_class))
        and (target_type != "Individual student" or bool(selected_student))
        and bool(selected_subject)
        and (level == "Subject overview" or bool(selected_topic))
        and (level != "Question" or bool(selected_question))
    )

    if not scope_ready:
        st.info("Select the class/student and subject scope to continue.")
    else:
        focus_query = {**target_query, "subject": selected_subject}
        if selected_topic:
            focus_query["topic"] = selected_topic
        if selected_question:
            focus_query["question"] = selected_question

        total_incorrect = db.responses.count_documents(focus_query)
        if total_incorrect == 0:
            st.info("No incorrect answers are recorded in this selection.")
        else:
            scope_name = selected_subject
            if target_type == "All classes":
                scope_name = f"All classes / {scope_name}"
            elif target_type == "Whole class":
                scope_name = f"{selected_class} / {scope_name}"
            else:
                scope_name = f"{selected_class} / {selected_student} / {scope_name}"
            if selected_topic:
                scope_name = f"{scope_name} / {selected_topic}"
            if selected_question:
                scope_name = f"{scope_name} / {selected_question}"

            focus_responses = list(
                db.responses.find(focus_query)
                .sort("created_at", -1)
                .limit(30 if level == "Question" else 60)
            )
            evidence_responses = list(focus_responses)
            focus_indices = list(range(len(focus_responses)))
            if level == "Question":
                comparison_query = {
                    **target_query,
                    "$nor": [
                        {
                            "subject": selected_subject,
                            "topic": selected_topic,
                            "question": selected_question,
                        }
                    ],
                }
                comparison_responses = list(
                    db.responses.find(comparison_query)
                    .sort("created_at", -1)
                    .limit(30)
                )
                evidence_responses.extend(comparison_responses)

            examples = [
                {
                    "index": index,
                    "subject": response.get("subject", ""),
                    "topic": response.get("topic", ""),
                    "question": response.get("question", ""),
                    "correct_answer": response.get("correct_answer", ""),
                    "student_answer": response.get("student_answer", ""),
                }
                for index, response in enumerate(evidence_responses)
            ]
            analysis_key = hashlib.sha256(
                json.dumps(
                    {
                        "target": target_type,
                        "class": selected_class,
                        "student": selected_student,
                        "scope": scope_name,
                        "examples": examples,
                    },
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()

            if not os.getenv("GEMINI_API_KEY"):
                st.warning(
                    "Add GEMINI_API_KEY to .env to generate the overview and use "
                    "the make-up chat."
                )
            analyze_clicked = st.button(
                "Analyze misconceptions",
                type="primary",
                key=f"analyze_makeup_{analysis_key}",
                disabled=not bool(os.getenv("GEMINI_API_KEY")),
            )
            analysis_cache = st.session_state.setdefault(
                "misconception_analysis_cache", {}
            )
            if analyze_clicked:
                try:
                    with st.spinner("Analyzing answers with Gemini..."):
                        result = analyze_misconceptions(examples, focus_indices)
                    diagnosis_by_index = {}
                    for pattern in result["patterns"]:
                        for index in pattern["evidence_indices"]:
                            diagnosis_by_index.setdefault(
                                index,
                                {
                                    "misconception": pattern["label"],
                                    "misconception_detail": pattern["explanation"],
                                    "confidence": pattern["confidence"],
                                },
                            )
                    for index, response in enumerate(evidence_responses):
                        diagnosis = diagnosis_by_index.get(index)
                        db.responses.update_one(
                            {"_id": response["_id"]},
                            {
                                "$set": {
                                    "analysis": {
                                        "source": "gemini",
                                        "version": 2,
                                        "misconception": diagnosis["misconception"]
                                        if diagnosis
                                        else None,
                                        "misconception_detail": diagnosis[
                                            "misconception_detail"
                                        ]
                                        if diagnosis
                                        else None,
                                        "confidence": diagnosis["confidence"]
                                        if diagnosis
                                        else None,
                                        "uncertain": index
                                        in result["uncertain_indices"],
                                    }
                                }
                            },
                        )
                    analysis_cache[analysis_key] = result
                except Exception as e:
                    st.error(f"Gemini could not analyze these answers: {e}")

            result = analysis_cache.get(analysis_key)
            if result:
                if total_incorrect > len(focus_responses):
                    st.caption(
                        f"Analyzed {len(focus_responses)} of {total_incorrect} "
                        "incorrect answers in this scope."
                    )
                st.markdown("#### AI overview")
                st.info(result["overview"])
                first, second, third = st.columns(3)
                first.metric("Incorrect answers", total_incorrect)
                second.metric("Evidence-backed patterns", len(result["patterns"]))
                third.metric(
                    "Answers needing more evidence",
                    len(result["uncertain_indices"]),
                )

                if result["patterns"]:
                    st.markdown("#### Possible misconceptions")
                    for pattern in result["patterns"]:
                        with st.container(border=True):
                            st.markdown(
                                f"**{pattern['label']}** "
                                f"({pattern['confidence']} confidence)"
                            )
                            st.write(pattern["explanation"])
                            for index in pattern["evidence_indices"]:
                                if index >= len(evidence_responses):
                                    continue
                                response = evidence_responses[index]
                                st.caption(
                                    f"{response.get('subject', '')} / "
                                    f"{response.get('topic', '')} ? "
                                    f"{response.get('question', '')}"
                                )
                                st.write(
                                    f"Student answer: "
                                    f"{response.get('student_answer', '')} | "
                                    f"Correct answer: "
                                    f"{response.get('correct_answer', '')}"
                                )
                else:
                    st.success(
                        "Gemini did not find enough evidence to assign a specific "
                        "misconception."
                    )

                uncertain = [
                    evidence_responses[index]
                    for index in result["uncertain_indices"]
                    if index < len(evidence_responses)
                ]
                if uncertain:
                    with st.expander("Incorrect answers that need more evidence"):
                        st.dataframe(
                            pd.DataFrame(
                                [
                                    {
                                        "subject": item.get("subject", ""),
                                        "topic": item.get("topic", ""),
                                        "question": item.get("question", ""),
                                        "student_answer": item.get("student_answer", ""),
                                        "correct_answer": item.get("correct_answer", ""),
                                    }
                                    for item in uncertain
                                ]
                            ),
                            hide_index=True,
                            width="stretch",
                        )

                if level == "Question":
                    related = [
                        evidence_responses[index]
                        for index in result["related_error_indices"]
                        if index < len(evidence_responses)
                        and index not in focus_indices
                    ]
                    st.markdown("#### Similar errors across other topics or subjects")
                    if related:
                        st.caption(
                            "Gemini found a possible connection from the answer evidence."
                        )
                        st.dataframe(
                            pd.DataFrame(
                                [
                                    {
                                        "subject": item.get("subject", ""),
                                        "topic": item.get("topic", ""),
                                        "question": item.get("question", ""),
                                        "student_answer": item.get("student_answer", ""),
                                        "correct_answer": item.get("correct_answer", ""),
                                    }
                                    for item in related
                                ]
                            ),
                            hide_index=True,
                            width="stretch",
                        )
                    else:
                        st.caption(
                            "Gemini did not find enough evidence to link this answer "
                            "to another error."
                        )

                chat_context = (
                    f"Focus: {scope_name}\n"
                    f"AI misconception overview: {result['overview']}\n"
                    "Evidence-based patterns: "
                    f"{json.dumps(result['patterns'], ensure_ascii=True)}\n"
                    "Help the teacher explain these results and plan supportive, "
                    "age-appropriate make-up practice. Be clear when answer evidence "
                    "is insufficient; do not claim to know hidden reasoning."
                )
                conversations = st.session_state.setdefault(
                    "misconception_conversations", {}
                )
                history = conversations.setdefault(analysis_key, [])
                if st.button(
                    "Clear conversation",
                    key=f"clear_makeup_{analysis_key}",
                ):
                    conversations[analysis_key] = []
                    st.rerun()
                for turn in history:
                    with st.chat_message(turn["role"]):
                        st.markdown(turn["content"])
                prompt = st.chat_input(
                    "Ask Gemini to explain a pattern or suggest practice",
                    key=f"makeup_chat_{analysis_key}",
                )
                if prompt and prompt.strip():
                    prompt = prompt.strip()
                    try:
                        with st.spinner("Preparing a focused response..."):
                            reply = chat_about_misconceptions(
                                chat_context,
                                history,
                                prompt,
                            )
                    except Exception as e:
                        st.error(f"Gemini could not reply: {e}")
                    else:
                        history.extend(
                            [
                                {"role": "user", "content": prompt},
                                {"role": "assistant", "content": reply},
                            ]
                        )
                        st.rerun()
