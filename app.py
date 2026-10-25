import hashlib
import hmac
import json
import os
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv
from pymongo import MongoClient
from streamlit.errors import StreamlitSecretNotFoundError

from agent_workflow import (
    VECTOR_COLLECTION_NAME,
    log_agent_action,
    rebuild_agent_packs,
    retry_agent_rows,
    run_agent_saved_responses,
)
from analysis import (
    analyze_misconceptions,
    chat_about_education,
    chat_about_misconceptions,
    generate_teaching_notes,
)

load_dotenv()
try:
    app_secrets = st.secrets
except StreamlitSecretNotFoundError:
    app_secrets = {}

for setting in (
    "MONGODB_URI",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GEMINI_EMBEDDING_MODEL",
    "APP_PASSWORD",
):
    if setting not in os.environ and setting in app_secrets:
        os.environ[setting] = str(app_secrets[setting])

st.set_page_config(page_title="AIM Assist", page_icon="📘", layout="wide")

access_password = os.getenv("APP_PASSWORD")
if not access_password:
    st.error(
        "App access is not configured. Set `APP_PASSWORD` in Streamlit Secrets "
        "or your local `.env` file."
    )
    st.stop()

if not st.session_state.get("app_authenticated"):
    with st.form("app_access_form"):
        st.title("AIM Assist")
        st.caption("Enter the shared access password to continue.")
        entered_password = st.text_input("Access password", type="password")
        submitted = st.form_submit_button("Unlock")
    if submitted:
        if hmac.compare_digest(entered_password, access_password):
            st.session_state["app_authenticated"] = True
            st.rerun()
        st.error("That password was not accepted.")
    st.stop()

if st.sidebar.button("Lock app"):
    st.session_state.pop("app_authenticated", None)
    st.rerun()

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
        <div class="portal-badge"><span class="portal-dot"></span> Learning Intelligence</div>
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
            max-width: 1740px;
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
            padding: 2rem 2rem 1.6rem;
            margin-bottom: 1.5rem;
            text-align: center;
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
            font-size: 1.08rem;
            letter-spacing: 0.06em;
        }

        .main-header .status-chip {
            justify-content: center;
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
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 0.45rem;
            margin-bottom: 1rem;
            background: rgba(15, 23, 42, 0.28);
            padding: 0.4rem;
            border-radius: 18px;
            border: 1px solid rgba(148,163,184,0.14);
            overflow: visible !important;
            height: auto !important;
        }

        .stTabs [role="tab"] {
            position: relative;
            z-index: 1;
            flex: 1 1 145px;
            justify-content: center;
            white-space: nowrap;
            background: transparent;
            border: 1px solid transparent;
            border-radius: 999px;
            color: #dfe9ff;
            padding: 0.7rem 0.8rem;
            font-weight: 700;
            transition: color 0.2s ease, border-color 0.2s ease;
        }

        .stTabs [role="tab"][aria-selected="true"] {
            color: #ffffff;
            border-color: rgba(147, 197, 253, 0.36);
            background: linear-gradient(
                120deg,
                rgba(59, 130, 246, 0.24),
                rgba(168, 85, 247, 0.2)
            );
            box-shadow: none;
        }

        .stTabs [data-baseweb="tab-highlight"] {
            display: none;
        }

        .stTabs [role="tablist"] > button:not([role="tab"]) {
            display: none !important;
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

        .insight-pie {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 1.25rem;
            min-height: 190px;
            padding: 1rem;
            background: rgba(15, 23, 42, 0.56);
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 16px;
        }

        .insight-pie-circle {
            width: 150px;
            height: 150px;
            flex: 0 0 150px;
            border: 3px solid rgba(226, 232, 240, 0.82);
            border-radius: 50%;
        }

        .insight-pie-legend {
            display: grid;
            gap: 0.7rem;
            color: #edf4ff;
            font-size: 0.9rem;
        }

        .insight-pie-legend-item {
            display: flex;
            align-items: center;
            gap: 0.55rem;
        }

        .insight-pie-swatch {
            width: 0.75rem;
            height: 0.75rem;
            flex: 0 0 0.75rem;
            border-radius: 50%;
        }

        @media (max-width: 520px) {
            .insight-pie {
                gap: 0.8rem;
                padding: 0.75rem;
            }

            .insight-pie-circle {
                width: 120px;
                height: 120px;
                flex-basis: 120px;
            }
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
        <div class="status-chip"><span class="status-chip-dot"></span> Portal Online</div>
        <h1>📘 AIM Assist</h1>
        <p>See the thinking. Shape the learning.</p>
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
    database.teaching_resources.create_index([("created_at", -1)])
    database.teaching_resources.create_index(
        [("subject", 1), ("topic", 1), ("created_at", -1)]
    )
    database.agent_runs.create_index([("created_at", -1)])
    database.agent_runs.create_index("run_id", unique=True)
    database.responses.create_index(
        [("agent_run_id", 1), ("agent_row_number", 1)],
        unique=True,
        sparse=True,
    )
    vector_collection_info = list(
        database.list_collections(filter={"name": VECTOR_COLLECTION_NAME})
    )
    if vector_collection_info:
        collection_info = vector_collection_info[0]
        if (
            collection_info.get("type") == "timeseries"
            or collection_info.get("options", {}).get("timeseries")
        ):
            raise RuntimeError(
                f"{VECTOR_COLLECTION_NAME} must be a regular collection, not a "
                "time-series collection, for Atlas Vector Search."
            )
    else:
        database.create_collection(VECTOR_COLLECTION_NAME)
    database[VECTOR_COLLECTION_NAME].create_index("label_key", unique=True)
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


def prepare_teaching_notes(subject, topic, focus):
    st.session_state["teaching_assistant_subject"] = subject
    st.session_state["teaching_assistant_topic"] = topic
    st.session_state["teacher_notes_focus"] = focus
    st.session_state["main_navigation_tabs"] = "💬 Teaching Assistant"


def render_insight_pie(correct, incorrect):
    total = correct + incorrect
    correct_percentage = round(100 * correct / total) if total else 0
    incorrect_percentage = 100 - correct_percentage
    st.markdown(
        f"""
        <div class="insight-pie">
            <div class="insight-pie-circle" role="img"
                 aria-label="Correct: {correct}, Incorrect: {incorrect}"
                 style="background: conic-gradient(
                     #34d399 0 {correct_percentage}%,
                     #fb7185 {correct_percentage}% 100%
                 );"></div>
            <div class="insight-pie-legend">
                <div class="insight-pie-legend-item">
                    <span class="insight-pie-swatch" style="background:#34d399"></span>
                    <span>Correct: {correct} ({correct_percentage}%)</span>
                </div>
                <div class="insight-pie-legend-item">
                    <span class="insight-pie-swatch" style="background:#fb7185"></span>
                    <span>Incorrect: {incorrect} ({incorrect_percentage}%)</span>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


tab_add, tab_questions, tab_view, tab_insights, tab_chat, tab_assistant, tab_library, tab_agent = st.tabs(
    [
        "📝 Record Response",
        "📚 Question Bank",
        "📋 Responses",
        "📈 Class Insights",
        "🧠 Misconception Insights",
        "💬 Teaching Assistant",
        "📂 Teaching Library",
        "🤖 Class Agent",
    ],
    key="main_navigation_tabs",
    on_change="rerun",
)

# ---------- Question bank ----------
with tab_questions:
    st.subheader("Question Bank")
    st.caption(
        "Create a complete question and answer, then assign it to a subject and topic."
    )
    bank_subject = st.selectbox(
        "Subject",
        list(SUBJECT_TOPICS),
        key="question_bank_subject",
    )
    bank_topic = st.selectbox(
        "Topic",
        SUBJECT_TOPICS[bank_subject],
        key=f"question_bank_topic_{bank_subject}",
    )
    with st.form("question_bank_form"):
        bank_question = st.text_area("Question")
        bank_answer = st.text_area("Correct answer")
        save_question = st.form_submit_button("Save to question bank")

    if save_question:
        if not bank_question.strip() or not bank_answer.strip():
            st.warning("Enter both the question and its correct answer.")
        else:
            try:
                saved = db.questions.update_one(
                    {
                        "subject": bank_subject,
                        "topic": bank_topic,
                        "question": bank_question.strip(),
                    },
                    {
                        "$setOnInsert": {
                            "subject": bank_subject,
                            "topic": bank_topic,
                            "question": bank_question.strip(),
                            "correct_answer": bank_answer.strip(),
                            "created_at": datetime.now(timezone.utc),
                        }
                    },
                    upsert=True,
                )
                if saved.upserted_id:
                    st.success("Question added to the question bank.")
                else:
                    st.info("That question is already in the question bank.")
            except Exception as e:
                st.error(f"Could not save question: {e}")

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

    with st.form("answer_form", clear_on_submit=True):
        student_answer = st.text_area("Student's answer")
        is_correct = st.checkbox("Student's answer is correct")

        submitted = st.form_submit_button(
            "Save response",
            disabled=selected_question is None,
        )
    st.caption(
        "Misconceptions are identified by Gemini in Misconception insights; "
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

        st.subheader("Organised Response View")
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
    st.subheader("Explore Class Results")
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
                    ["Class Overview", "Student Insights", "Question Analysis"],
                    horizontal=True,
                    key="insights_mode_v3",
                )

                if mode == "Student Insights":
                    students = sorted(class_df["student_name"].dropna().unique())
                    if not students:
                        st.info("No students are recorded in this class yet.")
                    else:
                        student_name = st.selectbox(
                            "Student",
                            students,
                            key="insights_student_select",
                        )
                        student_df = class_df[
                            class_df["student_name"] == student_name
                        ].copy()
                        total_correct = int(student_df["is_correct"].sum())
                        total_incorrect = int((~student_df["is_correct"]).sum())
                        accuracy = round(100 * total_correct / len(student_df))

                        st.markdown(f"#### {student_name} — Performance Overview")
                        metrics = st.columns(4)
                        metrics[0].metric("Questions Answered", len(student_df))
                        metrics[1].metric("Correct", total_correct)
                        metrics[2].metric("Incorrect", total_incorrect)
                        metrics[3].metric("Overall Understanding", f"{accuracy}%")

                        st.markdown("#### Correct and Incorrect Answers")
                        render_insight_pie(total_correct, total_incorrect)

                        st.markdown("#### Understanding by Topic")
                        topic_summary = (
                            student_df.dropna(subset=["subject", "topic"])
                            .groupby(["subject", "topic"])["is_correct"]
                            .agg(correct="sum", answered="count")
                            .reset_index()
                        )
                        if topic_summary.empty:
                            st.info("No subject and topic details are available.")
                        else:
                            topic_summary["incorrect"] = (
                                topic_summary["answered"] - topic_summary["correct"]
                            )
                            topic_summary["understanding"] = (
                                topic_summary["correct"]
                                .div(topic_summary["answered"])
                                .mul(100)
                                .round()
                                .astype(int)
                            )
                            topic_summary = topic_summary.sort_values(
                                "understanding",
                                ascending=True,
                            )
                            for start in range(0, len(topic_summary), 2):
                                topic_columns = st.columns(2)
                                for column, (_, topic_row) in zip(
                                    topic_columns,
                                    topic_summary.iloc[start : start + 2].iterrows(),
                                ):
                                    with column:
                                        st.markdown(
                                            f"**{topic_row['subject']} / "
                                            f"{topic_row['topic']}**"
                                        )
                                        st.caption(
                                            f"Understanding: "
                                            f"{topic_row['understanding']}% "
                                            f"({topic_row['correct']} correct, "
                                            f"{topic_row['incorrect']} incorrect)"
                                        )
                                        render_insight_pie(
                                            int(topic_row["correct"]),
                                            int(topic_row["incorrect"]),
                                        )

                        st.markdown("#### Answered Questions")
                        filter_columns = st.columns(2)
                        available_subjects = sorted(
                            student_df["subject"].dropna().unique()
                        )
                        selected_subject_filter = filter_columns[0].selectbox(
                            "Filter by subject",
                            ["All subjects", *available_subjects],
                            key="student_insights_subject_filter",
                        )
                        if selected_subject_filter == "All subjects":
                            available_topics = sorted(
                                student_df["topic"].dropna().unique()
                            )
                        else:
                            available_topics = sorted(
                                student_df.loc[
                                    student_df["subject"] == selected_subject_filter,
                                    "topic",
                                ]
                                .dropna()
                                .unique()
                            )
                        selected_topic_filter = filter_columns[1].selectbox(
                            "Filter by topic",
                            ["All topics", *available_topics],
                            key="student_insights_topic_filter",
                        )
                        wrong_only = st.toggle(
                            "Show incorrect answers only",
                            key="student_insights_wrong_only",
                        )
                        question_df = student_df.copy()
                        if selected_subject_filter != "All subjects":
                            question_df = question_df[
                                question_df["subject"] == selected_subject_filter
                            ]
                        if selected_topic_filter != "All topics":
                            question_df = question_df[
                                question_df["topic"] == selected_topic_filter
                            ]
                        if wrong_only:
                            question_df = question_df[~question_df["is_correct"]]

                        if question_df.empty:
                            st.info("No answered questions match these filters.")
                        else:
                            question_columns = [
                                column
                                for column in [
                                    "created_at",
                                    "subject",
                                    "topic",
                                    "question",
                                    "student_answer",
                                    "correct_answer",
                                    "is_correct",
                                ]
                                if column in question_df.columns
                            ]
                            question_display = question_df[question_columns].copy()
                            question_display["is_correct"] = question_display[
                                "is_correct"
                            ].map({True: "Correct", False: "Incorrect"})
                            if "created_at" in question_display.columns:
                                question_display = question_display.sort_values(
                                    "created_at",
                                    ascending=False,
                                    kind="mergesort",
                                )
                            question_display = question_display.rename(
                                columns={
                                    "created_at": "Date",
                                    "subject": "Subject",
                                    "topic": "Topic",
                                    "question": "Question",
                                    "student_answer": "Student answer",
                                    "correct_answer": "Correct answer",
                                    "is_correct": "Result",
                                }
                            )
                            st.dataframe(
                                question_display,
                                hide_index=True,
                                width="stretch",
                            )
                elif mode == "Question Analysis":
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
                    st.subheader("Accuracy by Subject and Topic")
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

# ---------- Misconception insights ----------
with tab_chat:
    st.subheader("Misconception Insights")
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
                st.markdown("#### AI Overview")
                st.info(result["overview"])
                first, second, third = st.columns(3)
                first.metric("Incorrect answers", total_incorrect)
                second.metric("Evidence-backed patterns", len(result["patterns"]))
                third.metric(
                    "Answers needing more evidence",
                    len(result["uncertain_indices"]),
                )

                if result["patterns"]:
                    st.markdown("#### Possible Misconceptions")
                    for pattern_index, pattern in enumerate(result["patterns"]):
                        with st.container(border=True):
                            st.markdown(
                                f"**{pattern['label']}** "
                                f"({pattern['confidence']} confidence)"
                            )
                            st.write(pattern["explanation"])
                            pattern_evidence = []
                            for index in pattern["evidence_indices"]:
                                if index >= len(evidence_responses):
                                    continue
                                response = evidence_responses[index]
                                pattern_evidence.append(response)
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
                            if pattern_evidence:
                                evidence_text = "\n".join(
                                    (
                                        f"- Question: {item.get('question', '')}\n"
                                        f"  Correct answer: {item.get('correct_answer', '')}\n"
                                        f"  Student answer: {item.get('student_answer', '')}"
                                    )
                                    for item in pattern_evidence
                                )
                                notes_focus = (
                                    "Create focused teaching notes to address this "
                                    "evidence-backed misconception.\n"
                                    f"Misconception: {pattern['label']}\n"
                                    f"Gemini's explanation: {pattern['explanation']}\n"
                                    "Question and answer evidence:\n"
                                    f"{evidence_text}\n"
                                    "Explain the correct reasoning, why this "
                                    "misconception may be tempting, and a practical "
                                    "reteaching approach. Include a short check for "
                                    "understanding. Do not assume reasoning beyond "
                                    "the supplied evidence."
                                )
                                notes_topic = selected_topic or pattern_evidence[0].get(
                                    "topic", ""
                                )
                                st.button(
                                    "Prepare teaching notes in Teaching Assistant",
                                    key=(
                                        f"prepare_misconception_notes_"
                                        f"{analysis_key}_{pattern_index}"
                                    ),
                                    on_click=prepare_teaching_notes,
                                    args=(selected_subject, notes_topic, notes_focus),
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
                    with st.expander("Incorrect Answers That Need More Evidence"):
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
                    st.markdown("#### Similar Errors Across Other Topics or Subjects")
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
                    "age-appropriate follow-up practice. Be clear when answer evidence "
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

# ---------- Teaching library ----------
with tab_library:
    st.subheader("Teaching Library")
    st.caption("Your saved AI-created teaching resources, ready whenever you need them.")
    try:
        teaching_resources = list(
            db.teaching_resources.find(
                {},
                {
                    "title": 1,
                    "subject": 1,
                    "topic": 1,
                    "content": 1,
                    "created_at": 1,
                },
            ).sort("created_at", -1)
        )
    except Exception as e:
        st.error(f"Could not load your Teaching Library: {e}")
        teaching_resources = []

    if not teaching_resources:
        st.info("No saved resources yet. Create and save teaching notes in the Teaching Assistant.")
    else:
        resource_subjects = sorted(
            {
                resource["subject"]
                for resource in teaching_resources
                if resource.get("subject")
            }
        )
        subject_filter = st.selectbox(
            "Filter by Subject",
            ["All Subjects", *resource_subjects],
            key="teaching_library_subject_filter",
        )
        matching_resources = teaching_resources
        if subject_filter != "All Subjects":
            matching_resources = [
                resource
                for resource in matching_resources
                if resource.get("subject") == subject_filter
            ]
        resource_topics = sorted(
            {
                resource["topic"]
                for resource in matching_resources
                if resource.get("topic")
            }
        )
        topic_filter = st.selectbox(
            "Filter by Topic",
            ["All Topics", *resource_topics],
            key=f"teaching_library_topic_filter_{subject_filter}",
        )
        if topic_filter != "All Topics":
            matching_resources = [
                resource
                for resource in matching_resources
                if resource.get("topic") == topic_filter
            ]

        if not matching_resources:
            st.info("No saved resources match these filters.")
        else:
            resources_by_id = {
                str(resource["_id"]): resource for resource in matching_resources
            }
            selected_resource_id = st.selectbox(
                "Choose a Saved Resource",
                list(resources_by_id),
                format_func=lambda resource_id: (
                    f"{resources_by_id[resource_id].get('title', 'Untitled Resource')} · "
                    f"{resources_by_id[resource_id].get('subject', 'Unassigned')} / "
                    f"{resources_by_id[resource_id].get('topic', 'Unassigned')}"
                ),
                key=f"teaching_library_resource_{subject_filter}_{topic_filter}",
            )
            selected_resource = resources_by_id[selected_resource_id]
            st.markdown(
                f"### {selected_resource.get('title', 'Untitled Resource')}"
            )
            st.caption(
                f"{selected_resource.get('subject', 'Unassigned')} / "
                f"{selected_resource.get('topic', 'Unassigned')}"
            )
            st.markdown(selected_resource.get("content", "No content is available."))

# ---------- Teaching assistant ----------
with tab_assistant:
    st.subheader("Teaching Assistant")
    st.caption(
        "Plan lessons, clarify concepts, create classroom materials, and adapt support "
        "for your learners."
    )
    study_subject = st.selectbox(
        "Subject",
        ["Any Subject", *SUBJECT_TOPICS],
        key="teaching_assistant_subject",
    )
    study_topic = None
    if study_subject != "Any Subject":
        study_topic = st.selectbox(
            "Topic",
            ["Any Topic", *SUBJECT_TOPICS[study_subject]],
            key="teaching_assistant_topic",
        )
        if study_topic == "Any Topic":
            study_topic = None

    with st.expander(
        "Create Teaching Notes",
        expanded=bool(st.session_state.get("teacher_notes_focus")),
    ):
        with st.form("teacher_notes_form"):
            notes_focus = st.text_area(
                "What should the notes focus on?",
                placeholder="For example: key vocabulary and common misconceptions",
                key="teacher_notes_focus",
            )
            create_notes = st.form_submit_button(
                "Generate Teaching Notes",
                disabled=(
                    study_subject == "Any Subject"
                    or study_topic is None
                    or not bool(os.getenv("GEMINI_API_KEY"))
                ),
            )
        if create_notes:
            try:
                with st.spinner("Creating classroom-ready teaching notes..."):
                    notes_content = generate_teaching_notes(
                        study_subject,
                        study_topic,
                        notes_focus,
                    )
                notes_key = hashlib.sha256(
                    f"{study_subject}\0{study_topic}\0{notes_content}".encode("utf-8")
                ).hexdigest()[:12]
                st.session_state["generated_teacher_notes"] = {
                    "key": notes_key,
                    "title": f"{study_topic} — {study_subject} Teaching Notes",
                    "subject": study_subject,
                    "topic": study_topic,
                    "content": notes_content,
                    "saved": False,
                }
            except Exception as e:
                st.error(f"Gemini could not create teaching notes: {e}")

    if not os.getenv("GEMINI_API_KEY"):
        st.warning("Add GEMINI_API_KEY to .env to use the Teaching Assistant.")
    generated_notes = st.session_state.get("generated_teacher_notes")
    if generated_notes:
        st.markdown("#### Generated Teaching Notes")
        st.markdown(generated_notes["content"])
        resource_title = st.text_input(
            "Title for your Teaching Library",
            value=generated_notes["title"],
            key=f"teacher_notes_title_{generated_notes['key']}",
            disabled=generated_notes["saved"],
        )
        if generated_notes["saved"]:
            st.success("These notes are saved in your Teaching Library.")
        elif st.button(
            "Save Notes to Teaching Library",
            key=f"save_teacher_notes_{generated_notes['key']}",
        ):
            if (
                not resource_title.strip()
                or not generated_notes.get("subject")
                or not generated_notes.get("topic")
                or not generated_notes.get("content")
            ):
                st.warning(
                    "A title, subject, topic, and note content are required to save."
                )
            else:
                try:
                    db.teaching_resources.insert_one(
                        {
                            "title": resource_title.strip(),
                            "subject": generated_notes["subject"],
                            "topic": generated_notes["topic"],
                            "content": generated_notes["content"],
                            "created_at": datetime.now(timezone.utc),
                        }
                    )
                    generated_notes["saved"] = True
                    st.success("Teaching notes saved to your Teaching Library.")
                except Exception as e:
                    st.error(f"Could not save teaching notes: {e}")

    st.markdown("#### Ask the Teaching Assistant")
    study_conversation = st.session_state.setdefault(
        "teaching_assistant_conversation",
        [],
    )
    if st.button("Clear Conversation", key="clear_teaching_assistant_chat"):
        st.session_state["teaching_assistant_conversation"] = []
        st.rerun()
    for turn in study_conversation:
        with st.chat_message(turn["role"]):
            st.markdown(turn["content"])
    study_prompt = st.chat_input(
        "Ask about teaching, lessons, or learning resources",
        key="teaching_assistant_chat",
        disabled=not bool(os.getenv("GEMINI_API_KEY")),
    )
    if study_prompt and study_prompt.strip():
        study_prompt = study_prompt.strip()
        try:
            with st.spinner("Preparing a teaching-focused response..."):
                study_reply = chat_about_education(
                    study_conversation,
                    study_prompt,
                    None if study_subject == "Any Subject" else study_subject,
                    study_topic,
                )
        except Exception as e:
            st.error(f"The Teaching Assistant could not reply: {e}")
        else:
            study_conversation.extend(
                [
                    {"role": "user", "content": study_prompt},
                    {"role": "assistant", "content": study_reply},
                ]
            )
            st.rerun()

# ---------- Class agent ----------
with tab_agent:
    st.subheader("Class Response Agent")
    st.caption(
        "Find where your class is getting stuck and prepare focused revision "
        "resources from the answers you have already recorded."
    )
    with st.container(border=True):
        st.markdown("**How this helps you**")
        st.markdown(
            "Choose a class and subject to review its recorded answers. The assistant "
            "checks the marks, flags uncertain answers for your decision, and looks "
            "for misconceptions shared by students. It then drafts a short revision "
            "resource with practice questions for you to check. Nothing is added to "
            "the Teaching Library until you approve it."
        )
        st.caption(
            "Start by choosing a class, subject, and topic below. Only answers not "
            "previously reviewed by this assistant will be included."
        )

    saved_classes = sorted(db.responses.distinct("class_name"))
    saved_subjects = sorted(db.responses.distinct("subject"))
    if not saved_classes or not saved_subjects:
        st.info(
            "There are no saved responses to process yet. First record student "
            "answers in the **Record Response** tab."
        )
    else:
        filter_col1, filter_col2, filter_col3 = st.columns(3)
        with filter_col1:
            selected_agent_class = st.selectbox(
                "Class",
                ["All classes", *saved_classes],
                key="agent_saved_class",
            )
        class_query = (
            {}
            if selected_agent_class == "All classes"
            else {"class_name": selected_agent_class}
        )
        available_subjects = sorted(
            db.responses.distinct("subject", class_query)
        )
        with filter_col2:
            selected_agent_subject = st.selectbox(
                "Subject",
                ["All subjects", *available_subjects],
                key="agent_saved_subject",
            )
        scope_query = dict(class_query)
        if selected_agent_subject != "All subjects":
            scope_query["subject"] = selected_agent_subject
        available_topics = sorted(
            topic
            for topic in db.responses.distinct("topic", scope_query)
            if topic
        )
        with filter_col3:
            selected_agent_topic = st.selectbox(
                "Topic",
                ["All topics", *available_topics],
                key="agent_saved_topic",
            )
        if selected_agent_topic != "All topics":
            scope_query["topic"] = selected_agent_topic
        scope_query["$or"] = [
            {"analysis": None},
            {"analysis.source": {"$ne": "gemini_agent"}},
        ]
        available_response_count = db.responses.count_documents(scope_query)
        st.write(
            f"**{available_response_count} saved response(s)** in this scope have "
            "not been processed by the Class Agent."
        )
        selected_responses = list(
            db.responses.find(scope_query)
            .sort("created_at", 1)
            .limit(100)
        )
        if available_response_count > 100:
            st.info(
                "Showing the first 100 unprocessed responses. Run this batch, then "
                "run the agent again to process the remaining responses."
            )
        if selected_responses:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Class": item.get("class_name", ""),
                            "Student": item.get("student_name", ""),
                            "Subject": item.get("subject", ""),
                            "Topic": item.get("topic", ""),
                            "Question": item.get("question", ""),
                            "Student answer": item.get("student_answer", ""),
                            "Current mark": (
                                "Correct"
                                if item.get("is_correct")
                                else "Incorrect"
                            ),
                        }
                        for item in selected_responses
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        run_disabled = (
            not selected_responses
            or not bool(os.getenv("GEMINI_API_KEY"))
        )
        if not os.getenv("GEMINI_API_KEY"):
            st.warning(
                "Gemini is not configured because `GEMINI_API_KEY` is missing from "
                "`.env`. Add your key to enable the agent."
            )
        if st.button(
            f"Analyze {len(selected_responses)} saved response(s)",
            type="primary",
            disabled=run_disabled,
            key="run_class_agent",
        ):
            try:
                with st.spinner(
                    "Assessing saved answers, grouping misconceptions, and checking "
                    "revision questions..."
                ):
                    run_id = run_agent_saved_responses(db, selected_responses)
                st.session_state["agent_run_selected"] = run_id
                completed_run = db.agent_runs.find_one({"run_id": run_id})
                if completed_run.get("status") == "paused_error":
                    st.warning(
                        "Answer assessment finished, but misconception grouping "
                        "paused. Review the run error and retry."
                    )
                else:
                    st.success(
                        "Saved responses analyzed. Review uncertain marks and "
                        "revision packs below."
                    )
                st.rerun()
            except Exception as error:
                st.error(f"The Class Agent could not complete: {error}")

    recent_runs = list(
        db.agent_runs.find(
            {},
            {
                "_id": 0,
                "run_id": 1,
                "status": 1,
                "row_count": 1,
                "processed_count": 1,
                "failed_count": 1,
                "created_at": 1,
            },
        )
        .sort("created_at", -1)
        .limit(20)
    )
    if recent_runs:
        run_labels = {
            run["run_id"]: (
                f"{run.get('created_at', 'Unknown time')} · "
                f"{run.get('status', 'unknown')} · "
                f"{run.get('processed_count', 0)}/{run.get('row_count', 0)} rows"
            )
            for run in recent_runs
        }
        run_ids = list(run_labels)
        default_run = st.session_state.get("agent_run_selected")
        if default_run not in run_ids:
            default_run = run_ids[0]
        selected_run_id = st.selectbox(
            "Agent run history",
            run_ids,
            index=run_ids.index(default_run),
            format_func=lambda run_id: run_labels[run_id],
            key="agent_run_selected",
        )
        selected_run = db.agent_runs.find_one({"run_id": selected_run_id})
        if selected_run:
            st.markdown(f"#### Run status: `{selected_run.get('status', 'unknown')}`")
            st.write(
                f"Processed {selected_run.get('processed_count', 0)} of "
                f"{selected_run.get('row_count', 0)} rows; "
                f"{selected_run.get('failed_count', 0)} failed."
            )
            if selected_run.get("last_error"):
                st.error(selected_run["last_error"])

            failed_rows = selected_run.get("failed_rows", [])
            if failed_rows:
                st.markdown("#### Responses that need retry")
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Response #": item.get("row_number"),
                                "Retryable": item.get("retryable", False),
                                "Error": item.get("error", ""),
                            }
                            for item in failed_rows
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                )
            marked_responses = list(
                db.responses.find(
                    {"agent_run_id": selected_run_id}
                ).sort("agent_row_number", 1)
            )
            if marked_responses:
                st.markdown("#### Marking results")
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Response #": item.get("agent_row_number"),
                                "Student": item.get("student_name"),
                                "Question": item.get("question"),
                                "Student answer": item.get("student_answer"),
                                "Correct": item.get("is_correct"),
                                "Score": item.get("analysis", {}).get("score"),
                                "Confidence": item.get("analysis", {}).get(
                                    "confidence"
                                ),
                                "Misconception": item.get("analysis", {}).get(
                                    "misconception"
                                ),
                                "Review": item.get("teacher_review", {}).get(
                                    "status"
                                ),
                            }
                            for item in marked_responses
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                )
            retryable_rows = any(item.get("retryable") for item in failed_rows)
            retry_needed = (
                retryable_rows
                or selected_run.get("status") == "paused_error"
                or bool(selected_run.get("vector_errors"))
                or any(
                    pack.get("error") or not pack.get("verified")
                    for pack in selected_run.get("packs", [])
                )
            )
            if retry_needed and st.button(
                "Retry failed rows and rebuild revision packs",
                key=f"retry_agent_rows_{selected_run_id}",
            ):
                try:
                    if retryable_rows:
                        with st.spinner(
                            "Retrying failed rows and rebuilding groups..."
                        ):
                            retried, remaining = retry_agent_rows(
                                db,
                                selected_run_id,
                            )
                        st.info(
                            f"Retried {retried} rows; {remaining} remain unresolved."
                        )
                    else:
                        with st.spinner("Rebuilding groups and revision packs..."):
                            rebuild_agent_packs(db, selected_run_id)
                        st.success("Revision groups and packs have been rebuilt.")
                    st.rerun()
                except Exception as error:
                    st.error(f"Could not retry the agent workflow: {error}")

            pending_reviews = list(
                db.responses.find(
                    {
                        "agent_run_id": selected_run_id,
                        "teacher_review.status": "pending",
                    }
                ).sort("agent_row_number", 1)
            )
            if pending_reviews:
                st.markdown("#### Teacher review for uncertain marks")
                st.caption(
                    "Low-confidence and borderline scores stay on hold until you "
                    "confirm each mark."
                )
                with st.form(f"agent_review_form_{selected_run_id}"):
                    teacher_decisions = {}
                    for response in pending_reviews:
                        response_id = str(response["_id"])
                        analysis = response.get("analysis", {})
                        label = (
                            f"Response #{response.get('agent_row_number')}: "
                            f"{response.get('student_name')} — "
                            f"{response.get('question')}"
                        )
                        st.write(
                            f"{label} | score {analysis.get('score')} | "
                            f"{analysis.get('confidence')} confidence"
                        )
                        st.caption(
                            f"Student answer: {response.get('student_answer', '')}"
                        )
                        teacher_decisions[response_id] = st.selectbox(
                            "Teacher decision",
                            ["Needs review", "Mark correct", "Mark incorrect"],
                            key=f"teacher_decision_{selected_run_id}_{response_id}",
                        )
                    save_reviews = st.form_submit_button("Save teacher decisions")
                if save_reviews:
                    reviewed_count = 0
                    for response in pending_reviews:
                        response_id = str(response["_id"])
                        decision = teacher_decisions[response_id]
                        if decision == "Needs review":
                            continue
                        is_correct = decision == "Mark correct"
                        db.responses.update_one(
                            {"_id": response["_id"]},
                            {
                                "$set": {
                                    "is_correct": is_correct,
                                    "teacher_review.status": "reviewed",
                                    "teacher_review.decision": decision,
                                    "teacher_review.reviewed_at": datetime.now(
                                        timezone.utc
                                    ),
                                }
                            },
                        )
                        reviewed_count += 1
                    log_agent_action(
                        db,
                        selected_run_id,
                        "teacher_review_marks",
                        "succeeded",
                        {"reviewed": reviewed_count},
                    )
                    if reviewed_count:
                        rebuild_agent_packs(db, selected_run_id)
                        st.success(
                            f"Saved {reviewed_count} teacher decisions and rebuilt "
                            "the evidence groups."
                        )
                        st.rerun()
                    else:
                        st.info("No teacher decisions were changed.")

            packs = selected_run.get("packs", [])
            if packs:
                st.markdown("#### Draft revision packs")
                for pack in packs:
                    with st.container(border=True):
                        st.markdown(f"**{pack.get('canonical_label', pack['title'])}**")
                        st.caption(
                            f"{pack.get('subject', '')} / {pack.get('topic', '')} · "
                            f"{pack.get('evidence_count', 0)} answer(s)"
                        )
                        if pack.get("verification_attempts"):
                            st.caption(
                                "Practice-question check attempts: "
                                f"{pack['verification_attempts']}"
                            )
                        if pack.get("vector_similarity") is not None:
                            st.caption(
                                "Atlas Vector Search grouped this with a similar "
                                f"label (similarity {pack['vector_similarity']:.3f})."
                            )
                        if pack.get("error"):
                            st.error(pack["error"])
                        materials = pack.get("materials")
                        if materials:
                            st.write(materials.get("explanation", ""))
                            st.markdown("**Revision notes**")
                            for note in materials.get("revision_notes", []):
                                st.markdown(f"- {note}")
                            st.markdown("**Practice questions**")
                            for question_index, question_item in enumerate(
                                materials.get("practice_questions", [])
                            ):
                                check = (
                                    pack.get("verification", [])[question_index]
                                    if question_index < len(pack.get("verification", []))
                                    else {"pass": False, "issue": "Not verified"}
                                )
                                st.write(
                                    f"{'PASS' if check['pass'] else 'FAIL'} · "
                                    f"{question_item.get('question', '')}"
                                )
                                st.caption(
                                    f"Proposed answer: {question_item.get('answer', '')}"
                                )
                                if check.get("issue"):
                                    st.warning(check["issue"])
                            st.write(
                                f"Teacher tip: {materials.get('teacher_tip', '')}"
                            )
                        else:
                            st.error("No revision pack was generated for this group.")

            ungrouped_responses = selected_run.get("ungrouped_responses", [])
            if ungrouped_responses:
                st.markdown("#### Answers needing another look")
                st.info(
                    f"{len(ungrouped_responses)} incorrect answer(s) were not used "
                    "to create a revision pack because the assistant could not "
                    "confidently place them in a misconception group. These answers "
                    "are not included in the packs below."
                )
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Evidence #": item["index"] + 1,
                                "Subject": item.get("subject", ""),
                                "Topic": item.get("topic", ""),
                                "Question": item.get("question", ""),
                                "Student answer": item.get("student_answer", ""),
                                "Correct answer": item.get("correct_answer", ""),
                                "Why it needs a look": item.get("reason", ""),
                            }
                            for item in ungrouped_responses
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                )

            vector_errors = selected_run.get("vector_errors", [])
            if vector_errors:
                st.warning(
                    "Atlas could not compare one or more misconception labels by "
                    "meaning, so those labels were not combined. Check that the "
                    "Vector Search index is ready and Atlas is reachable, then retry "
                    "grouping before releasing the packs."
                )

            remaining_reviews = db.responses.count_documents(
                {
                    "agent_run_id": selected_run_id,
                    "teacher_review.status": "pending",
                }
            )
            has_failed_rows = bool(selected_run.get("failed_count", 0))
            all_packs_verified = bool(packs) and all(
                pack.get("verified") and pack.get("materials")
                for pack in packs
            )
            if selected_run.get("status") == "released":
                st.success(
                    f"Approved by {selected_run.get('approved_by', 'teacher')} and "
                    "released to the Teaching Library."
                )
            elif packs:
                teacher_name = st.text_input(
                    "Teacher approving these revision packs",
                    key=f"agent_approver_{selected_run_id}",
                )
                approval_ready = (
                    selected_run.get("status") == "awaiting_review"
                    and not remaining_reviews
                    and not has_failed_rows
                    and not vector_errors
                    and all_packs_verified
                    and bool(teacher_name.strip())
                )
                if not all_packs_verified:
                    st.warning(
                        "Release is blocked until every practice question passes "
                        "verification."
                    )
                if remaining_reviews or has_failed_rows:
                    st.warning(
                        "Resolve all uncertain marks and failed rows before approval."
                    )
                if vector_errors:
                    st.warning(
                        "Release is paused until Atlas has compared the misconception "
                        "labels successfully."
                    )
                if st.button(
                    "Approve and release revision packs",
                    type="primary",
                    disabled=not approval_ready,
                    key=f"approve_agent_run_{selected_run_id}",
                ):
                    try:
                        for pack in packs:
                            existing_resource = db.teaching_resources.find_one(
                                {
                                    "agent_run_id": selected_run_id,
                                    "agent_pattern_index": pack["pattern_index"],
                                }
                            )
                            if existing_resource:
                                continue
                            materials = pack["materials"]
                            content = (
                                f"### Misconception: {pack['misconception']}\n\n"
                                f"{materials['explanation']}\n\n"
                                "### Revision notes\n"
                                + "\n".join(
                                    f"- {note}"
                                    for note in materials["revision_notes"]
                                )
                                + "\n\n### Practice questions\n"
                                + "\n".join(
                                    f"{index}. {item['question']}\n"
                                    f"   Answer: {item['answer']}"
                                    for index, item in enumerate(
                                        materials["practice_questions"],
                                        start=1,
                                    )
                                )
                                + f"\n\n### Teacher tip\n{materials['teacher_tip']}"
                            )
                            db.teaching_resources.insert_one(
                                {
                                    "title": pack["title"],
                                    "subject": pack["subject"],
                                    "topic": pack["topic"],
                                    "content": content,
                                    "created_at": datetime.now(timezone.utc),
                                    "agent_run_id": selected_run_id,
                                    "agent_pattern_index": pack["pattern_index"],
                                }
                            )
                        log_agent_action(
                            db,
                            selected_run_id,
                            "teacher_approval_and_release",
                            "approved",
                            {"teacher": teacher_name.strip(), "packs": len(packs)},
                        )
                        db.agent_runs.update_one(
                            {"run_id": selected_run_id},
                            {
                                "$set": {
                                    "status": "released",
                                    "approved_by": teacher_name.strip(),
                                    "approved_at": datetime.now(timezone.utc),
                                    "updated_at": datetime.now(timezone.utc),
                                }
                            },
                        )
                        st.success("Revision packs released to the Teaching Library.")
                        st.rerun()
                    except Exception as error:
                        st.error(
                            "Could not release all revision packs. Existing saved "
                            f"packs are retained and the action can be retried: {error}"
                        )

            st.markdown("#### What the agent did")
            summary_columns = st.columns(3)
            summary_columns[0].metric(
                "Answers assessed",
                f"{selected_run.get('processed_count', 0)} / "
                f"{selected_run.get('row_count', 0)}",
            )
            summary_columns[1].metric(
                "Misconception groups",
                len(packs),
            )
            verified_pack_count = sum(
                bool(pack.get("verified")) for pack in packs
            )
            summary_columns[2].metric(
                "Revision packs checked",
                f"{verified_pack_count} / {len(packs)} passed",
            )
            ungrouped_responses = selected_run.get("ungrouped_responses", [])

            if failed_rows:
                st.write(
                    f"**Answer assessment:** {len(failed_rows)} response(s) could "
                    "not be assessed. Review the retry section above."
                )
            else:
                st.write(
                    f"**Answer assessment:** all "
                    f"{selected_run.get('processed_count', 0)} selected responses "
                    "were assessed."
                )

            if packs:
                st.write(
                    f"**Misconceptions:** incorrect answers were organized into "
                    f"{len(packs)} revision group(s). Similar labels may be combined "
                    "when Atlas finds a close meaning."
                )
                if all_packs_verified:
                    st.write(
                        "**Quality check:** every practice-question answer passed "
                        "Gemini's separate verification check."
                    )
                else:
                    st.write(
                        "**Quality check:** some revision packs still need "
                        "correction. They cannot be released until every question "
                        "passes verification."
                    )
            elif selected_run.get("status") == "completed":
                st.write(
                    "**Misconceptions:** no incorrect answers in this run were "
                    "grouped into a revision pack."
                )
            if ungrouped_responses:
                st.write(
                    f"**Answers needing another look:** "
                    f"{len(ungrouped_responses)} incorrect answer(s) were not "
                    "included in the revision packs and are listed above."
                )

            if remaining_reviews:
                st.write(
                    f"**Teacher review:** {remaining_reviews} uncertain mark(s) "
                    "are waiting for your decision."
                )
            elif selected_run.get("status") == "released":
                st.write(
                    f"**Teacher approval:** approved by "
                    f"{selected_run.get('approved_by', 'the teacher')} and saved to "
                    "the Teaching Library."
                )
            elif packs:
                st.write(
                    "**Teacher approval:** waiting for you to review and release "
                    "the verified packs."
                )
