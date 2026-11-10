# EduLayne v2: LMS + AI assistant

React (Vite) frontend · FastAPI backend · MongoDB · any OpenAI-compatible LLM (Groq or Ollama)

```
edulayne/
├── backend/
│   ├── app/
│   │   ├── chatbot/      router, entities, facts, prompts, engine  ← the assistant
│   │   ├── services/     directory (reads + stats), actions (all writes)
│   │   ├── core/         db, migration, audit ledger, security
│   │   └── api/          auth, portal pages, admin, chat endpoints
│   ├── rules/            student / instructor / admin rule files (loaded into prompts)
│   ├── scripts/migrate.py
│   ├── data/legacy/      your Compass exports (used by demo mode and tests)
│   ├── seed_users.json   the 3 demo logins
│   └── tests/            python -m pytest
└── frontend/             same screens as before + Explore pages + admin panel
```

## Quick start

**1. Backend**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # then edit .env (see below)
python -m scripts.migrate --dry-run                    # preview the data changes
python -m scripts.migrate                              # writes the new "edulayne" database
uvicorn app.main:app --reload --port 8000
```

No MongoDB or API key yet? Leave `MONGO_URI=memory` and skip the migrate step: the app builds the database in memory from `data/legacy/` (resets on restart).

**2. Frontend**

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173 (calls to /api go to port 8000)
```

**3. Sign in**

| User ID | Password | Role |
|---|---|---|
| STD001 | amma@123 | Student (Bonnie) |
| INS001 | teach@123 | Instructor (Dr. Meera Nair) |
| ADM001 | manage@123 | Admin (Arun Kumar) |

Change these in `seed_users.json` before running the migration if you need to.

## Configuration (`backend/.env`)

| Setting | Meaning |
|---|---|
| `MONGO_URI` | Atlas connection string, or `memory` for offline demo mode |
| `MONGO_DB` | Database the migration writes to (default `edulayne`). Your original `LMS` database is only read. |
| `JWT_SECRET` | Long random string for login tokens |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | Any OpenAI-compatible endpoint |
| `LLM_ROUTER_MODEL` | Small model used only for the few questions the rules can't classify |
| `LOW_ATTENDANCE`, `DEFAULT_PASS_MARK` | 75 and 40 by default |

**About Llama on Groq:** Groq shut down its self-serve Llama models (`llama-3.3-70b-versatile`, `llama-3.1-8b-instant`) on 16 Aug 2026 and recommends `openai/gpt-oss-120b` / `openai/gpt-oss-20b` instead, which are the defaults here. To keep using Llama, run it locally with Ollama (settings are in `.env.example`). The chatbot works with either, and still answers record questions with no model at all.

## How the chatbot decides what to answer

The old version passed every question straight to Llama and let it guess. Now the model only *words* the answer; code decides where the answer comes from and what data it may see.

```
message → entities → router → scope check → facts → LLM wording → number check → reply
```

1. **Entities** (`chatbot/entities.py`) find IDs (`STD002`), batches (`A1`), courses (incl. aliases like "Artificial Intelligence") and names. Names shared across roles (Arun, Meera, Priya, Kiran, Anjali…) are kept ambiguous and resolved by scope and topic, or the bot asks "which one?".
2. **Router** (`chatbot/router.py`) classifies the message:
   - `lms`: needs records ("what are my marks", "who has low attendance in my class", "which batch has the lowest pass rate")
   - `general`: tutoring ("what is CNN", "teach me recursion", "difference between CNN and RNN")
   - conversation (greetings, thanks, help, "who am I"), `action` (admin changes), follow-ups ("explain it simply", "what about attendance?") which inherit the previous turn.
   Only messages the rules can't settle go to the small LLM classifier.
3. **Scope check, in code**: a student's prompt only ever contains *their own* record; an instructor's only their batches; admins see everything. Asking for someone else's data is declined before any model runs, so nothing can leak.
4. **Facts** (`chatbot/facts.py`) compute every number in Python (attendance %, averages, pass rates, top/lowest), so the model never does arithmetic.
5. **LLM** writes the reply using the rule file for the user's role plus the facts. General questions get *no* records at all, so the bot doesn't drag marks into "what is a neural network?".
6. **Number check**: if the reply contains a number that isn't in the facts, it's discarded and a template answer is used. Template answers are also used when no model is configured.

## Admin powers

- **LMS Overview** page: add / edit / delete students, instructors and admins; enter marks and attendance; create logins and reset passwords; enable or disable logins; manage courses and batches; bulk CSV import; view and verify the audit ledger.
- **In chat**: "Add a student named Riya Das to batch A1", "Set marks of STD002 to 80", "Give Kavya a login", "Assign Dr. Kiran Varma to batch C3". Common phrasings are parsed by rules; anything else goes to the LLM. Either way, the bot shows a **confirmation card**, and nothing runs until the admin presses Confirm.
- New users get the next ID automatically (STD031, INS013…) and a temporary password shown once; they're asked to choose their own on first sign-in.
- Students and instructors who ask the bot to change records are pointed to the admin.

## Audit ledger (blockchain provision)

Every change (from the panel or the chat) is appended to `audit_ledger` as a block holding the previous block's SHA-256 hash. Editing or deleting any past entry breaks the chain, and **Verify** shows exactly which block. Passwords are never written to it.

**Create checkpoint** stores the current head hash in `ledger_checkpoints`. To anchor on a public chain later, fill in `anchor_to_chain()` in `app/core/ledger.py` (e.g. web3.py sending the hash to Polygon Amoy or Ethereum Sepolia) and return the transaction hash.

## Data model (after migration)

| Collection | Key fields |
|---|---|
| `users` | user_id, role, password_hash (PBKDF2), active, must_change_password |
| `students` | student_code, name, course_code, batch_code, learning_progress (number), email, phone |
| `instructors` | instructor_code, name, email, phone |
| `admins` | admin_code, name, email, phone |
| `courses` | course_code, name, aliases, pass_mark, max_marks |
| `batches` | batch_code, course_code, instructor_code, schedule, status, engagement_score |
| `marks` | student_code, course_code, marks, max_marks, assessments[] |
| `attendance` | student_code, course_code, classes_attended, total_classes |
| `counters`, `audit_ledger`, `ledger_checkpoints`, `pending_actions` | system |

`attendance_percentage`, `result` and all batch analytics are calculated instead of stored. The migration fixed 10 attendance percentages that didn't match their own class counts, and it unified the course names ("AI" / "Artificial Intelligence").

## Tests

```bash
cd backend && python -m pytest -q
```

25 tests cover the migration, logins, routing, student/instructor privacy, admin insights, the confirm-before-change flow, ledger tamper detection, and the LLM number check (no network needed).
