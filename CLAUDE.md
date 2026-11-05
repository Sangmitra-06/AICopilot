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
The profile is the backbone of how the copilot leads, used actively and visibly in their
words: reading order decides where the conversation goes; summary_preference whether and
when a summary appears; workflow_mode the pace (together = lead step by step, read first =
wait until asked); strength/weakness criteria and note_habit give one light lens prompt
when a section is on screen; hardest_part where extra help goes; experience_level how much
to explain; bad_review_traits are reminders when they check their draft. Quote, never
rank or reinterpret, never use it for an opinion about the paper, at most one profile
reference per turn, never the same one twice in a row.

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
  { PdfViewer (after upload), Thread (Message, Chip, Cite), Composer, "Review draft" toggle,
  DraftPanel > DraftItem }. The PDF pane (`frontend/src/pdf/`: PdfViewer, PdfPage, pdf.css) shows
  the paper on the left once one is attached; the draft panel then opens over the chat column; below
  900px wide the pane is hidden. `citeModel.js` (React-free, tested) maps citations to highlights; the
  controller holds `spans` (id -> page and box, from `GET /papers/{pid}/spans` plus what replies
  carry) and one `focus` (the spans on show). The focus changes only when a reply cites a span that
  can be located, when a pointer in a reply is clicked, or when the reviewer drags a box on the page
  (`POST /select`, the text goes into the text box as a quotation); a reply that cites nothing, a gap
  report, a draft, a nudge or the fallback never moves the PDF. Spans that cannot be located fail quietly.
  **`PdfViewer`/`PdfPage` deliberately DUPLICATE the viewer logic in `Page`/`Viewer` of `App.jsx`
  (old guided flow, which must not be modified): keep the two copies in sync, or delete one when the
  old flow is removed.**
  Onboarding uses `/onboarding/*` (no paper yet), then `/chat/{pid}` after upload; the reviewer
  id and paper id are kept in localStorage. `POST /onboarding/{rid}/answer` returns an `ack`
  (a plain, varied "Got it." / "Thanks.") only after a real answer, never after a skip, an
  off-topic reply that earned a follow-up, a GET or a 409; the UI shows it before the next question.
- 19 *_SYS prompts (16 across 8 backend files, plus `onboarding.TOPIC_SYS`,
  `prompts.CHAT_SYS` and `prompts.VIEW_SYS`); each composes the shared NEUTRALITY block from `prompts.py`.
  `prompts.py` is also the one place for the PROFILE block and the chat prompt assembly.
- Profile as backbone (`profile.py`, pure; `prompts.profile_block`; `chatflow.profile_kw/last_ref`). The PROFILE block
  quotes every stated field in the reviewer's words (through `onboarding.tidy(..., edges_only=True)`: stray quotes,
  brackets and punctuation at the ends go, no word is changed) with one usage rule per stated field, PACE
  (workflow_mode), HOW MUCH TO EXPLAIN (experience_level, never shown as a label), a brevity line when hardest_part is
  about time, and the SUMMARY RULE (`prompts.SUMMARY_GIVEN` once the opening summary was given, from `walk_state
  ["summarized"]`). Rules: quote exactly, never rank/reinterpret, never an opinion about the paper, at most one profile
  reference per turn, never the same one twice in a row (meta `profile_ref` on the assistant turn). "together": each walk
  section after the opening's first one carries one app-written lens line (`profile.lens_line`: strength -> weakness ->
  note habit, rotating); model turns get one `PROFILE REFERENCE` note (none with a nudge or a decline; counted as used only
  if the reply quotes it). "read first" (`profile.reads_first`): the opening shows the summary if wanted, then
  `walk.wait_line` ("You said “…”, so I'll wait until you ask"), no walk_at, no nudges, no lens or reference until "next".
  The opening lead names the first two sections they named. "What's missing?" adds their bad-review words as a reminder
  (not twice in a row) and draft notes that repeat each other (`profile.duplicates`).
- Citations (`cites.py`): the chat prompt's POINTING AT THE PAPER block asks the model to put a
  span's `[id]` after a sentence only when the reply refers to that passage, never to support an
  evaluation. `chatflow` strips the markers (the reviewer sees a plain "(Section 4)", never an id),
  drops ids that are not spans of the paper (and spans the prompt never showed: references, stray
  text), and returns `cites` ([{id, page, bbox, section, lines}]) and `parts` (the text cut into
  plain pieces with the pointers marked) in the `/chat` response; both are stored in the
  `chat_turn` meta so a reload keeps the pointers. The neutrality checks run on the displayed text
  AND on the marker-free text (`chatflow.checked_errors`), so a marker can never hide a blocked
  phrase. Gap reports, drafts, nudges and the fallback cite nothing. `verify.py` and `llm.JUDGE` are
  untouched.
- Chat-first backend: `POST /chat/{pid}` (body `{reviewer_id, message}`) -> `chatflow.turn`.
  Until onboarding closes the message goes to the onboarding rules (with a short
  acknowledgement before each next question); after that it is free conversation. The prompt
  = NEUTRALITY + PROFILE (the reviewer's own quoted phrases) + paper text + review draft +
  last 20 turns in full. `chat_checks.reply_errors` runs on every reply (verify.BANNED and
  llm.JUDGE, unchanged, plus opinion / stock-re-ask / pile-of-questions / decline /
  unrequested-summary checks; the reviewer's own words are licensed only when attributed to
  them); on failure: regenerate once, then a neutral fallback; outcomes are logged
  (`chat_check` events, `store.chat_check_stats`, logger `copilot.chat`).
  Capture (view -> saved at once as `note_added`, editable/removable through `/events`), reword
  (stance words must survive), gap reports, non-blocking paper-conflict notes
  (`pointers.check` + fixed template) and drafting (never blocked; `synth.make_draft` and its
  gate are untouched) are server code over the event log. `coverage.py` = gap report;
  `nudges.py` = silent coverage map + at most one nudge per turn (gates: not during onboarding,
  not after a decline, not twice in a row, only at a natural pause; dismissed or twice-ignored
  nudges never repeat). `store.fold_chat` replays the chat events.
  Notes are SAVE-THEN-TELL (`chatflow.save_views` / `keep_captures_honest`, commands in `notecmd.py`, run by
  `chatflow.note_turn` before the walk, no model call): a stated view (model `views`, or the extraction call for a prose
  reply) is saved at once in the reviewer's exact words in its section, and the app's line is the ONLY word about it:
  "Saved under X. Say “move it” if that's wrong." (every model offer and capture claim is stripped; the line is written only
  after the note is in GET /notes; `added` {note_id, section, label}; meta `saved` on the turn). Commands: "move it" (asks
  which section; the next message naming one moves it), "put it in X" / "I want it to go in the strenghts" (typos ok),
  "also as a strength" (a copy in a second section), "add the summary" / "add all of it" (the app's own summary or section
  description, kept as meta `proposal` on its turn, saved with `origin: paper_claims` and `label` "Drafted from the paper's
  claims", shown above the paragraph in the panel and never copied; "all of it" after a pasted sentence replaces that
  sentence), "undo" (reverts the last `note_action`). Right after a save, a correction naming a section moves it and "don't
  add that" undoes it. A saved point does not move the walk on; "next" does. Legacy pending offers (`capture.answer`,
  `add_line`) still resolve as before. "What's missing?" and "draft
  it" (broad wording in `chatflow.GAP_REQ2/DRAFT_REQ2`, plus a model reply that only promises a list or draft) are answered
  by the app: the open-section list, and the draft text grouped by section, in the reply itself.
- Guided walk (`walk.py`, `chatflow.open_turn/walk_turn/move_on_after_capture`, `store.fold_walk`). The app speaks first:
  `POST /chat/{pid}/open` {reviewer_id} runs once onboarding is closed and a paper is attached (the frontend calls it after
  upload, when onboarding closes with a paper attached, and on reload). It returns `{opened, messages:[{kind: "summary" |
  "section", reply, parts, cites}], reason?}` and logs each message as an assistant `chat_turn` (meta `opening`, `cites`,
  `parts`) plus an `opening_made` event on the paper, so a reload gets `opened:false, reason:"already"` and nothing repeats.
  Message 1, only when `summary_preference` is `before_reading`: a descriptive, claim-based summary written by the model
  through `generate_checked` (the normal neutrality checks, plus `require_pointer`: it must carry section pointers; at most
  three sentences, one pointer run per sentence, `walk.one_pointer_each`), between the app's own friendly lead-in and close (`walk.SUMMARY_LEAD`/`SUMMARY_CLOSES`); if the
  checks never pass or the model is down it is silently left out (never the generic fallback). `after_reading`, `none`,
  `on_request` or unset: no summary. Message 2 (the walk's first section): the app's own line, "You said you like to start with
  the intro, here it is." (no pointer on it), then a SHORT DESCRIPTIVE PARAGRAPH about that section (`chatflow.section_description`:
  model-written through `generate_checked` with the same checks, at most three sentences, one pointer per sentence, a pointer
  that would read exactly like the previous sentence's is not shown twice but its span still counts, only passages of THAT
  section are kept), then a one-line hint on how to move, jump or stop. The paragraph's cited passages are the cites, so the PDF
  scrolls to and marks the section. If no paragraph can be made (checks never pass, model down) the app's line carries the
  pointer itself ("... here it is (Section 1).", first <=3 passages cited), never the generic fallback. The reading order is `walk.parse_reading_order` over the reviewer's own
  `reading_order` text (source `answer`, or the extracted sentence; a skip/default says nothing): loose word matching
  (intro, methods/approach/setup/model, results/experiments/evaluation, related work, conclusion, limitations, "section 3")
  against the paper's real TOP-LEVEL sections (`walk.real_sections`: no References/front matter/stray text; every span gets
  `top`, its top-level numbered section, in `main.spans_of` via `walk.add_tops` from the headings ingest found, so "3 Methods"
  counts even with no text of its own before 3.1; a unit's spans include its subsections; ingest.py itself is untouched). The
  method words (method/methodology/approach/setup/experimental setup) are one group, top-level titles win, and a method word
  never lands on a results/discussion/conclusion section (`walk.NOT_METHODS`); "section 3.2" goes to section 3. Sections the
  reviewer names come first with their word (`said`), the rest follow in paper order with `said: null` (the app never claims
  "as you said" for those); a word in a clause with skip/never/last is not an instruction; unparseable or linear answers
  ("straight through") are plain paper order. Walk events on the paper: `opening_made` {order}, `walk_at` {index, section,
  reason}, `walk_done`, `walk_stopped`; `store.walk_state` folds them (pointer, covered, stopped, done). During the walk
  the app answers these itself (its line is app-written; the descriptive paragraph under a section line is the only model
  call, and the end-of-order and stop lines have none): a done signal ("ok", "next", "got it", "move on", ...) -> for a section they
  named, "You said you like to read the intro first and then the methods, so let's go to the methods now." ("first" only
  after the first named one; for one they did not name, "Moving to the abstract.") (next section not yet shown, after the pointer; its spans cited); a jump ("go to results", "take me
  to section 3", only when the whole message is the move) -> "Going to the results, as you asked." ("Let's look at the
  intro again, as you asked." only for a section already shown) and the pointer resets
  there; the end of the order -> "That was the last section in your order." plus the open review-form sections (the gap
  report); "stop guiding" -> stopped for good (no resume; nudges stop too). A covered section is not shown again unless the
  reviewer jumps back to it. An accepted capture moves on after the app's "Added to ..." line unless that turn carries a
  nudge, a fresh offer, a gap list or a draft. Walk lines contain only the reviewer's own word, the paper's heading
  (repeated only if `walk.rates` finds no evaluative word in it, else "the next section") and a pointer.
- Notes and the draft panel: every "Added to X" line is written only after its `note_added` is in the store, so GET /notes always
  has it. `draftModel.buildSections` shows a section's generated sentences, then any note of that section whose key (`n<id>`)
  is not in the sentences' `src` (a note added after "draft it"), so the panel never hides one; a draft with no `src` record
  keeps hiding the notes (never twice).
- Dev clean state: `COPILOT_FRESH=1` (OFF by default; `fresh.py`, applied at the top of `store.py`) deletes the event database
  (and its journal files) and the data folder at startup and recreates the folder; it refuses to wipe the working directory,
  a root or the home folder. With it on, `GET /config` returns a random `boot_id` per process; off, `boot_id` is null and a
  restart changes nothing. The frontend (`chat/boot.js`, run by `Root` before the chat screen mounts) clears the stored
  reviewer id and paper id when a boot id differs from the stored one. `GET /papers/{pid}/pdf` is a 404 (not a 500) when the
  file is missing, and `PdfViewer` (`onMissing`, `pdf/missing.js`) then makes the controller forget the paper id
  (`controller.paperMissing`: back to "attach", "I can't find that paper any more").
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
Run everything from the repository root (C:\dev\ReviewerAISlop). Counts are what each command
reports today; update them when they change.

1. **Python** (all backend tests, including the old-flow Python loop tests):
   `.\.venv\Scripts\python.exe -m pytest`
   -> 2148 passed, 11 skipped (2159 collected). The 11 skipped are the 10 `live` tests (item 5) and the
   opt-in real-PDF walk test (set WALK_REAL_PDF to a local PDF, never committed); any
   other live model call must fail loudly. (If RUN_LIVE=1 is set in your shell the 10 run too.)
   Unset COPILOT_FRESH in the shell first: with it set, 3 /config and old-flow tests fail. HTTP tests (tests/onboarding/test_http.py) use FastAPI TestClient;
   tests/conftest.py points COPILOT_DB at a temp file so the suite never opens the real copilot.db.
2. **Old-flow loop tests** (node):
   `node --test tests/loops/*.test.mjs`
   -> 12 tests.
3. **Chat-first frontend tests** (node):
   `node --test tests/chat/*.test.mjs`
   -> 181 tests: controller, API client, draft model, flow switch, criteria chips, citations to
   highlights (`cites.test.mjs`), the opening turn (`opening.test.mjs`), message formatting
   (`format.test.mjs`), the browser scripts' skip logic, and a render test that loads the
   real components through Vite's SSR loader and lists every control on screen (PDF pane included).
   Both node suites together: `node --test tests/loops/*.test.mjs tests/chat/*.test.mjs` -> 193.
4. **Frontend build** (run in frontend/): `npm run build`. Optional lint of the chat code, also
   in frontend/: `npx oxlint src/chat src/main.jsx src/pdf` (should print nothing).
5. **Live-model tests** (not in the default run; real model calls with the real key):
   put the real OPENROUTER_API_KEY and MODEL from backend/.env into the environment first
   (tests/conftest.py otherwise gives them dummy values), then
   `$env:RUN_LIVE = "1"; .\.venv\Scripts\python.exe -m pytest -m live`
   -> 10 tests (8 chat-checks + 2 for the guided walk, `test_walk_live.py`).
6. **Browser end-to-end check** (not in the default run; needs Chrome and a built frontend):
   `node scripts/e2e/drive.mjs` (full journey; a few real model calls, needs the key in
   backend/.env), `node scripts/e2e/drive.mjs --offline` (no model, no key),
   `node scripts/e2e/drive-guided.mjs` (old flow shown by a guided-mode backend),
   `node scripts/e2e/drive-pdf.mjs` (the PDF pane: real backend, scripted model, no key; 31 checks).
   They print PASS/FAIL per check, exit 1 on a failure, and skip (exit 0) with a reason if
   Chrome, the key or the built frontend is missing. See "End-to-end browser check" in readme.md.

- Setup: python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r backend\requirements.txt
- Project lives at C:\dev\ReviewerAISlop (outside OneDrive; OneDrive breaks SQLite and node_modules)

## Status
- Prompt A (loop fixes) done. Flow counters (follow-up cap, I-don't-know) are
  frontend-only and not persisted; the backend onboarding step moves flow state to the backend.
- Drafting gate (synth.py:224, main.py:314) is intentionally still in place until
  the loosening step. Do not change it earlier.
- Chat-first frontend built and checked end to end in headless Chrome against the real
  backend and model. The model (anthropic/claude-sonnet-5.5 via OpenRouter) sometimes replies
  in plain prose, which carries no `views`. Captures stay honest regardless (`capture.py`):
  the assistant may only say something was added when the backend recorded it this turn, and
  when a prose reply follows a stated view a short extraction call (`prompts.VIEW_SYS`, plain
  `VIEW | section | their words` lines, words must be a verbatim span of the message) finds the
  view and the app SAVES it and says so in its own words ("Saved under Summary of weaknesses. Say
  “move it” if that's wrong."), the same save-then-tell flow as for JSON replies. A flat `json_schema` response format gave 10/10 JSON in a trial (different provider;
  deliberately not adopted).


  ## Frontend principles (chat-first, guided)
- Layout: before a paper is attached, a centered chat column. After upload, the
  PDF on the left and the chat on the right, with no added controls. The viewer
  follows the conversation: when a reply cites paper spans, it scrolls to them and
  highlights them automatically in one neutral colour. Highlights only locate text
  the reply cites or the reviewer selected; they never express an evaluation and
  are never added unprompted.
  - Onboarding happens as the first messages of the same thread, one question at a
  time. No separate form, no wizard.
- Assistant messages render `**bold**`, bullet/numbered lists and paragraph breaks (`frontend/src/chat/format.js`: text
  becomes plain data and React renders strings and `<strong>`, so a reply can never inject HTML; pointers stay clickable
  inside bold and list items). The reviewer's own messages are shown exactly as typed. A single plain paragraph keeps the
  plain `<p class="ca-msg ca-assistant">`.
- Onboarding answers are READ through `onboarding.tidy` (stray quotes/brackets, a leading "yes,"/"ok,"); what the reviewer
  wrote is what is stored. After a paper is attached the app does not post "Got the paper" when it can open (the opening is
  the reply); there is no "Switched to the new paper." message.
- No per-message buttons. Allowed UI: Send, a paperclip for paper upload, a small
  "Review draft" toggle that opens a side panel (read, edit, copy all), and inline
  choice chips only when onboarding returns a criteria menu for a novice.
- The PDF pane adds no buttons or toggles. Its only marks are page-number labels ("p4"),
  highlights (one neutral colour) and the rectangle shown while dragging a box. A pointer in a
  reply, "(Section 4)", is plain text, not a button; clicking it shows its highlight again.
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