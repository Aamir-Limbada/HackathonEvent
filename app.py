import os
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

st.set_page_config(page_title="TeachAssist AI", page_icon="📚", layout="wide")
st.title("📚 TeachAssist AI")
st.caption("Record student answers and spot where the class is struggling.")


@st.cache_resource
def get_db():
    uri = os.getenv("MONGODB_URI")
    if not uri:
        raise RuntimeError("MONGODB_URI not found in .env")
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    return client["teaching_assistant"]


try:
    db = get_db()
except Exception as e:
    st.error(f"Could not connect to MongoDB: {e}")
    st.stop()


def load_df():
    docs = list(db.responses.find({}, {"_id": 0}).sort("created_at", -1))
    return pd.DataFrame(docs)


tab_add, tab_view, tab_insights = st.tabs(
    ["✏️ Add response", "📋 Responses", "📊 Class insights"]
)

# ---------- Add response ----------
with tab_add:
    with st.form("answer_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        class_name = c1.text_input("Class or group")
        student_name = c2.text_input("Student name or ID")
        topic = c3.text_input("Topic")

        question = st.text_area("Question")
        correct_answer = st.text_area("Correct answer")
        student_answer = st.text_area("Student's answer")
        is_correct = st.checkbox("Student's answer is correct")

        submitted = st.form_submit_button("Save response")

    if submitted:
        fields = [class_name, student_name, topic, question, correct_answer, student_answer]
        if not all(f.strip() for f in fields):
            st.warning("Please complete every field.")
        else:
            try:
                db.responses.insert_one({
                    "class_name": class_name.strip(),
                    "student_name": student_name.strip(),
                    "topic": topic.strip(),
                    "question": question.strip(),
                    "correct_answer": correct_answer.strip(),
                    "student_answer": student_answer.strip(),
                    "is_correct": is_correct,
                    "created_at": datetime.now(timezone.utc),
                    "analysis": None,  # the AI will fill this in later
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
        wanted = ["created_at", "class_name", "student_name", "topic",
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

            st.subheader("Accuracy by topic (%)")
            st.bar_chart(df.groupby("topic")["is_correct"].mean().mul(100).round(0))

            st.subheader("Most-missed questions")
            missed = (
                df[~df["is_correct"]]
                .groupby(["topic", "question"])
                .size()
                .reset_index(name="times_wrong")
                .sort_values("times_wrong", ascending=False)
            )
            if missed.empty:
                st.success("No wrong answers recorded yet.")
            else:
                st.dataframe(missed, hide_index=True)