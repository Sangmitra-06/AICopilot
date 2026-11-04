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
- Frontend: React (App.jsx); conversation flow is an implicit state machine in
  `flow = useRef(...)` with stages ask/confirm/offer/score/draft/free.
- 16 *_SYS prompts across 8 backend files; each composes the shared NEUTRALITY block
  from `prompts.py`.
- Onboarding: `onboarding.py` holds pure rules (next question, defaults, one follow-up
  per field, rule-based extraction, 14-turn cap, experience inference, criteria menu,
  form walkthrough). `store.fold_onboarding` replays `profile_field_set`,
  `evidence_set`, `onboarding_asked/answered/closed`, `walkthrough_shown` events, keyed
  `reviewer:<id>` in the same event table. Endpoints: `GET /onboarding/{rid}`,
  `POST /onboarding/{rid}/answer`, `GET /profile/{rid}`. Frontend not wired yet.
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
- Python: .\.venv\Scripts\python.exe -m pytest (258 tests + 2 `live` tests skipped unless RUN_LIVE=1; any other live model call must fail loudly)
- Frontend: node --test tests/loops/*.test.mjs (12 tests)
- Build: npm run build in frontend/
- Setup: python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r backend\requirements.txt
- Project lives at C:\dev\ReviewerAISlop (outside OneDrive; OneDrive breaks SQLite and node_modules)

## Status
- Prompt A (loop fixes) done. Flow counters (follow-up cap, I-don't-know) are
  frontend-only and not persisted; the backend onboarding step moves flow state to the backend.
- Drafting gate (synth.py:224, main.py:314) is intentionally still in place until
  the loosening step. Do not change it earlier.