import hashlib
import json
import os
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv
from pymongo import MongoClient

from analysis import analyze_misconceptions, chat_about_misconceptions

load_dotenv()

st.set_page_config(page_title="AIM Assist", page_icon="🎯", layout="wide")

components.html(
    """
    <style>
        body { overflow: hidden; }
        .portal-splash {
            position: fixed;
            inset: 0;
            background: radial-gradient(circle at top, rgba(102,126,234,0.32), transparent 38%),
                        linear-gradient(135deg, #050b14 0%, #0f172a 40%, #171f32 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 99999;
            animation: fadeIn 0.8s ease-out;
        }
        .portal-splash.hidden {
            opacity: 0;
            visibility: hidden;
            transition: opacity 0.8s ease, visibility 0.8s ease;
        }
        .portal-panel {
            background: rgba(15, 23, 42, 0.7);
            border: 1px solid rgba(148, 163, 184, 0.25);
            box-shadow: 0 30px 80px rgba(11, 18, 30, 0.8);
            border-radius: 28px;
            padding: 42px 52px;
            text-align: center;
            backdrop-filter: blur(14px);
            transform: translateY(0);
            animation: riseIn 0.9s cubic-bezier(.2,.8,.2,1);
        }
        .portal-badge {
            display: inline-flex;
            align-items: center;
            gap: 10px;
            border: 1px solid rgba(96, 165, 250, 0.38);
            background: rgba(96,165,250,0.08);
            color: #dfeeff;
            border-radius: 999px;
            padding: 8px 16px;
            font-size: 12px;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            margin-bottom: 18px;
            font-weight: 700;
        }
        .portal-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #7dd3fc;
            box-shadow: 0 0 20px rgba(125,211,252,0.9);
            animation: pulse 1.6s ease-in-out infinite;
        }
        .portal-title {
            font-size: clamp(2.5rem, 5vw, 4rem);
            margin: 0;
            font-weight: 800;
            letter-spacing: -0.06em;
            background: linear-gradient(135deg, #f8fbff 0%, #b9d7ff 28%, #8eb8ff 52%, #d7c0ff 100%);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
        }
        .portal-subtitle {
            margin-top: 10px;
            color: rgba(226,232,240,0.8);
            font-size: 1rem;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }
        .portal-loader {
            margin-top: 26px;
            display: flex;
            justify-content: center;
            gap: 10px;
        }
        .portal-loader span {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: linear-gradient(135deg, #8ab4ff, #d4a9ff);
            animation: bounce 1.1s ease-in-out infinite;
        }
        .portal-loader span:nth-child(2) { animation-delay: 0.15s; }
        .portal-loader span:nth-child(3) { animation-delay: 0.3s; }
        @keyframes riseIn { 0% { opacity: 0; transform: translateY(30px) scale(0.98); } 100% { opacity: 1; transform: translateY(0) scale(1); } }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        @keyframes pulse { 0%, 100% { transform: scale(1); opacity: 0.8; } 50% { transform: scale(1.5); opacity: 1; } }
        @keyframes bounce { 0%, 80%, 100% { transform: translateY(0); opacity: 0.4; } 40% { transform: translateY(-12px); opacity: 1; } }
    </style>
    <div id="portal-splash" class="portal-splash">
      <div class="portal-panel">
        <div class="portal-badge"><span class="portal-dot"></span> Learning intelligence</div>
        <h1 class="portal-title">AIM Assist</h1>
        <div class="portal-subtitle">Opening your teaching insight portal</div>
        <div class="portal-loader"><span></span><span></span><span></span></div>
      </div>
    </div>
    <script>
      setTimeout(function() {
        const splash = document.getElementById('portal-splash');
        if (splash) splash.classList.add('hidden');
      }, 1800);
    </script>
    """,
    height=0,
    scrolling=False,
)

st.markdown(
    """
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

        html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"] {
            background: radial-gradient(circle at top left, rgba(96,165,250,0.18), transparent 26%),
                        radial-gradient(circle at bottom right, rgba(168,85,247,0.18), transparent 32%),
                        linear-gradient(135deg, #07111f 0%, #0d1b2a 30%, #13243b 100%);
            color: #edf4ff;
            font-family: 'Inter', sans-serif;
        }

        .block-container {
            padding-top: 1.5rem;
            padding-bottom: 3rem;
            max-width: 1500px;
        }

        [data-testid="stHeader"] {
            background: rgba(8, 15, 27, 0.6);
            backdrop-filter: blur(10px);
        }

        [data-stale="true"] {
            opacity: 1 !important;
            filter: none !important;
        }

        [data-testid="stStatusWidget"] {
            display: none !important;
        }

        body:has([data-stale="true"])::after {
            content: "";
            position: fixed;
            top: 1rem;
            right: 1.25rem;
            z-index: 100000;
            width: 18px;
            height: 18px;
            border: 2px solid rgba(191, 219, 254, 0.28);
            border-top-color: #93c5fd;
            border-right-color: #c4b5fd;
            border-radius: 50%;
            animation: loadingSpin 0.75s linear infinite;
            pointer-events: none;
        }

        .main-header {
            position: relative;
            padding: 1.4rem 1.5rem 0.8rem;
            margin-bottom: 1.2rem;
            background: linear-gradient(135deg, rgba(15,23,42,0.72), rgba(30,41,59,0.58));
            border: 1px solid rgba(148,163,184,0.18);
            border-radius: 24px;
            box-shadow: 0 24px 60px rgba(15, 23, 42, 0.35);
            overflow: hidden;
            animation: fadeUp 0.8s ease-out both;
        }

        .main-header::before {
            content: "";
            position: absolute;
            inset: 0;
            background: linear-gradient(120deg, rgba(59,130,246,0.18), rgba(168,85,247,0.12), transparent 70%);
            pointer-events: none;
        }

        .main-header h1 {
            margin: 0;
            font-size: clamp(2.2rem, 4vw, 3.2rem);
            font-weight: 800;
            letter-spacing: -0.06em;
            position: relative;
            z-index: 1;
        }

        .main-header p {
            position: relative;
            z-index: 1;
            margin: 0.8rem 0 0;
            color: rgba(226,232,240,0.8);
            font-size: 1rem;
        }

        .status-chip {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: rgba(96,165,250,0.12);
            border: 1px solid rgba(147,197,253,0.25);
            color: #dfeeff;
            border-radius: 999px;
            padding: 7px 12px;
            margin-bottom: 1rem;
            font-size: 0.72rem;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            font-weight: 700;
        }

        .status-chip-dot {
            width: 9px;
            height: 9px;
            border-radius: 50%;
            background: #7dd3fc;
            box-shadow: 0 0 18px rgba(125,211,252,0.9);
            animation: pulse 1.8s ease-in-out infinite;
        }

        .floating-card {
            background: rgba(15, 23, 42, 0.74);
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 18px;
            padding: 1rem 1.1rem;
            box-shadow: 0 18px 36px rgba(2,6,23,0.18);
            transition: transform 0.2s ease, border-color 0.2s ease;
            animation: fadeUp 0.85s ease-out both;
        }

        .floating-card:hover {
            transform: translateY(-3px);
            border-color: rgba(147,197,253,0.35);
        }

        .stTabs [role="tablist"] {
            position: relative;
            gap: 0.7rem;
            margin-bottom: 1rem;
            background: rgba(15, 23, 42, 0.28);
            padding: 0.4rem;
            border-radius: 18px;
            border: 1px solid rgba(148,163,184,0.14);
        }

        .stTabs [role="tab"] {
            position: relative;
            z-index: 1;
            background: transparent;
            border: 1px solid transparent;
            border-radius: 999px;
            color: #dfe9ff;
            padding: 0.8rem 1.1rem;
            font-weight: 700;
            transition: color 0.2s ease, border-color 0.2s ease;
        }

        .stTabs [role="tab"][aria-selected="true"] {
            color: #ffffff;
            border-color: transparent;
            box-shadow: none;
        }

        .stTabs [data-baseweb="tab-highlight"] {
            z-index: 0;
            height: 100%;
            top: 0;
            bottom: auto;
            border: 1px solid rgba(147, 197, 253, 0.36);
            border-radius: 999px;
            background: linear-gradient(
                120deg,
                rgba(59, 130, 246, 0.24),
                rgba(168, 85, 247, 0.2)
            );
            box-shadow: 0 8px 24px rgba(91, 124, 255, 0.14);
            backdrop-filter: blur(10px);
            transition:
                transform 380ms cubic-bezier(0.2, 0.8, 0.2, 1),
                width 380ms cubic-bezier(0.2, 0.8, 0.2, 1),
                height 380ms cubic-bezier(0.2, 0.8, 0.2, 1);
        }

        .stTabs [data-baseweb="tab-border"] {
            display: none;
        }

        div[data-testid="stVerticalBlock"] > div > div {
            border-radius: 16px;
        }

        .stButton > button {
            background: linear-gradient(135deg, #4f8cff 0%, #7a4dff 100%);
            color: white;
            border: none;
            border-radius: 12px;
            font-weight: 800;
            padding: 0.7rem 1.3rem;
            box-shadow: 0 10px 20px rgba(85, 115, 255, 0.28);
            transition: transform 0.18s ease, box-shadow 0.18s ease;
        }

        .stButton > button:hover {
            transform: translateY(-2px);
            box-shadow: 0 18px 24px rgba(85, 115, 255, 0.36);
        }

        .stButton > button:active {
            transform: translateY(0);
        }

        .stDataFrame {
            border-radius: 16px;
            overflow: hidden;
            border: 1px solid rgba(148, 163, 184, 0.18);
            box-shadow: 0 18px 36px rgba(2,6,23,0.12);
        }

        .stMetric {
            background: rgba(15, 23, 42, 0.72);
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 16px;
            padding: 0.9rem 1rem;
            box-shadow: 0 12px 26px rgba(2,6,23,0.15);
        }

        section[data-testid="stSidebar"] {
            background: rgba(11, 18, 30, 0.82);
            border-right: 1px solid rgba(148, 163, 184, 0.14);
            backdrop-filter: blur(12px);
        }

        .stSelectbox > div > div, .stTextInput > div > div, .stTextArea > div > div {
            border-radius: 12px;
            border: 1px solid rgba(148,163,184,0.2) !important;
        }

        .stExpander {
            background: rgba(15, 23, 42, 0.45);
            border: 1px solid rgba(148,163,184,0.18);
            border-radius: 16px;
        }

        .stAlert {
            border-radius: 14px;
        }

        @keyframes pulse {
            0%, 100% { transform: scale(1); opacity: 0.8; }
            50% { transform: scale(1.5); opacity: 1; }
        }

        @keyframes fadeUp {
            from { opacity: 0; transform: translateY(12px); }
            to { opacity: 1; transform: translateY(0); }
        }

        @keyframes loadingSpin {
            to { transform: rotate(360deg); }
        }

        @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after {
                animation-duration: 0.01ms !important;
                animation-iteration-count: 1 !important;
                scroll-behavior: auto !important;
                transition-duration: 0.01ms !important;
            }
        }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="main-header">
        <div class="status-chip"><span class="status-chip-dot"></span> Portal online</div>
        <h1>🎯 AIM Assist</h1>
        <p>AI-powered support for recording answers, tracking class performance, and spotting likely misconceptions.</p>
    </div>
    """,
    unsafe_allow_html=True,
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
        df = df.copy()
        if "created_at" in df.columns:
            df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
        if "is_correct" in df.columns:
            df["is_correct"] = df["is_correct"].astype(bool)

        class_options = ["All classes"] + sorted(df["class_name"].dropna().unique())
        selected_class = st.selectbox("Class", class_options, index=0)

        student_options = ["All students"]
        if selected_class != "All classes":
            student_options += sorted(
                df.loc[df["class_name"] == selected_class, "student_name"].dropna().unique()
            )
        selected_student = st.selectbox("Student", student_options, index=0)

        subject_options = ["All subjects"] + sorted(df["subject"].dropna().unique())
        selected_subject = st.selectbox("Subject", subject_options, index=0)

        topic_options = ["All topics"]
        if selected_subject != "All subjects":
            topic_options += sorted(
                df.loc[df["subject"] == selected_subject, "topic"].dropna().unique()
            )
        selected_topic = st.selectbox("Topic", topic_options, index=0)

        question_options = ["All questions"]
        filtered_question_df = df
        if selected_class != "All classes":
            filtered_question_df = filtered_question_df[
                filtered_question_df["class_name"] == selected_class
            ]
        if selected_student != "All students":
            filtered_question_df = filtered_question_df[
                filtered_question_df["student_name"] == selected_student
            ]
        if selected_subject != "All subjects":
            filtered_question_df = filtered_question_df[
                filtered_question_df["subject"] == selected_subject
            ]
        if selected_topic != "All topics":
            filtered_question_df = filtered_question_df[
                filtered_question_df["topic"] == selected_topic
            ]
        if not filtered_question_df.empty:
            question_options += sorted(filtered_question_df["question"].dropna().unique())
        selected_question = st.selectbox("Question", question_options, index=0)

        result_options = ["All results", "Correct", "Incorrect"]
        selected_result = st.selectbox("Result", result_options, index=0)

        filtered_df = df.copy()
        if selected_class != "All classes":
            filtered_df = filtered_df[filtered_df["class_name"] == selected_class]
        if selected_student != "All students":
            filtered_df = filtered_df[filtered_df["student_name"] == selected_student]
        if selected_subject != "All subjects":
            filtered_df = filtered_df[filtered_df["subject"] == selected_subject]
        if selected_topic != "All topics":
            filtered_df = filtered_df[filtered_df["topic"] == selected_topic]
        if selected_question != "All questions":
            filtered_df = filtered_df[filtered_df["question"] == selected_question]
        if selected_result == "Correct":
            filtered_df = filtered_df[filtered_df["is_correct"] == True]
        elif selected_result == "Incorrect":
            filtered_df = filtered_df[filtered_df["is_correct"] == False]

        st.subheader("Organised response view")
        if filtered_df.empty:
            st.info("No responses match the current selection. Try a different filter combination.")
        else:
            summary_cols = st.columns(4)
            summary_cols[0].metric("Responses", len(filtered_df))
            if "is_correct" in filtered_df.columns:
                summary_cols[1].metric("Correct", int(filtered_df["is_correct"].sum()))
                summary_cols[2].metric("Incorrect", int((~filtered_df["is_correct"]).sum()))
                accuracy = round(100 * filtered_df["is_correct"].mean()) if not filtered_df.empty else 0
                summary_cols[3].metric("Accuracy", f"{accuracy}%")

            wanted = [
                "created_at",
                "class_name",
                "student_name",
                "subject",
                "topic",
                "question",
                "student_answer",
                "correct_answer",
                "is_correct",
            ]
            display_df = filtered_df[[c for c in wanted if c in filtered_df.columns]].sort_values(
                by="created_at",
                ascending=False,
                kind="mergesort",
            )
            display_df = display_df.copy()
            if "created_at" in display_df.columns:
                display_df["created_at"] = display_df["created_at"].dt.strftime("%d %b %Y %H:%M")
            st.dataframe(display_df, hide_index=True, width="stretch")

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
