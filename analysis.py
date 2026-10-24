import json
import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# If you get a "model not found" error, check AI Studio for the current model
# name and set GEMINI_MODEL in .env (e.g. GEMINI_MODEL=some-model-name)
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

SYSTEM = """You are an expert teaching assistant. Given a question, the correct
answer, and a student's answer, diagnose the student's understanding.
Respond with ONLY a JSON object with these keys:
- "is_correct": true or false
- "score": integer 0-100 (partial credit allowed)
- "misconception": short label for the underlying misconception, or null if correct
- "misconception_detail": one sentence explaining the faulty thinking, or null if correct
- "knowledge_gap": the specific prerequisite concept the student seems to lack, or null
- "suggested_intervention": one concrete thing the teacher could do, or null if correct
Use consistent, reusable labels for misconceptions (e.g. "adds denominators
when adding fractions") so they can be grouped across students."""


def analyze_response(topic, question, correct_answer, student_answer):
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not found in .env")

    client = genai.Client(api_key=key)
    prompt = (
        f"Topic: {topic}\n"
        f"Question: {question}\n"
        f"Correct answer: {correct_answer}\n"
        f"Student answer: {student_answer}"
    )
    result = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM,
            response_mime_type="application/json",
        ),
    )
    text = result.text.strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(text)