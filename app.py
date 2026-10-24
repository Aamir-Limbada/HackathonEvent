import os
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from pymongo import MongoClient

from analysis import chat_about_misconceptions

load_dotenv()

st.set_page_config(page_title="TeachAssist AI", page_icon="📚", layout="wide")
st.title("📚 TeachAssist AI")
st.caption("Record student answers and spot where the class is struggling.")

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
    ["✏️ Add response", "📋 Responses", "📊 Class insights", "🧠 Misconception make-up"]
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
        placeholder="Search questions or add a new one",
        accept_new_options=True,
        key="question_select",
        help="Choose a saved question or type a new one. New questions and answers are saved for this subject and topic.",
    )
    selected_question = questions_by_text.get(question) if question else None

    with st.form("answer_form", clear_on_submit=True):
        if selected_question:
            correct_answer = st.text_area(
                "Correct answer",
                value=selected_question["correct_answer"],
                disabled=True,
            )
        else:
            correct_answer = st.text_area("Correct answer")
        student_answer = st.text_area("Student's answer")
        is_correct = st.checkbox("Student's answer is correct")

        submitted = st.form_submit_button("Save response")

    if submitted:
        fields = [
            class_name or "",
            student_name or "",
            subject or "",
            topic or "",
            question or "",
            correct_answer,
            student_answer,
        ]
        if not all(f.strip() for f in fields):
            st.warning("Please complete every field.")
        else:
            try:
                normalized_question = question.strip()
                normalized_answer = correct_answer.strip()
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

                if selected_question is None:
                    db.questions.update_one(
                        {
                            "subject": subject,
                            "topic": topic,
                            "question": normalized_question,
                        },
                        {
                            "$setOnInsert": {
                                "subject": subject,
                                "topic": topic,
                                "question": normalized_question,
                                "correct_answer": normalized_answer,
                                "created_at": datetime.now(timezone.utc),
                            }
                        },
                        upsert=True,
                    )
                    saved_question = db.questions.find_one(
                        {
                            "subject": subject,
                            "topic": topic,
                            "question": normalized_question,
                        }
                    )
                    if saved_question is None:
                        raise RuntimeError("Could not load the saved question.")
                    normalized_answer = saved_question["correct_answer"]

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
                                        "analysis",
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
                                        "analysis",
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
        "Review a student's answers by subject, topic, or question, then use Gemini "
        "to plan a focused explanation and practice."
    )

    class_options = sorted(db.classes.distinct("class_name"))
    if not class_options:
        st.info("Add a class and student responses to get started.")
    else:
        selected_class = st.selectbox(
            "Class",
            class_options,
            key="makeup_class",
        )
        student_options = sorted(
            db.students.distinct("student_name", {"class_name": selected_class})
        )
        if not student_options:
            st.info("There are no students recorded in this class yet.")
        else:
            selected_student = st.selectbox(
                "Student",
                student_options,
                key="makeup_student",
            )
            student_filter = {
                "class_name": selected_class,
                "student_name": selected_student,
            }
            available_subjects = sorted(
                db.responses.distinct("subject", student_filter)
            )
            if not available_subjects:
                st.info("There are no saved responses for this student yet.")
            else:
                selected_subject = st.selectbox(
                    "Subject",
                    available_subjects,
                    key="makeup_subject",
                )
                subject_responses = list(
                    db.responses.find(
                        {**student_filter, "subject": selected_subject},
                        {"_id": 0, "class_name": 0, "student_name": 0},
                    ).sort("topic", 1)
                )
                level = st.radio(
                    "Explore misconceptions",
                    ["Subject overview", "Topic", "Question"],
                    horizontal=True,
                    key="makeup_level",
                )
                scoped_responses = subject_responses
                selected_topic = None
                selected_question = None

                if level in ("Topic", "Question"):
                    topic_options = sorted(
                        {response.get("topic", "") for response in subject_responses}
                        - {""}
                    )
                    if topic_options:
                        selected_topic = st.selectbox(
                            "Topic",
                            topic_options,
                            key="makeup_topic",
                        )
                        scoped_responses = [
                            response
                            for response in subject_responses
                            if response.get("topic") == selected_topic
                        ]

                if level == "Question":
                    incorrect_questions = sorted(
                        {
                            response.get("question", "")
                            for response in scoped_responses
                            if not response.get("is_correct", False)
                            and response.get("question")
                        }
                    )
                    question_options = incorrect_questions or sorted(
                        {
                            response.get("question", "")
                            for response in scoped_responses
                            if response.get("question")
                        }
                    )
                    if question_options:
                        selected_question = st.selectbox(
                            "Question",
                            question_options,
                            key="makeup_question",
                        )
                        scoped_responses = [
                            response
                            for response in scoped_responses
                            if response.get("question") == selected_question
                        ]

                scoped_incorrect = [
                    response
                    for response in scoped_responses
                    if not response.get("is_correct", False)
                ]
                diagnosis_rows = []
                for response in scoped_incorrect:
                    diagnosis = response.get("analysis")
                    if isinstance(diagnosis, dict) and diagnosis.get("misconception"):
                        diagnosis_rows.append(
                            {
                                "misconception": diagnosis["misconception"],
                                "topic": response.get("topic", ""),
                                "question": response.get("question", ""),
                                "student_answer": response.get("student_answer", ""),
                                "correct_answer": response.get("correct_answer", ""),
                                "knowledge_gap": diagnosis.get("knowledge_gap") or "",
                                "misconception_detail": diagnosis.get(
                                    "misconception_detail"
                                )
                                or "",
                            }
                        )

                if not scoped_incorrect:
                    st.success("No incorrect answers are recorded in this selection.")
                else:
                    first, second = st.columns(2)
                    first.metric("Answers to review", len(scoped_incorrect))
                    second.metric(
                        "Misconceptions identified",
                        len({row["misconception"] for row in diagnosis_rows}),
                    )
                    if diagnosis_rows:
                        summary = (
                            pd.DataFrame(diagnosis_rows)
                            .groupby("misconception", as_index=False)
                            .agg(
                                occurrences=("question", "count"),
                                knowledge_gap=("knowledge_gap", "first"),
                            )
                            .sort_values(
                                ["occurrences", "misconception"],
                                ascending=[False, True],
                            )
                        )
                        st.markdown("#### Misconceptions to work on")
                        st.dataframe(
                            summary,
                            hide_index=True,
                            width="stretch",
                        )
                        with st.expander("Review the student's answers"):
                            st.dataframe(
                                pd.DataFrame(diagnosis_rows)[
                                    [
                                        "topic",
                                        "question",
                                        "student_answer",
                                        "correct_answer",
                                        "misconception",
                                        "misconception_detail",
                                        "knowledge_gap",
                                    ]
                                ],
                                hide_index=True,
                                width="stretch",
                            )
                    else:
                        st.info(
                            "These answers are marked incorrect, but do not have "
                            "a saved misconception diagnosis yet."
                        )

                related_responses = []
                comparison_responses = []
                if level == "Question" and selected_question and scoped_incorrect:
                    selected_response = next(
                        (
                            response
                            for response in scoped_responses
                            if not response.get("is_correct", False)
                        ),
                        scoped_responses[0] if scoped_responses else None,
                    )
                    if selected_response:
                        selected_diagnosis = selected_response.get("analysis") or {}
                        label = (
                            selected_diagnosis.get("misconception")
                            if isinstance(selected_diagnosis, dict)
                            else None
                        )
                        if label:
                            related_responses = list(
                                db.responses.find(
                                    {
                                        **student_filter,
                                        "is_correct": False,
                                        "analysis.misconception": label,
                                        "$or": [
                                            {"subject": {"$ne": selected_subject}},
                                            {"topic": {"$ne": selected_topic}},
                                        ],
                                    },
                                    {
                                        "_id": 0,
                                        "subject": 1,
                                        "topic": 1,
                                        "question": 1,
                                        "student_answer": 1,
                                        "analysis.misconception": 1,
                                    },
                                ).limit(50)
                            )
                        comparison_responses = [
                            response
                            for response in db.responses.find(
                                {
                                    **student_filter,
                                    "is_correct": False,
                                },
                                {
                                    "_id": 0,
                                    "subject": 1,
                                    "topic": 1,
                                    "question": 1,
                                    "student_answer": 1,
                                    "correct_answer": 1,
                                    "analysis": 1,
                                },
                            )
                            if not (
                                response.get("subject") == selected_subject
                                and response.get("topic") == selected_topic
                                and response.get("question") == selected_question
                            )
                        ][:20]
                        st.markdown("#### Similar errors across other topics or subjects")
                        if related_responses:
                            st.caption(
                                "These answers share the same saved misconception label."
                            )
                            st.dataframe(
                                pd.DataFrame(
                                    [
                                        {
                                            "subject": item.get("subject", ""),
                                            "topic": item.get("topic", ""),
                                            "question": item.get("question", ""),
                                            "student_answer": item.get(
                                                "student_answer", ""
                                            ),
                                            "misconception": item.get(
                                                "analysis", {}
                                            ).get("misconception", ""),
                                        }
                                        for item in related_responses
                                    ]
                                ),
                                hide_index=True,
                                width="stretch",
                            )
                        else:
                            st.caption(
                                "No other answer has this exact saved misconception "
                                "label. The student's other mistakes are available "
                                "below for comparison."
                            )
                        if comparison_responses:
                            with st.expander(
                                "Compare with other mistakes from this student"
                            ):
                                st.dataframe(
                                    pd.DataFrame(
                                        [
                                            {
                                                "subject": item.get("subject", ""),
                                                "topic": item.get("topic", ""),
                                                "question": item.get("question", ""),
                                                "student_answer": item.get(
                                                    "student_answer", ""
                                                ),
                                                "misconception": (
                                                    item.get("analysis", {}).get(
                                                        "misconception", ""
                                                    )
                                                    if isinstance(
                                                        item.get("analysis"), dict
                                                    )
                                                    else ""
                                                ),
                                            }
                                            for item in comparison_responses
                                        ]
                                    ),
                                    hide_index=True,
                                    width="stretch",
                                )

                if level == "Question" and not scoped_incorrect:
                    st.info(
                        "Select a question with an incorrect answer to start a "
                        "question-focused make-up conversation."
                    )
                elif not os.getenv("GEMINI_API_KEY"):
                    st.warning(
                        "Add GEMINI_API_KEY to .env to start a Gemini conversation."
                    )
                else:
                    scope_name = (
                        f"{selected_subject} / {selected_topic}"
                        if selected_topic
                        else selected_subject
                    )
                    if selected_question:
                        scope_name = f"{scope_name} / selected question"
                    context_rows = scoped_incorrect[:30]
                    if level == "Question":
                        context_rows = (
                            scoped_incorrect[:1] + comparison_responses[:20]
                        )
                    context_lines = [
                        (
                            f"- {response.get('subject', '')} / "
                            f"{response.get('topic', '')}: "
                            f"Question: {response.get('question', '')}; "
                            f"student answer: {response.get('student_answer', '')}; "
                            f"correct answer: {response.get('correct_answer', '')}; "
                            f"diagnosis: "
                            f"{diagnosis.get('misconception', 'not diagnosed')}"
                        )
                        for response in context_rows
                        for diagnosis in [
                            response.get("analysis")
                            if isinstance(response.get("analysis"), dict)
                            else {}
                        ]
                    ]
                    chat_context = (
                        f"Selected focus: {scope_name}\n"
                        "Help the teacher plan supportive misconception make-up for "
                        "this student's incorrect answers. Explain patterns clearly, "
                        "suggest an age-appropriate reteaching step and short practice. "
                        "For a question-level focus, compare the selected error with "
                        "the other supplied errors and identify only genuinely related "
                        "patterns; do not claim a connection without evidence.\n"
                        "Incorrect-answer evidence:\n"
                        + ("\n".join(context_lines) or "- No diagnosed errors in scope.")
                    )
                    chat_key = (
                        f"{selected_class}|{selected_student}|{selected_subject}|"
                        f"{selected_topic or 'subject'}|"
                        f"{selected_question or 'overview'}"
                    )
                    conversations = st.session_state.setdefault(
                        "misconception_conversations", {}
                    )
                    history = conversations.setdefault(chat_key, [])
                    if st.button("Clear conversation", key=f"clear_makeup_{chat_key}"):
                        conversations[chat_key] = []
                        st.rerun()
                    for turn in history:
                        with st.chat_message(turn["role"]):
                            st.markdown(turn["content"])
                    prompt = st.chat_input(
                        "Ask Gemini about the pattern or request a make-up activity",
                        key=f"makeup_chat_{chat_key}",
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