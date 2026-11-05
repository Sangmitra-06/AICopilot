"""Proposed text goes to the wrong section or is not saved, and "not under X, under Y" does not move it (real session).

1. The assistant proposes a quoted version of the reviewer's strength (no section named in that reply).
2. "no it doesnt lets add that to strenghts"  -> nothing was saved; the assistant just repeated the text.
3. "add that version to the draft please"     -> saved under Paper summary (the proposal was made for strengths).
4. "not under suimmary under strenghts"       -> nothing moved; the assistant just repeated the text.

A proposal remembers the section it was proposed for; approving it saves exactly that text into the section named in
the message, else that section, else the one being worked on, never Paper summary by default. A move right after a save
moves the note and says "Moved to Y." Every reply here is the app's own line, written after GET /notes has the note.
"""
import pytest

from app import notecmd, synth
from conftest import make_reviewer

STATED = "I like that they classify heads with patching and ablate them"
TEXT = ("I think I like that the paper classifies heads with patching and then ablates the same heads, so each head is "
        "tested causally for both sufficiency and necessity.")
PROPOSAL = f"Here is a tighter version: “{TEXT}” Does it say what you meant?"
REPEAT = f"Sure, here it is again: “{TEXT}”"


@pytest.fixture
def c(chat_env):
    c, set_model = chat_env
    make_reviewer("rev")
    c.set_model = set_model
    return c


def say(c, message, *model):
    if model:
        c.set_model(*model)
    r = c.post("/chat/p1", json={"reviewer_id": "rev", "message": message})
    assert r.status_code == 200, r.text
    return r.json()


def notes(c):
    return c.get("/notes/p1").json()


def with_text(c, text=TEXT):
    return [n for n in notes(c) if n["text"] == text]


def only_in(c, field, text=TEXT):
    found = with_text(c, text)
    assert [n["field"] for n in found] == [field], found
    return found[0]


def last_line(body):
    return body["reply"].split("\n\n")[-1]


def propose(c):
    """A strength stated and saved under strengths, then the assistant's quoted version of it (no section named)."""
    say(c, STATED, {"reply": "Okay.", "views": [{"text": STATED, "section": "strengths"}]})
    assert [n["field"] for n in notes(c)] == ["strengths"]
    body = say(c, "can you tighten that into one sentence?", {"reply": PROPOSAL})
    assert with_text(c) == []
    return body


def test_the_session_sequence(c):
    names = synth.names()
    propose(c)

    body = say(c, "no it doesnt lets add that to strenghts", {"reply": REPEAT})
    n = only_in(c, "strengths")
    assert n.get("label") == notecmd.APPROVED_LABEL
    assert body["added"]["note_id"] == n["id"] and names["strengths"] in last_line(body)
    assert TEXT not in body["reply"]                                     # acted, did not repeat the text

    body = say(c, "add that version to the draft please", {"reply": REPEAT})
    only_in(c, "strengths")                                              # not Paper summary, and not twice
    assert names["strengths"] in body["reply"] and TEXT not in body["reply"]

    body = say(c, "not under suimmary under strenghts", {"reply": REPEAT})
    only_in(c, "strengths")
    assert names["strengths"] in body["reply"] and TEXT not in body["reply"]


def test_approval_without_a_section_uses_the_section_it_was_proposed_for(c):
    propose(c)
    body = say(c, "add that version to the draft please", {"reply": REPEAT})
    n = only_in(c, "strengths")
    assert body["added"]["note_id"] == n["id"] and TEXT not in body["reply"]


def test_the_section_is_remembered_when_the_model_repeats_the_text(c):
    propose(c)
    say(c, "hmm let me think about it", {"reply": REPEAT})
    say(c, "add that version to the draft please", {"reply": REPEAT})
    only_in(c, "strengths")


def test_not_under_summary_under_strengths_moves_it(c):
    names = synth.names()
    propose(c)
    say(c, "add that to the paper summary", {"reply": REPEAT})
    only_in(c, "summary")
    body = say(c, "not under suimmary under strenghts", {"reply": REPEAT})
    n = only_in(c, "strengths")
    assert body["reply"] == notecmd.moved_line(names["strengths"]) == f"Moved to {names['strengths']}."
    assert body["added"]["note_id"] == n["id"] and body["draft_changed"] is True


def test_add_that_to_comments(c):
    names = synth.names()
    propose(c)
    body = say(c, "add that to comments", {"reply": REPEAT})
    n = only_in(c, "comments")
    assert body["added"]["note_id"] == n["id"] and names["comments"] in last_line(body)


def test_lets_add_that_to_strengthss(c):
    propose(c)
    say(c, "lets add that to strengthss", {"reply": REPEAT})
    only_in(c, "strengths")


@pytest.mark.parametrize("move", ["move it to weaknesses", "put it in weaknesses", "no, weaknesses",
                                  "not under strengths, under weaknesses"])
def test_move_right_after_an_approved_save(c, move):
    names = synth.names()
    propose(c)
    say(c, "add that version to the draft please", {"reply": REPEAT})
    only_in(c, "strengths")
    body = say(c, move, {"reply": REPEAT})
    only_in(c, "weaknesses")
    assert body["reply"] == f"Moved to {names['weaknesses']}."


def test_move_it_to_weaknesses_after_a_stated_view(c):
    names = synth.names()
    say(c, STATED, {"reply": "Okay.", "views": [{"text": STATED, "section": "strengths"}]})
    body = say(c, "move it to weaknesses", {"reply": "Okay."})
    only_in(c, "weaknesses", STATED)
    assert body["reply"] == f"Moved to {names['weaknesses']}."


def test_no_section_known_asks_instead_of_defaulting_to_summary(c):
    say(c, "can you tighten this: they patch and ablate the heads", {"reply": PROPOSAL})
    body = say(c, "add that version to the draft please", {"reply": REPEAT})
    assert with_text(c) == [] and TEXT not in body["reply"]
    assert body["reply"].startswith("Which section should it go under?")
    say(c, "strenghts", {"reply": REPEAT})
    only_in(c, "strengths")
