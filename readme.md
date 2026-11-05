# Reviewer Co-pilot (prototype)

A chat assistant that helps peer reviewers (initially for *CL conferences) work through a paper and write their review. It supports your thinking and writing and never gives its own opinion of the paper (quality, novelty, soundness, accept/reject).

**How it works**
1. Short onboarding: how you read papers, what you look for in strengths and weaknesses, how you take notes. The assistant uses your own words to guide the conversation.
2. Attach a paper (PDF). The paper appears on the left, the chat on the right.
3. It can open with a short descriptive summary, then walk through the sections in the order you prefer ("next", or name any part).
4. State a point and it saves your words to the right review section. Open **Review draft** to see, edit or copy everything.
5. Ask "what's missing?" for a list of open sections, or "draft it" to assemble the draft from your notes.

## Requirements
- Python 3.11+
- Node 18+
- An [OpenRouter](https://openrouter.ai) API key with some credit

## Quick start

**Windows (PowerShell)**
```powershell
git clone <repo-url>
cd <repo>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
cd frontend
npm install
npm run build
cd ..
copy backend\.env.example backend\.env
```

**macOS / Linux**
```bash
git clone <repo-url>
cd <repo>
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
(cd frontend && npm install && npm run build)
cp backend/.env.example backend/.env
```

Open `backend/.env` and fill in:
```
OPENROUTER_API_KEY=your-key
MODEL=<an OpenRouter model id>
```

Run it:
```bash
cd backend
uvicorn app.main:app --port 8000
```
Open http://127.0.0.1:8000. Everything is served from that one address.

Your data (papers, notes, profile) is stored locally in `backend/copilot.db` and `backend/data/`. Both are git-ignored. To start fresh, stop the server and delete them.

## Things to know
- **Confidentiality:** paper text is sent to OpenRouter's model providers. Use public papers (for example from arXiv), not papers under review.
- **Cost:** each message uses your OpenRouter credit.
- The venue review criteria are **placeholders** (`backend/definitions/venue_criteria.json`), not the official guidelines.
- Optional settings (environment variables): `DEMO_PASSWORD` (require a password), `MAX_CHAT_CALLS_PER_DAY` (spend cap, default 500), `COPILOT_DB` and `COPILOT_DATA_DIR` (where data is stored).
- `COPILOT_FRESH=1` wipes the database and data folder every time the server starts. Dev only.

## Development
Frontend with hot reload (backend must be running on port 8000):
```bash
cd frontend && npm run dev
```
Tests (run in a normal PowerShell or terminal; the node run can hang in Git Bash):
```bash
python -m pytest
node --test tests/loops/*.test.mjs tests/chat/*.test.mjs
```
Most tests use a mocked model. Live-model tests run only with `RUN_LIVE=1` and `-m live`.

## Design rules (please keep)
- The assistant never expresses its own opinion about the paper. Checks live in `backend/app/verify.py`, `chat_checks.py`, and the shared NEUTRALITY block in `prompts.py`.
- The draft only contains the reviewer's own words, or text they explicitly approved.
- See `CLAUDE.md` for architecture notes and the full test counts.