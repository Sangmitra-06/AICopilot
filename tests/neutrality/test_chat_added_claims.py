"""Fix 3: every line saying where a note went ("Added to X", "Saved under X", "Also saved under X", "Moved to X") is
written by the app, only after the note exists under that section, and a model-written sentence claiming a capture is
always removed. (Save-then-tell: a statement is saved at once; these tests drove offer-then-yes before.)"""
import json
import re

import pytest

from app import capture, store
from conftest import make_reviewer
from test_nudges import SECTIONS

SENTENCE = "The paper probes syntax in pretrained encoders using three datasets"
MESSAGE = f"My summary sentence: {SENTENCE}"
ADDED = re.compile(r"(?i)\b(?:added to|saved under|moved to)\s+([^.,\n]+)")
LABELS = {s["name"].lower(): s["id"] for s in SECTIONS}


def post(c, message):
    r = c.post("/chat/p1", json={"reviewer_id": "rev", "message": message})
    assert r.status_code == 200, r.text
    return r.json()


def live_notes():
    return [n for n in store.notes("p1") if not n["removed"]]


def ever_held():
    """Every section that held a note at some point (a note may be moved or undone later)."""
    out = set()
    for e in store.events("p1"):
        if e["type"] in ("note_added", "note_field_set"):
            out.add(e["payload"].get("field") or "")
    return list(out)


def assert_added_claims_are_true(reply, fields_now=None):
    """For every 'Added to / Saved under / Moved to <section>' in a reply, a matching non-removed note exists in the
    store (for a reply from earlier in the thread: a note was in that section at some point)."""
    for m in ADDED.finditer(reply):
        fields = fields_now if fields_now is not None else [n["field"] for n in live_notes()]
        for where in m.group(1).strip().lower().split(" and "):        # "Saved under Soundness and Summary of strengths"
            if where in LABELS:
                assert LABELS[where] in fields, (reply, fields)
            else:
                assert where.startswith("your draft") and fields, (reply, fields)


# ------------------------------------------------------------------ the guard itself: "Paper summary" is a section

SUMMARY_CLAIMS = [
    "Added to Paper summary.",
    "Added to Paper summary as written.",
    "Added to the Paper summary section.",
    "Added to Paper summary, in your own words.",
    "Saved to Paper summary.",
    "Added it to Paper summary.",
]


@pytest.mark.parametrize("sentence", SUMMARY_CLAIMS)
def test_a_claim_naming_the_paper_summary_section_is_a_claim(sentence):
    text, removed = capture.scrub(f"You describe the encoders. {sentence} Section 3 has the method.", SECTIONS)
    assert removed == [sentence] and text == "You describe the encoders. Section 3 has the method."


# ------------------------------------------------------------------ through the endpoint

@pytest.fixture
def env(chat_env):
    c, set_model = chat_env
    make_reviewer("rev")
    return c, set_model


@pytest.mark.parametrize("raw", [
    "That reads as a description. Added to Paper summary as written.",
    {"reply": "That reads as a description. Added to Paper summary, in your own words."},
    'Sure! Here is my answer: {"reply": "Added to Paper summary.", "views": []}',
    '```json\n{"reply": "Added to Paper summary as written.", "intent": "chat"}\n```',
])
def test_no_note_written_means_no_added_claim_whatever_the_form(env, raw):
    c, set_model = env
    set_model(raw, "NONE")
    body = post(c, MESSAGE)
    assert "added" not in body["reply"].lower() and live_notes() == []


SAVED = "Saved under Paper summary. Say “move it” if that's wrong."


def saved(env, section="summary", later="Okay.", first="Got it. Want me to add that to your draft?"):
    c, set_model = env
    set_model({"reply": first, "views": [{"text": SENTENCE, "section": section}]}, later)
    body = post(c, MESSAGE)
    assert [(n["text"], n["field"]) for n in live_notes()] == [(SENTENCE, section)]
    return c, body


@pytest.mark.parametrize("first", ["Added to Paper summary, in your own words. All set.", "Got it."])
def test_a_statement_writes_the_note_and_the_apps_line_is_the_only_claim(env, first):
    c, body = saved(env, first=first)                                             # the model's own claim, or none
    [n] = live_notes()
    assert len(ADDED.findall(body["reply"])) == 1 and body["reply"].endswith(SAVED)
    assert body["added"] == {"note_id": n["id"], "section": "summary", "label": "Paper summary"}
    assert_added_claims_are_true(body["reply"])


def test_a_model_claim_naming_a_different_section_is_replaced_by_the_apps_true_line(env):
    c, body = saved(env, first="Added to Summary of strengths.")
    assert "strengths" not in body["reply"].lower() and body["reply"] == SAVED


def test_a_later_reply_that_is_only_a_model_claim_says_nothing_untrue(env):
    c, _ = saved(env, later="Added to Paper summary.")
    reply = post(c, "yes lets add it")["reply"]
    assert "Added to" not in reply and len(live_notes()) == 1                      # saved once; no second claim


def test_the_fallback_reply_never_claims_a_save(env, monkeypatch):
    c, _ = saved(env)
    from app import chatflow
    monkeypatch.setattr(chatflow, "_chat", lambda msgs: (_ for _ in ()).throw(RuntimeError("down")))
    body = post(c, "The baselines look dated to me")
    assert len(live_notes()) == 1 and not ADDED.search(body["reply"]) and body["checks"]["fallback"] is True


def test_an_unplaced_view_is_told_as_saved_in_the_draft(env):
    c, set_model = env
    set_model({"reply": "Got it.", "views": [{"text": SENTENCE, "section": ""}]})
    body = post(c, MESSAGE)
    assert body["reply"].endswith("Saved under your draft. Say “move it” if that's wrong.")
    assert live_notes()[0]["field"] == ""


def test_dont_add_that_never_produces_an_added_line(env):
    c, _ = saved(env, later="Added to Paper summary anyway.")
    body = post(c, "don't add that")
    assert "dded" not in body["reply"] and live_notes() == [] and body.get("added") is None


def test_every_added_claim_in_a_whole_session_matches_a_note(env):
    c, set_model = env
    script = [
        ({"reply": "Got it. Want me to add that to your draft?", "views": [{"text": SENTENCE, "section": "summary"}]}, MESSAGE),
        ("Added to Paper summary.", "Yes lets add it as my sentence"),
        ("Added to Paper summary again.", "what does Section 4 report?"),
        ({"reply": "Noted. Added to Weaknesses.", "views": [{"text": "The baselines look dated to me", "section": "weaknesses"}]},
         "The baselines look dated to me"),
        ("Added to Weaknesses.", "no i mean add the strengths"),
        ("Added to Summary of weaknesses.", "thanks"),
    ]
    set_model(*[r for r, _ in script])
    for _, message in script:
        body = post(c, message)
        assert_added_claims_are_true(body["reply"])
    for t in store.thread("p1"):
        if t.get("role") == "assistant":
            assert_added_claims_are_true(t["text"], ever_held())
    assert sorted(n["field"] for n in live_notes()) == ["strengths", "summary"]


# ------------------------------------------------------------------ the real session, replayed against a scripted model

def test_replay_of_the_real_session_the_notes_the_panel_and_the_reply_always_agree(env, monkeypatch):
    from test_chat_capabilities import fake_drafter
    c, set_model = env
    fake_drafter(monkeypatch)
    low = "Five participants per region seems low"
    script = [
        (MESSAGE, {"reply": "Got it. Want me to add your sentence to Paper summary as written?",
                   "views": [{"text": SENTENCE, "section": "summary"}]}),
        ("Yes lets add it as my sentence", "Added to Paper summary, in your own words."),     # prose, claims it itself
        (low, {"reply": "Noted. Want me to add that to Summary of weaknesses?", "views": [{"text": low, "section": "weaknesses"}]}),
        ("no i mean add the strengths", {"reply": "Added to Paper summary.", "offer_response": "accept"}),
        ("what else do I have to add?", "Here's the list of sections still open in your draft."),
        ("draft it", "Here's your draft, assembled from the notes you've added so far."),
    ]
    set_model(*[r for _, r in script])
    replies = []
    for message, _ in script:
        body = post(c, message)
        replies.append(body["reply"])
        assert_added_claims_are_true(body["reply"])
        panel_notes = [n for n in c.get("/notes/p1").json() if not n["removed"]]      # what the draft panel lists
        said = [m.group(0) for m in ADDED.finditer(body["reply"])]
        if body.get("added"):
            assert any(n["id"] == body["added"]["note_id"] and n["field"] == body["added"]["section"] for n in panel_notes)
        elif not body["draft_changed"]:
            assert not said or "already saved under" in body["reply"], said         # only a true "it's already there"
    assert [(n["text"], n["field"]) for n in c.get("/notes/p1").json() if not n["removed"]] == [
        (SENTENCE, "summary"), (low, "strengths")]
    assert [len(ADDED.findall(r)) for r in replies[:4]] == [1, 1, 1, 1]          # saved, already there, saved, moved
    assert replies[1] == "That's already saved under Paper summary."
    assert replies[3] == "Moved to Summary of strengths."
    assert all(r.count("Want me to add") == 0 for r in replies)
    gap, draft = replies[4], replies[5]
    required = next(l for l in gap.splitlines() if l.startswith("- Required"))
    assert "Paper summary" not in required and "Summary of strengths" not in required and "Soundness" in required
    assert SENTENCE in draft and low in draft
    assert [s["text"] for s in c.get("/draft/p1").json()["summary"]["sentences"]] == [SENTENCE]


