
import os
import streamlit as st
from dotenv import load_dotenv
from pymongo import MongoClient
from datetime import datetime, timezone

load_dotenv()

st.set_page_config(
    page_title="TeachAssist AI",
    page_icon="📚",
    layout="wide"
)

st.title("📚 TeachAssist AI")
st.write("Your AI-powered teaching assistant")
st.divider()

uri = os.getenv("MONGODB_URI")

if not uri:
    st.error("MongoDB connection string not found in .env")
    st.stop()

try:
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    db = client["teaching_assistant"]
except Exception:
    st.error("Could not connect to MongoDB. Check your connection settings.")
    st.stop()

st.subheader("Record a Student Answer")
st.write(
    "Enter a question, its correct answer, "
    "and the student's response."
)

with st.form("answer_form"):
    class_name = st.text_input("Class or group")
    student_name = st.text_input("Student name or ID")
    topic = st.text_input("Subject topic")

    question = st.text_area("Question")
    correct_answer = st.text_area("Correct answer")
    student_answer = st.text_area("Student's answer")

    submitted = st.form_submit_button("Save response")

if submitted:
    if not all([
        class_name.strip(),
        student_name.strip(),
        topic.strip(),
        question.strip(),
        correct_answer.strip(),
        student_answer.strip()
    ]):
        st.warning("Please complete every field.")
    else:
        response = {
            "class_name": class_name.strip(),
            "student_name": student_name.strip(),
            "topic": topic.strip(),
            "question": question.strip(),
            "correct_answer": correct_answer.strip(),
            "student_answer": student_answer.strip(),
            "created_at": datetime.now(timezone.utc),
            "analysis": None
        }

        try:
            db.responses.insert_one(response)
            st.success("Student response saved successfully!")
        except Exception:
            st.error("Could not save the response. Please try again.")

st.divider()
st.subheader("Stored Responses")

try:
    responses = list(
        db.responses.find(
            {},
            {
                "_id": 0,
                "student_name": 1,
                "topic": 1,
                "question": 1,
                "student_answer": 1,
                "created_at": 1
            }
        ).sort("created_at", -1).limit(20)
    )

    if responses:
        st.dataframe(responses, use_container_width=True)
    else:
        st.info("No responses recorded yet. Add your first one above.")
except Exception:
    st.error("Could not load saved responses.")

client.close()
