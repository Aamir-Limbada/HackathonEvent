# AIM Assist

A teacher records student answers, reviews class performance, and uses AI to find
possible misconceptions and prepare revision material. Responses and agent runs are
stored in MongoDB Atlas.

## What the app does

The app has eight tabs:

| Tab | What it is for |
|---|---|
| **Record Response** | Save a student's answer to a question from the question bank. The teacher records whether it is correct. |
| **Question Bank** | Save questions and their correct answers for use when recording responses. |
| **Responses** | Filter and review saved answers by class, student, subject, topic, question, and result. |
| **Class Insights** | View accuracy and answer summaries for a class, student, or question. |
| **Misconception Insights** | Ask Gemini to analyze incorrect answers in a selected scope and identify evidence-backed patterns. |
| **Teaching Assistant** | Generate teaching notes or ask education-related questions. |
| **Teaching Library** | Browse teaching resources and revision packs saved by the teacher. |
| **Class Agent** | Reassess saved responses, flag uncertain marks, group misconceptions, check revision questions, and prepare packs for teacher approval. |

### A typical workflow

1. Add a question and its correct answer in **Question Bank**.
2. Record student answers in **Record Response**. The teacher marks whether each
   answer is correct; saving a response does not call Gemini.
3. Review the saved records in **Responses** or class performance in **Class
   Insights**.
4. In **Misconception Insights**, choose a class/student and subject scope, then
   click **Analyze misconceptions** to run Gemini analysis.
5. In **Class Agent**, choose a class, subject, and topic, then analyze saved
   responses that have not already been processed by that agent.
6. Review any uncertain marks and draft revision packs. Approved packs are saved
   to **Teaching Library**.

AI results are suggestions. Check them before using them with students.

## Current implementation

| Status | Capability |
|---|---|
| ✅ | Save and filter student responses in MongoDB Atlas |
| ✅ | Record a teacher's correctness mark when saving a response |
| ✅ | View class, student, topic, and question performance |
| ✅ | Run Gemini misconception analysis on demand |
| ✅ | Prepare teaching notes and use an education-focused assistant |
| ✅ | Use the Class Agent on responses already saved in the database; no CSV upload is required |
| ✅ | Flag low-confidence or borderline agent marks for teacher review |
| ✅ | Group agent misconceptions using Gemini and Atlas Vector Search |
| ✅ | Generate revision packs and ask Gemini to check their practice answers, with one regeneration attempt if a check fails |
| ✅ | Keep packs in draft until teacher approval; record agent actions in MongoDB |
| ✅ | Show incorrect answers that could not confidently be grouped |
| ✅ | Atlas Search for full-text searching across responses |
| ✅ | Teacher accounts and access control |
| ✅ | Automated evaluation against a labelled set of student answers |
| ✅ | Gemini Interactions API integration |

Gemini is configured through `GEMINI_MODEL` in `.env` (currently set to
`gemini-4-argon` in the local setup). Model access depends on the API account.
The app uses the Google Gen AI SDK's content-generation API; Gemini 4 Argon
availability and challenge eligibility have not been verified from this repository.

## How the Class Agent works

The Class Agent reads up to 100 unprocessed responses matching the selected class,
subject, and topic. It sends each answer to Gemini for a score, correctness decision,
confidence, and possible misconception. It updates those existing response documents
in MongoDB; it does not create new response records.

Low-confidence answers, scores near 50, or disagreements between the score and
correctness decision are marked for teacher review. The agent groups incorrect
answers, keeping each subject and topic in its own group. Answers it cannot confidently
group are listed separately rather than silently included in a pack.

For each group, Gemini drafts an explanation, revision notes, practice questions,
and a teacher tip. A separate Gemini call checks the practice answers. If any answer
fails, the agent requests one revision and checks again. Packs that do not pass are
not eligible for release. The teacher must resolve pending marks and approve the
packs before they are saved to Teaching Library.

Each run, including its actions and any failures, is recorded in the `agent_runs`
collection. The response assessment is stored on the corresponding document in
`responses`.

## MongoDB Atlas

The application uses the `teaching_assistant` database and these collections:

| Collection | Contents |
|---|---|
| `classes` | Class names |
| `students` | Student names and their class |
| `questions` | Saved questions and correct answers |
| `responses` | Student responses, teacher marks, and AI analysis |
| `teaching_resources` | Teaching notes and approved revision packs |
| `agent_runs` | Class Agent run status, review state, packs, and action history |
| `misconception_vector_labels` | Labels and embeddings used for semantic grouping |

The app creates the regular `misconception_vector_labels` collection when it starts.
To use semantic grouping, create its Vector Search index manually in Atlas. Search
indexes cannot be created by the app or with `mongosh`.

Use database `teaching_assistant`, collection `misconception_vector_labels`, and
index name `misconception_vector_index`. In Atlas, choose **JSON Editor** and use:

```json
{
  "fields": [
    {
      "type": "vector",
      "path": "embedding",
      "numDimensions": 3072,
      "similarity": "cosine"
    }
  ]
}
```

The vector collection must be a regular collection, not a time-series collection.
The app uses cosine similarity and groups labels only when the returned score meets
its configured threshold. If vector search fails, the run records the failure and
uses the unmerged Gemini labels; teacher release remains blocked until grouping
succeeds.

The app also creates regular indexes for common lookups and checks its MongoDB
connection at startup. If it cannot connect, it displays an error and stops.

## Gemini and data use

The Gemini API key is read from `GEMINI_API_KEY`. The model is read from
`GEMINI_MODEL`; the embedding model can be set with `GEMINI_EMBEDDING_MODEL`.
The defaults in `analysis.py` are `gemini-4-argon` and `gemini-embedding-001`.

Gemini is called when a teacher runs misconception analysis, generates teaching
notes, uses the teaching chat, or starts the Class Agent. Class Agent processing
sends the question, correct answer, and student answer to Gemini. Do not use real
student information in a demo. The app has no login or per-teacher data separation,
so any user with access to the app can see the shared database.

API model access, quotas, and billing depend on the Google account and are not
controlled by this application.

## Setup

### Requirements

- Python 3.11 or newer
- A MongoDB Atlas cluster and database user
- A Gemini API key with access to the configured model

Install the packages used by the app:

```powershell
python -m pip install streamlit pandas pymongo python-dotenv google-genai
```

Create a `.env` file in the same folder as `app.py`:

```text
MONGODB_URI=mongodb+srv://<db_user>:<db_password>@<cluster>.mongodb.net/
GEMINI_API_KEY=<your-api-key>
GEMINI_MODEL=gemini-4-argon
```

The current app can record and display responses with MongoDB configured. Gemini
features also require a valid key and access to the selected model. The Class Agent's
semantic grouping requires the Atlas Vector Search index described above.

Start the app from the project folder:

```powershell
python -m streamlit run app.py
```

Open the local URL printed by Streamlit, usually `http://localhost:8501`.
Restart the app after changing `.env`.

## Project files

```text
app.py             Streamlit interface and MongoDB access
analysis.py        Gemini assessment, misconception analysis, notes, and chat
agent_workflow.py  Class Agent processing, Vector Search, verification, and review
README.md          Project and setup guide
```

## Known limitations

- The app has no authentication or per-teacher access controls.
- Gemini can make mistakes, particularly when student answers are open-ended.
- Gemini API access, model availability, usage limits, and billing depend on the
  configured Google account.
- Vector Search requires an Atlas index created manually in the Atlas UI.
- Agent batches are limited to 100 saved responses at a time.
- The verification step is another AI assessment, not a guarantee that the material
  is correct. Teachers should review the pack before releasing it.
- The current app uses the Google Gen AI content-generation API, not the Gemini
  Interactions API.
