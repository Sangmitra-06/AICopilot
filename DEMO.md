# Reviewer Co-pilot: tester notes

## What it is
A chat assistant that helps you work through a paper and write **your own** peer review (set up for *CL venues: ACL,
EMNLP, NAACL). It explains concepts, finds what the paper says, walks you through the sections in the order you like,
and keeps a review draft in your own words. It will **not** tell you whether the paper is good, novel or acceptable,
and will politely decline if you ask. That is deliberate.

## Getting in
Open the link you were sent. The browser asks for a user name and password: any user name works; the password is the
one shared with you alongside the link. You enter it once per browser session.

## What to try (15 to 20 minutes)
1. **Onboarding.** Answer a few short questions about how you review (reading order, whether you want a summary before
   reading, what you look for). "Not sure" or "skip" are fine answers.
2. **Attach a paper** with the paperclip. The PDF opens on the left (on a screen at least 900px wide).
3. **The opening.** The assistant starts by itself: a short descriptive summary (if you asked for one) and the first
   section in your reading order. Pointers like "(Section 3)" are clickable and highlight the passage.
4. **Walk.** Say "next", "go to results" or "stop guiding".
5. **Ask things.** "What is BLEU?", "What dataset do they use?", "Is this novel?" (try it: it should decline in one
   sentence and turn back to your criteria).
6. **State your views.** e.g. "The ablation in Table 3 is missing a baseline." It is saved in your words under a review
   section; say "move it" or "put it in strengths" to change that, "undo" to take it back.
7. **Review.** "What's missing?" lists open review-form sections; "draft it" assembles your notes. Open the **Review draft**
   toggle to read, edit or copy everything.
8. **Drag a box** on the PDF to quote that text into the message box.

Things worth reporting: anything that sounds like the assistant's own opinion of the paper, a loop or repeated question,
a note saved in the wrong place, or a highlight in the wrong spot. Please include roughly what you typed.

## What is stored
On the host's machine, in a local database: your onboarding answers, the conversation, your notes and draft, and the
PDF you upload. You are identified only by a random id kept in your browser (no name or email is collected). Another
tester who uploads the same PDF gets their own separate conversation and draft. To start over, clear this site's data
in your browser.

## Important: use a public paper
Paper text and your messages are sent to a language model through **OpenRouter**, which forwards them to third-party
model providers. **Use a paper that is already public (for example from arXiv or the ACL Anthology). Do not upload a
paper you are reviewing under confidentiality, or anything else private.**

## Limits
The demo answers a fixed number of chat messages per day across all testers. If you see "This demo has reached its
limit of chat messages for today", your work is saved: come back tomorrow.

---

## For the host: running it

```powershell
# once: build the frontend
cd C:\dev\ReviewerAISlop\frontend
npm run build

# start: one process serves the frontend and the API on one port
cd C:\dev\ReviewerAISlop\backend
$env:DEMO_PASSWORD = "choose-a-password"     # required for a public tunnel; never logged
$env:MAX_CHAT_CALLS_PER_DAY = "500"          # optional; default 500 per UTC day
$env:COPILOT_DB = "C:\dev\copilot-demo\copilot.db"   # optional: keep demo data apart
$env:COPILOT_DATA_DIR = "C:\dev\copilot-demo\data"
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# in a second terminal: the tunnel (for example Cloudflare's quick tunnel)
cloudflared tunnel --url http://127.0.0.1:8000
```

Share the `https://...trycloudflare.com` link it prints, plus the password (send them separately). The model key and
model name come from `backend/.env` (`OPENROUTER_API_KEY`, `MODEL`). Do not set `COPILOT_FRESH=1` for a demo: it wipes
the database at every restart. The old guided flow (`?mode=guided`) is not part of the demo and does not work through
the tunnel.
