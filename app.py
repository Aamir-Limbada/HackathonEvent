import os
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from pymongo import MongoClient

from analysis import chat_with_student

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
    ["✏️ Add response", "📋 Responses", "📊 Class insights", "💬 Error-correction chat"]
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
                            use_container_width=True,
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
                            use_container_width=True,
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
                        use_container_width=True,
                    )

# ---------- Error-correction chat ----------
with tab_chat:
    st.subheader("Learn from a student's mistake")
    st.write(
        "Choose a saved incorrect response to open a focused tutoring chat. "
        "The student's name and class are not sent to Gemini."
    )

    incorrect_responses = list(
        db.responses.find({"is_correct": False}).sort("created_at", -1).limit(100)
    )

    if not incorrect_responses:
        st.info("There are no saved incorrect responses to discuss yet.")
    elif not os.getenv("GEMINI_API_KEY"):
        st.error("GEMINI_API_KEY is missing. Add it to your .env file to use the tutor.")
    else:
        responses_by_id = {str(response["_id"]): response for response in incorrect_responses}
        response_ids = list(responses_by_id)

        def response_label(response_id):
            response = responses_by_id[response_id]
            question = response.get("question", "").replace("\n", " ")
            if len(question) > 70:
                question = f"{question[:67]}..."
            return (
                f"{response.get('student_name', 'Student')} | "
                f"{response.get('subject', 'No subject')} / "
                f"{response.get('topic', 'No topic')} | {question}"
            )

        selected_id = st.selectbox(
            "Choose an incorrect response",
            response_ids,
            format_func=response_label,
        )
        selected_response = responses_by_id[selected_id]

        st.markdown(
            f"**Subject and topic:** {selected_response.get('subject', '')} / "
            f"{selected_response.get('topic', '')}"
        )
        st.markdown(f"**Question:** {selected_response.get('question', '')}")
        st.markdown(f"**Student's answer:** {selected_response.get('student_answer', '')}")
        st.markdown(f"**Correct answer:** {selected_response.get('correct_answer', '')}")
        diagnosis = selected_response.get("analysis") or {}
        if diagnosis.get("misconception"):
            st.warning(
                f"**Demonstration diagnosis:** {diagnosis['misconception']}"
            )
            st.write(diagnosis.get("misconception_detail", ""))
            if diagnosis.get("knowledge_gap"):
                st.write(f"**Knowledge gap:** {diagnosis['knowledge_gap']}")
            if diagnosis.get("suggested_intervention"):
                st.write(
                    f"**Suggested intervention:** "
                    f"{diagnosis['suggested_intervention']}"
                )

        conversations = st.session_state.setdefault("tutor_conversations", {})
        history = conversations.setdefault(selected_id, [])

        if st.button("Clear this chat", key=f"clear_tutor_{selected_id}"):
            conversations[selected_id] = []
            st.rerun()

        for turn in history:
            with st.chat_message(turn["role"]):
                st.markdown(turn["content"])

        prompt = st.chat_input(
            "Ask for a hint, explanation, or another example",
            key=f"tutor_input_{selected_id}",
        )
        if prompt and prompt.strip():
            prompt = prompt.strip()
            try:
                with st.spinner("Thinking..."):
                    reply = chat_with_student(
                        (
                            f"{selected_response.get('subject', '')} / "
                            f"{selected_response.get('topic', '')}"
                        ),
                        selected_response.get("question", ""),
                        selected_response.get("correct_answer", ""),
                        selected_response.get("student_answer", ""),
                        history,
                        prompt,
                    )
            except Exception as e:
                st.error(f"Gemini could not reply: {e}")
            else:
                history.extend([
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": reply},
                ])
                st.rerun()