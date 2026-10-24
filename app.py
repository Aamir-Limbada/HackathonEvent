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
    "English": [
        "Grammar",
        "Punctuation",
        "Reading comprehension",
        "Vocabulary",
        "Sentence structure",
        "Writing",
    ],
    "Maths": [
        "Number",
        "Fractions",
        "Decimals",
        "Percentages",
        "Algebra",
        "Geometry",
        "Statistics",
    ],
    "Science": [
        "Biology",
        "Chemistry",
        "Physics",
        "Cells",
        "Forces",
        "Electricity",
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


def select_or_add_existing_value(label, field, key):
    existing_values = {
        value.strip()
        for value in db.responses.distinct(field)
        if isinstance(value, str) and value.strip()
    }
    return st.selectbox(
        label,
        sorted(existing_values, key=str.casefold),
        index=None,
        placeholder=f"Type or select {label.lower()}",
        accept_new_options=True,
        key=key,
        help="Type to search existing values, or enter a new value. New values are saved with the response.",
    )


def reset_topic_selection():
    st.session_state["topic_select"] = None
    st.session_state["question_select"] = None


def reset_question_selection():
    st.session_state["question_select"] = None


tab_add, tab_view, tab_insights, tab_chat = st.tabs(
    ["✏️ Add response", "📋 Responses", "📊 Class insights", "💬 Error-correction chat"]
)

# ---------- Add response ----------
with tab_add:
    subject_col, topic_col = st.columns(2)
    subject = subject_col.selectbox(
        "Subject",
        list(SUBJECT_TOPICS),
        key="subject_select",
        on_change=reset_topic_selection,
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
        class_col, student_col = st.columns(2)
        with class_col:
            class_name = select_or_add_existing_value(
                "Class or group", "class_name", "class_name_select"
            )
        with student_col:
            student_name = select_or_add_existing_value(
                "Student name or ID", "student_name", "student_name_select"
            )

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
                    "class_name": class_name.strip(),
                    "student_name": student_name.strip(),
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
    if df.empty or "is_correct" not in df.columns:
        st.info("Add some responses first.")
    else:
        df = df.dropna(subset=["is_correct"])
        if df.empty:
            st.info("Add some responses first.")
        else:
            df["is_correct"] = df["is_correct"].astype(bool)

            m1, m2, m3 = st.columns(3)
            m1.metric("Responses", len(df))
            m2.metric("Students", df["student_name"].nunique())
            m3.metric("Overall accuracy", f"{round(100 * df['is_correct'].mean())}%")

            group_fields = ["topic"]
            if "subject" in df.columns:
                group_fields.insert(0, "subject")
            st.subheader("Accuracy by subject and topic (%)")
            st.bar_chart(
                df.groupby(group_fields)["is_correct"].mean().mul(100).round(0)
            )

            st.subheader("Most-missed questions")
            missed = (
                df[~df["is_correct"]]
                .groupby(["subject", "topic", "question"])
                .size()
                .reset_index(name="times_wrong")
                .sort_values("times_wrong", ascending=False)
            )
            if missed.empty:
                st.success("No wrong answers recorded yet.")
            else:
                st.dataframe(missed, hide_index=True)

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
                        selected_response.get("topic", ""),
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