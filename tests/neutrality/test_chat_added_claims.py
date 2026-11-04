"""Fix 3: "Added to X" is written by the app, only after the note exists under that section, and a model-written
sentence claiming a capture is removed unless a note was written this turn."""
import json
import re

import pytest

from app import capture, store
from conftest import make_reviewer
from test_nudges import SECTIONS

SENTENCE = "The paper probes syntax in pretrained encoders using three datasets"
MESSAGE = f"My summary sentence: {SENTENCE}"
ADDED = re.compile(r"(?i)\badded to ([^.,\n]+)")
LABELS = {s["name"].lower(): s["id"] for s in SECTIONS}


def post(c, message):
    r = c.post("/chat/p1", json={"reviewer_id": "rev", "message": message})
    assert r.status_code == 200, r.text
    return r.json()


def live_notes():
    return [n for n in store.notes("p1") if not n["removed"]]


def assert_added_claims_are_true(reply):
    """For every 'Added to <section>' in a reply, a matching non-removed note exists in the store."""
    for m in ADDED.finditer(reply):
        where = m.group(1).strip().lower()
        fields = [n["field"] for n in live_notes()]
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


def pending(env, section="summary", later="Okay."):
    c, set_model = env
    set_model({"reply": "Got it. Want me to add that to your draft?", "views": [{"text": SENTENCE, "section": section}]},
              later)
    post(c, MESSAGE)
    assert live_notes() == []
    return c


@pytest.mark.parametrize("answer", ["Yes lets add it as my sentence", "no i mean add the paper summary"])
def test_a_confirmation_writes_the_note_and_the_apps_line_is_the_only_claim(env, answer):
    c = pending(env, later="Added to Paper summary, in your own words. All set.")   # the model's own claim
    body = post(c, answer)
    [n] = live_notes()
    assert (n["text"], n["field"]) == (SENTENCE, "summary")
    assert len(ADDED.findall(body["reply"])) == 1 and body["reply"].endswith("Added to Paper summary, in your own words.")
    assert body["added"] == {"note_id": n["id"], "section": "summary", "label": "Paper summary"}
    assert_added_claims_are_true(body["reply"])


def test_a_model_claim_naming_a_different_section_is_replaced_by_the_apps_true_line(env):
    c = pending(env, later="Added to Summary of strengths.")
    body = post(c, "yes")
    assert "strengths" not in body["reply"].lower() and "Added to Paper summary" in body["reply"]


def test_a_reply_to_a_confirmation_that_was_only_the_model_claim_is_just_the_apps_line(env):
    c = pending(env, later="Added to Paper summary.")
    assert post(c, "yes lets add it")["reply"] == "Added to Paper summary, in your own words."


def test_the_fallback_reply_after_a_confirmation_still_tells_the_truth(env, monkeypatch):
    c = pending(env)
    from app import chatflow
    monkeypatch.setattr(chatflow, "_chat", lambda msgs: (_ for _ in ()).throw(RuntimeError("down")))
    body = post(c, "yes lets add it")
    assert len(live_notes()) == 1 and "Added to Paper summary" in body["reply"]


def test_an_unplaced_view_is_confirmed_as_added_to_the_draft(env):
    c, set_model = env
    set_model({"reply": "Got it. Want me to add that to your draft?", "views": [{"text": SENTENCE, "section": ""}]}, "Ok.")
    post(c, MESSAGE)
    body = post(c, "yes")
    assert body["reply"].endswith("Added to your draft, in your own words.") and live_notes()[0]["field"] == ""


def test_a_no_never_produces_an_added_line(env):
    c = pending(env, later="Added to Paper summary anyway.")
    body = post(c, "no")
    assert "dded" not in body["reply"] and live_notes() == [] and body.get("added") is None


def test_every_added_claim_in_a_whole_session_matches_a_note(env):
    c, set_model = env
    script = [
        ({"reply": "Got it. Want me to add that to your draft?", "views": [{"text": SENTENCE, "section": "summary"}]}, MESSAGE),
        ("Added to Paper summary.", "Yes lets add it as my sentence"),
        ("Added to Paper summary again.", "what does Section 4 report?"),
        ({"reply": "Noted. Want me to add that to Weaknesses?", "views": [{"text": "The baselines look dated to me", "section": "weaknesses"}]},
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
            assert_added_claims_are_true(t["text"])
    assert sorted(n["field"] for n in live_notes()) == ["strengths", "summary"]
