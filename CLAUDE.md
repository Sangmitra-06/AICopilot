# Reviewer Co-pilot

## Product
A chat assistant that helps peer reviewers (initially for *CL conferences: ACL,
EMNLP, NAACL, etc.) work through a paper and write their review. It supports the
reviewer's thinking and writing. It never supplies its own judgment of the paper.

## Hard constraint: neutrality
The assistant must NEVER express or imply its own opinion about:
- the paper's quality, novelty, significance, soundness, or clarity
- whether results are convincing or experiments adequate
- the accept/reject/score decision
- whether the reviewer's assessment of the paper is right or wrong

When asked directly ("is this novel?", "do you agree?", "should I accept?"),
decline in one short sentence and redirect to the reviewer's own criteria and
evidence. No lecturing, no repeated boilerplate. Then be useful.

## What the assistant MAY do (be generous; stiffness is a known problem)
- Explain concepts, methods, datasets, metrics, and terminology neutrally
- Locate and quote what the paper actually says or claims
- Ask open questions that prompt the reviewer to examine something, framed by
  the reviewer's OWN stated criteria
- Reflect back what the reviewer has said and ask what to look at next
- Help the reviewer phrase, organize, and tighten their OWN comments without
  changing their stance
- Point out gaps in the REVIEW (see below)
- Surface checklist items from the venue's official reviewing guidelines

## Interaction principles
- The assistant drives the conversation; the reviewer can jump anywhere at any time.
- Onboarding is MANDATORY and runs first, but must never loop:
  - One question per turn during onboarding.
  - "Not sure" / "no preference" / "skip this one" are valid answers; store a default.
  - At most one clarifying follow-up per field, then move on.
  - Extract profile fields from free conversation, not only direct answers.
  - Hard cap on onboarding turns; close with whatever has been collected.
  - The profile can be updated later from the reviewer's behavior.
- After onboarding, conversation is free-flowing. Never end a turn with a pile of
  questions; a useful statement plus at most one prompt is the norm.
- Review-gap detection: the assistant points out omissions and inconsistencies in
  the REVIEW (e.g., a weakness that cites no section, a venue-required item not
  addressed, a claim the reviewer made earlier that is missing from the draft).
  It never says whether the reviewer's judgment of the PAPER is right.
- AI summaries are descriptive and claim-based only, with section pointers and no
  evaluative language (no "novel", "strong", "thorough", "limited"). Offered per
  the reviewer's stated preference, including whether before or after they read.
- Novice handling: infer level from concrete questions (papers reviewed, subarea
  familiarity); never ask "are you a novice." For low experience, present the
  venue's official criteria as a randomized menu with an "other, in my words"
  option, give a short walkthrough of the review form, and default to more concept
  explanation and section-by-section structure. Level changes defaults, never the
  neutrality rule. Generic process reminders are fine ("reviewers often check
  whether claims are supported by evidence"); comments on the reviewer's actual
  take are not.

## Review draft
A live draft organized by the venue's review form sections. Every substantive
statement from the reviewer is offered for capture into the right section, in
their words. The reviewer can edit or reject any capture. Draft text never
contains the assistant's own evaluation.

## Reviewer profile (from onboarding)
Fields: reading_order, workflow_mode (collaborative vs read-first),
summary_preference, note_habit, excellent_review_example, bad_review_traits,
strength_criteria, weakness_criteria, over_under_penalize, hardest_part,
experience_level.
The profile changes WHAT process questions the assistant asks and how much
scaffolding it gives. It never changes the neutrality rule. Reflect the reviewer's
own phrases back; do not map their answers onto a fixed rubric.

## Working agreements for Claude Code
- Read before editing; summarize the architecture before proposing changes.
- Small, reviewable changes; one concern per change.
- Do not weaken the neutrality constraint to make something feel better.
- Keep the system prompt in one place.
- Update tests in `tests/neutrality` whenever prompt logic changes.
- Ask me before restructuring the whole project.

## Current architecture (from audit; keep this updated)
- Backend: FastAPI, SQLite event log (store.py), state rebuilt by replaying events.
- Storage paths come from env vars, defaulting to the working directory:
  `COPILOT_DB` (event log, default `copilot.db`) and `COPILOT_DATA_DIR` (uploaded
  PDFs, default `data`). Point them at a temp dir in tests.
- Frontend, old guided flow: React (App.jsx); conversation flow is an implicit state machine in
  `flow = useRef(...)` with stages ask/confirm/offer/score/draft/free. Unchanged; lazy-loaded.
- Frontend, chat-first (`frontend/src/chat/`): `main.jsx` mounts `Root`, which shows the
  chat screen unless `?mode=guided` or `GET /config` reports `flow: "guided"` (then the old
  flow). All behaviour is React-free and tested: `controller.js` (stages boot -> onboarding ->
  attach -> chat; 409 shows the returned question; a failure is one plain sentence, sending
  again retries), `api.js`, `draftModel.js`, `flow.js`. Components: Root > ChatApp > ChatView >
  { Thread (Message, Chip), Composer, "Review draft" toggle, DraftPanel > DraftItem }.
  Onboarding uses `/onboarding/*` (no paper yet), then `/chat/{pid}` after upload; the reviewer
  id and paper id are kept in localStorage.
- 18 *_SYS prompts (16 across 8 backend files, plus `onboarding.TOPIC_SYS` and
  `prompts.CHAT_SYS`); each composes the shared NEUTRALITY block from `prompts.py`.
  `prompts.py` is also the one place for the PROFILE block and the chat prompt assembly.
- Chat-first backend: `POST /chat/{pid}` (body `{reviewer_id, message}`) -> `chatflow.turn`.
  Until onboarding closes the message goes to the onboarding rules (with a short
  acknowledgement before each next question); after that it is free conversation. The prompt
  = NEUTRALITY + PROFILE (the reviewer's own quoted phrases) + paper text + review draft +
  last 20 turns in full. `chat_checks.reply_errors` runs on every reply (verify.BANNED and
  llm.JUDGE, unchanged, plus opinion / stock-re-ask / pile-of-questions / decline /
  unrequested-summary checks; the reviewer's own words are licensed only when attributed to
  them); on failure: regenerate once, then a neutral fallback; outcomes are logged
  (`chat_check` events, `store.chat_check_stats`, logger `copilot.chat`).
  Capture (view -> offer -> `note_added`, editable/removable through `/events`), reword
  (stance words must survive), gap reports, non-blocking paper-conflict notes
  (`pointers.check` + fixed template) and drafting (never blocked; `synth.make_draft` and its
  gate are untouched) are server code over the event log. `coverage.py` = gap report;
  `nudges.py` = silent coverage map + at most one nudge per turn (gates: not during onboarding,
  not after a decline, not twice in a row, only at a natural pause; dismissed or twice-ignored
  nudges never repeat). `store.fold_chat` replays the chat events.
- Flow toggle: `COPILOT_FLOW=chat` (default) or `guided` (turns `/chat` off with a 409);
  `GET /config` reports it. The old guided flow's endpoints and source files are unchanged;
  the frontend keeps it behind `?mode=guided`.
- Onboarding: `onboarding.py` holds pure rules (next question, defaults, one follow-up
  per field, rule-based extraction, 14-turn cap, experience inference, criteria menu,
  form walkthrough). `store.fold_onboarding` replays `profile_field_set`,
  `evidence_set`, `onboarding_asked/answered/closed`, `walkthrough_shown` events, keyed
  `reviewer:<id>` in the same event table. Endpoints: `GET /onboarding/{rid}`,
  `POST /onboarding/{rid}/answer`, `GET /profile/{rid}`. Frontend not wired yet.
- Venue criteria text (onboarding menu and form walkthrough) comes only from
  `backend/definitions/venue_criteria.json` (loaded by `venue.py`): `source` {venue,
  cycle, status} plus `criteria` [{id, label, description, menu?}]. It is currently
  marked "placeholder, replace with official guidelines"; startup logs a warning
  until that changes. Swapping in official wording is a data change only.
- Existing neutrality layers (verify.py BANNED regex, judge-model audits in
  guide.py/criterion.py, grounded explanations, draft guard in synth.py) MUST be
  kept. Extend them; do not remove or weaken them.

## Rules for this refactor
- New profile and onboarding state go in the event log, not the frontend ref.
- Onboarding logic (next question, defaults, caps, extraction) lives in the
  backend and is unit-testable. The frontend only renders it.
- Shared prompt blocks (NEUTRALITY, PROFILE) live in one module; individual
  prompts compose them.
- Every loop fix needs a test that reproduces the loop first.
- Drafting is never blocked by missing parts; gaps are reported, not enforced.
- The paper-conflict check is a non-blocking, neutrally worded flag.

## Test commands
- Python: .\.venv\Scripts\python.exe -m pytest (988 tests + 8 `live` tests skipped unless RUN_LIVE=1; any other live model call must fail loudly)
  HTTP tests (tests/onboarding/test_http.py) use FastAPI TestClient; tests/conftest.py
  points COPILOT_DB at a temp file so the suite never opens the real copilot.db.
- Frontend: node --test tests/loops/*.test.mjs tests/chat/*.test.mjs (77 tests: 12 old-flow, 65
  chat-first, including a render test that loads the real components through Vite's SSR loader
  and lists every control on screen)
- Build: npm run build in frontend/
- Setup: python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r backend\requirements.txt
- Project lives at C:\dev\ReviewerAISlop (outside OneDrive; OneDrive breaks SQLite and node_modules)

## Status
- Prompt A (loop fixes) done. Flow counters (follow-up cap, I-don't-know) are
  frontend-only and not persisted; the backend onboarding step moves flow state to the backend.
- Drafting gate (synth.py:224, main.py:314) is intentionally still in place until
  the loosening step. Do not change it earlier.
- Chat-first frontend built and checked end to end in headless Chrome against the real
  backend and model. KNOWN ISSUE: the model (anthropic/claude-sonnet-5.5 via OpenRouter)
  often replies in plain prose, which carries no `views`, so a capture offer is not
  recorded even when the reply says "Added to ...". A flat `json_schema` response format
  gave 10/10 JSON in a trial (routed to a different provider; not adopted yet).


  ## Frontend principles (chat-first, guided)
- One column: a chat thread and one text box. That is the whole main screen.
- Onboarding happens as the first messages of the same thread, one question at a
  time. No separate form, no wizard.
- No per-message buttons. Allowed UI: Send, a paperclip for paper upload, a small
  "Review draft" toggle that opens a side panel (read, edit, copy all), and inline
  choice chips only when onboarding returns a criteria menu for a novice.
- Gaps, rewording, and drafting are requested by typing ("what's missing?",
  "reword this", "draft it"), not by buttons.
- The assistant leads: it may end a turn with one light nudge about the review.
  Nudges are plain chat text, never buttons or popups.
- The old guided part-by-part flow lives behind ?mode=guided and is not linked
  from the UI. Do not change it.

## Chat-first behavior
- Tone: a helpful colleague, not a form. Acknowledge what the reviewer said in a
  few words, vary phrasing, allow plain statements instead of always ending in a
  question.
- Nudges are about the REVIEW, never about the paper: at most one per turn, never
  repeated once dismissed, never during onboarding, never right after a judgment
  decline, never twice in a row.
- Neutrality checks must not over-block: the fallback should almost never fire on
  ordinary neutral messages.