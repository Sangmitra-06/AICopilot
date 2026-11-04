# Reviewer co-pilot

A prototype that helps a peer reviewer read a paper, think about it, and write the review in their own words.

The assistant explains the paper and checks facts. The reviewer does all the judging and all the writing. When the assistant helps assemble the review, it uses only what the reviewer actually said.

## The rules, and how each one is enforced

These are enforced by code where possible, not by asking the model nicely. "How strong" is an honest rating.

| Rule | How it is enforced | How strong |
|---|---|---|
| Every explanation sentence says where it comes from | The model returns structured sentences with a source type (paper, authors' claim, background, picture) and a quote. Code checks the quote is a verbatim substring of the cited passage after normalizing whitespace and punctuation. Line numbers come from the PDF margin, never from the model. Numbers in a sentence must appear in the cited text. | Strong for text. Weak for pictures, which are labeled as the model's reading. |
| No "this is a key point" language | A keyword list rejects evaluative words (key, important, strong, weak, novel, convincing, and similar) in explanations, questions, and drafts. | Crude. It misses paraphrases. |
| No judging questions answered | A keyword filter declines questions containing words like good, valid, convincing, or "should I". | Crude. It also blocks innocent questions such as "what does valid mean?". |
| Only facts are corrected | A note is compared against the paper. The model may return only "contradicts" or "answers", and every quote it gives is checked. Words like "enough" or "adequate" are rejected in its explanation. | Medium. The comparison is a model's judgment. |
| Questions are open and non-leading | Rule checks (one sentence, under 25 words, no yes/no form, no "or", no two questions in one) plus a second model call that judges whether the question leads. After three failed tries, a generic question is used. | Medium |
| The reviewer's words are kept verbatim | An append-only event log in SQLite. Edits add a new version and keep the old one. The reviewer's text is never rewritten by a model. | Strong |
| The draft contains nothing the reviewer did not say | Every note must be used, cited notes must contain any number or evaluative word the draft uses, a stemmed-word overlap check limits new wording, and a second model call audits each sentence. After three failed tries, the draft falls back to the notes exactly as written. | Medium |
| The review cannot be finished with gaps or false statements | Every required part must have a note, a score, or an explicit "no comment". No note may contradict the paper unless the reviewer disputes the check with a written reason. | Medium. It forces a decision, not quality. |

## How it works

```
PDF
 └─ ingest.py: PyMuPDF reads text lines, detects margin line numbers, finds headings
      (from PDF bookmarks, else font size), and cuts text into "spans" with ids,
      page, bounding box, and line range
          │
          ▼
Model calls (OpenRouter), each one a separate request with no memory except what is sent:
  explain / ask / brief  →  sentences + quotes  →  verify.py  →  code looks up exact lines
  fact check             →  pointers            →  quote checks
  questions              →  rule checks + judge model
  sort / draft           →  reviewer's notes only (the paper is not sent)
          │
          ▼
store.py: one SQLite table of events (note_added, note_text_edited, score_set,
          draft_generated, fact_check, ...). Current state is rebuilt by replaying it.
```

Things worth knowing:

- **The model never sees a line number it can write.** It sees them as context, but any digits it writes must appear in the cited text, so invented line numbers are rejected.
- **Page images are sent too.** Up to 8 pages go with each explain or ask request, so the model can answer from tables and figures the text reader missed. Anything read from a picture is labeled as such. If it reads text that the parser missed, code finds the exact words on the page and turns them into a new checked passage.
- **The explaining side and the writing side are separate.** Explaining the paper never sees the reviewer's opinions, and drafting never sees the paper. The only places both appear together are the fact check and the question maker.

## Repo layout

```
backend/
  app/
    main.py        API endpoints
    ingest.py      PDF parsing, spans, line numbers, headings
    llm.py         explain / ask / look, page images, quote verification
    verify.py      the checks on explanations
    schemas.py     structured output types
    store.py       SQLite event log and state replay
    criteria.py    loads criteria.json and definitions/*.txt
    criterion.py   per-part questions ("talk it through")
    synth.py       sorting notes and drafting the review, required-part check
    factcheck.py   fact check on notes, cached, with the finish check
    pointers.py    compares a note with the paper
    brief.py       the paper brief (the authors' own emphasis)
    guide.py       older question maker; its rule checks are still reused
  criteria.json    the venue's list of review-form parts
  definitions/     one plain-text file per part: the venue's definition
  data/            uploaded PDFs (not committed)
  copilot.db       the event log (not committed)
  .env             your API key (not committed)
frontend/
  src/App.jsx      the whole UI in one file
  src/App.css
```

## Setup

You need Python 3.10 or newer, Node 18 or newer, and an [OpenRouter](https://openrouter.ai) API key.

### Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS or Linux: source .venv/bin/activate
pip install fastapi "uvicorn[standard]" pymupdf openai pydantic python-multipart python-dotenv requests
```

Create `backend/.env`:

```
OPENROUTER_API_KEY=your-key-here
MODEL=provider/model-slug
USE_PDF=1
MAXP=8
```

Start it **from the `backend` folder**:

```powershell
uvicorn app.main:app --reload --port 8000
```

Open <http://127.0.0.1:8000/docs> to see the endpoints. Wait for `Application startup complete.`

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>, choose **Upload paper**, and pick a PDF. The page forgets which paper is open on refresh, so upload it again. The same file gets the same id, and your notes load back in.

The frontend talks to `http://127.0.0.1:8000`. That address is hard-coded at the top of `App.jsx`.

### Configuration

| Variable | Default | Meaning |
|---|---|---|
| `OPENROUTER_API_KEY` | required | Your key |
| `MODEL` | required | An OpenRouter model slug. It should support JSON output. |
| `USE_PDF` | `1` | Send page images with explain and ask requests. The model must accept images. Set `0` to turn this off. |
| `MAXP` | `8` | Maximum page images per request |
| `CRITERIA_FILE` | `criteria.json` | Path to a different criteria file |
| `COPILOT_DB` | `copilot.db` | Path to the SQLite event log. A relative path is relative to the directory the server is started from. |
| `COPILOT_DATA_DIR` | `data` | Folder where uploaded PDFs are stored (created on first upload). Same relative-path rule. |

## End-to-end browser check

The unit tests cover the logic, not how the screen behaves in a real browser. Scripts in `scripts/e2e/` start a real backend (over a throwaway database) and the built frontend, and drive headless Chrome through the whole journey. They are **not** part of the default test runs: `pytest` only collects `tests/`, and the `node --test` commands only look at `tests/loops` and `tests/chat`. The test commands for every suite are in the "Test commands" section of [CLAUDE.md](CLAUDE.md).

What you need:

- **Chrome** (or Chromium or Edge). It is found in the usual install locations; set `CHROME_PATH` to use another.
- **The built frontend:** `npm install` and `npm run build` in `frontend/`.
- **The backend set up as above**, with its Python venv (`backend/.venv` or `.venv`; set `PYTHON` to use another interpreter). The scripts also use it to build a one-page test PDF.
- **For the full run only, the API key in `backend/.env`** (`OPENROUTER_API_KEY` and `MODEL`). The scripts only check that these have values. They never print the key, and the backend reads the file itself.
- Ports **8000**, **5173** and **9333** free.

Run from the repository root:

```
node scripts/e2e/drive.mjs              # the full journey; makes a few real model calls
node scripts/e2e/drive.mjs --offline    # everything that needs no model (no key needed)
node scripts/e2e/drive-guided.mjs       # a backend in guided mode shows the old flow (no key needed)
node scripts/e2e/drive-pdf.mjs          # the PDF pane that follows the conversation (scripted model, no key needed)
```

Each check prints `PASS` or `FAIL`, and the script exits 1 if any check fails. If Chrome, the key (full run only), the built frontend or a free port is missing, the script prints `SKIPPED:` with what to fix and exits 0. Screenshots and the backend log go to `scripts/e2e/out/` (git-ignored; set `E2E_OUT` to change it).

The full run checks, among other things: the failure sentence and retry when the backend is down; the onboarding acknowledgements (after a real answer, none after a skip or an off-topic reply); the switch to chat once the paper is attached; that the assistant never claims a capture that did not happen; the draft panel (edit, Copy all); the novice walkthrough and criteria chips; and that `?mode=guided` shows the old flow.

`drive-pdf.mjs` runs the real backend with a scripted model (`scripted_backend.py`) and a four-page test paper on a 1366px-wide window. It checks that the PDF sits on the left after upload and the chat stays usable; that a cited passage is highlighted and scrolled to, with no marker or id in the reply; that replies citing nothing (and gap reports, and ids the paper does not have) leave the PDF where it is; that clicking a pointer brings its highlight back, also after a reload; that dragging a box puts the text in the text box as a quotation; and that the draft panel opens over the chat.

## Criteria and definitions

The review form is data, not code. `criteria.json` lists the parts, and a venue can swap it without touching the code. Each part has:

- `id`, `name`, `tab`: the tab label and the part's name
- `type`: `text`, or `score`
- `required`: whether it must be dealt with before the review can be finished
- `list`: whether it takes several numbered points (strengths, weaknesses, comments)
- `scale`: for scores, a list of `{value, label}` pairs
- the venue's definition, loaded from `definitions/<id>.txt`

Set `"gate": false` to turn off the required-parts check, and `"fact_gate": false` or `"allow_dispute": false` for the conflict check.

Where the definition is used:

- It is shown to the reviewer at the top of the tab, unchanged.
- It is used by the assistant to sort notes into parts.
- It is the source for the assistant's questions.
- Nothing else uses it. In particular, the assistant does not decide whether the paper meets a definition.

**The definition files shipped here are stand-in wording written by the author, not the venue's official text.** Each file says so on its first line. Replace them with the official text, copied exactly, before using this for real. The app shows whatever you paste. Score scales must also match the form exactly, including any half steps, because a value that is not in the file is rejected.

Definitions live in text files and not in `criteria.json` because pasted official text contains quotes and line breaks that break JSON.

## API overview

| Group | Endpoints |
|---|---|
| Paper | `POST /papers`, `GET /papers/{id}/pdf`, `GET /papers/{id}/spans`, `GET /walk/{id}` |
| Explain and ask | `POST /explain`, `POST /ask`, `POST /select`, `POST /explain_spans`, `POST /ask_selection`, `GET /thread/{id}` |
| Brief | `GET /brief/{id}`, `POST /brief` |
| Notes and scores | `POST /events` (any event), `GET /notes/{id}`, `GET /scores/{id}`, `POST /score`, `POST /skip` |
| Questions | `POST /talk` |
| Fact check | `POST /verify`, `GET /facts/{id}`, `POST /dispute` |
| Review | `POST /sort`, `POST /draft`, `GET /draft/{id}`, `POST /finish/{id}`, `GET /criteria`, `GET /criteria/status/{id}`, `GET /criteria/diagnose` |
| Audit | `GET /history/{id}` returns the full event log |
| Older, no longer used by the UI | `POST /guide`, `POST /teachback`, `POST /pointers`, `POST /checkpoint/{id}`, `GET /state/{id}` |

## Known flaws

Roughly in order of how much they matter.

### Conversation and interface

1. **The per-part conversation is not natural.** This is the main problem. A real transcript showed three failures:
   - A follow-up that does not fit the part. Asking "what led you to describe it that way?" about a plain summary is absurd, because describing a paper is not a judgment.
   - A typed "Nothing else" was saved as a point, and it would have appeared in the draft. The assistant only understands its buttons, not what the reviewer types.
   - The conversation does not end. Each saved answer restarts the follow-up count, so typing "I'm done" cannot end it. Only the button can.
   - Underneath all three is the same cause: the assistant runs a fixed routine (ask, save, follow up, ask "what else") and has no idea what it is trying to get from each part. Its question rules (reuse the reviewer's words, add no new ideas) are right for judgments like strengths and weaknesses, but too tight for plain information such as the summary, and they make the assistant echo the reviewer back.
2. **The interface is hard to learn.** There are about a dozen tabs plus a progress strip, a "Next" bar, and a separate Full review tab. It has been rebuilt several times and has had very little testing by anyone other than the author.
3. **Questions are slow.** Each one takes a model call plus up to two checking calls, so the reviewer waits a few seconds on every turn.
4. **No streaming.** Explanations take 10 to 30 seconds and drafting up to a minute, with a progress bar and no partial output.
5. **Opening a tab triggers a model call** the first time, and a reload loses the open question (the reviewer's answers survive).
6. **The mobile layout is minimal**, and accessibility has not been audited. There are focus outlines and some labels, and that is all.


### PDF parsing

17. **Tested on one paper**, an ARR-format submission with line numbers in both margins. Other layouts may fail.
18. **Line numbers are found by looking for a column of consecutive integers in the margin.** Camera-ready and arXiv PDFs have none, and fall back to page numbers. Scanned PDFs are not supported at all.
19. **Section headings come from PDF bookmarks, then font size.** Papers without bookmarks use a weaker heuristic.
20. **Tables come out as jumbled strings and are skipped in walkthroughs.** Figures are read only through captions and page images.
21. **Small glitches:** footnote numbers stick to words ("Prolific2"), and the rule for rejoining words split across lines is a guess based on the rest of the paper.
22. **Highlights cover whole text chunks**, not the exact lines. The line numbers shown are exact.

### Cost and performance

23. **Asking about the paper sends the whole paper's text plus page images on every request.** This has not been measured, but it is probably tens of thousands of tokens each time.
24. **Everything is recomputed on every request.** State is rebuilt by replaying the whole event log, and nothing is cached except the parsed paper and page images in memory.
25. **No cost tracking and no rate limiting.**
26. **Chat memory is the last six turns.** Follow-ups beyond that lose context.

