"""Two draft-saving bugs (real session).

BUG 1: the assistant proposed a quoted text (a strengths line, a summary) and the reviewer said "this is good add it to the
draft" / "you can add the draft as is" / "add it": nothing was saved; once the model even replied "I can't place my
wording into it."
BUG 2: after the first saved note, later adds were silently not saved.

Every step below must add exactly one new note, visible in GET /notes (what the Review draft panel loads), and end with
the app's own line saying where it was saved, written only after the note exists.
"""
import pytest

from app import capture, notecmd, synth
from conftest import make_reviewer

STRENGTHS_PROPOSAL = ("For your strengths you could write: “The paper describes a new probing dataset and a layer-wise "
                      "analysis [s2].” Tell me if you want it.")
STRENGTHS_TEXT = "The paper describes a new probing dataset and a layer-wise analysis."
SUMMARY_PROPOSAL = ("Here is a summary you could use: “The authors study probing of syntax in pretrained encoders "
                    "(Abstract). They report accuracy on SST-2 and CoLA (Section 4).”")
SUMMARY_TEXT = ("The authors study probing of syntax in pretrained encoders. They report accuracy on SST-2 and CoLA.")
WEAKNESS = "they report accuracy on SST-2 only"


@pytest.fixture
def c(chat_env):
    c, set_model = chat_env
    make_reviewer("rev")
    c.set_model = set_model
    return c


def say(c, message):
    r = c.post("/chat/p1", json={"reviewer_id": "rev", "message": message})
    assert r.status_code == 200, r.text
    return r.json()


def notes(c):
    return c.get("/notes/p1").json()


def step(c, message, *model, expect=None):
    """One reviewer message; returns (reply body, the notes it added)."""
    if model:
        c.set_model(*model)
    before = {n["id"] for n in notes(c)}
    body = say(c, message)
    new = [n for n in notes(c) if n["id"] not in before]
    return body, new


def check_saved(body, new, field, text, approved=False):
    names = synth.names()
    assert len(new) == 1, (body["reply"], new)
    assert new[0]["field"] == field and new[0]["text"] == text
    if approved:
        assert new[0].get("label") == notecmd.APPROVED_LABEL
    assert body["draft_changed"] is True                                   # the panel reloads
    assert body["added"] and body["added"]["note_id"] == new[0]["id"]
    assert names[field] in body["reply"].split("\n\n")[-1]                # the app's closing line names the section
    assert "can't place" not in body["reply"].lower()


def test_every_add_in_the_session_sequence_saves_a_new_note(c):
    body, new = step(c, "methods are very good and rigorous",
                     {"reply": "Okay.", "views": [{"text": "methods are very good and rigorous", "section": "strengths"}]})
    check_saved(body, new, "strengths", "methods are very good and rigorous")

    body, new = step(c, "can you suggest a line for my strengths?", {"reply": STRENGTHS_PROPOSAL})
    assert new == []
    body, new = step(c, "this is good add it to the draft", {"reply": "I can't place my wording into it."})
    check_saved(body, new, "strengths", STRENGTHS_TEXT, approved=True)

    body, new = step(c, "can you summarize the paper for me?", {"reply": SUMMARY_PROPOSAL})
    assert new == []
    body, new = step(c, "you can add the draft as is", {"reply": "I can't place my wording into it."})
    check_saved(body, new, "summary", SUMMARY_TEXT, approved=True)

    body, new = step(c, WEAKNESS, {"reply": "Okay, I see."}, f"VIEW | weaknesses | {WEAKNESS}")
    check_saved(body, new, "weaknesses", WEAKNESS)


@pytest.mark.parametrize("approval", ["add it", "this is good add it to the draft", "you can add the draft as is",
                                      "yes, add that to my review", "looks good, add it as is"])
def test_approving_a_proposed_quote_saves_exactly_that_text_in_its_section(c, approval):
    step(c, "can you suggest a line for my strengths?", {"reply": STRENGTHS_PROPOSAL})
    body, new = step(c, approval, {"reply": "I can't place my wording into it."})
    check_saved(body, new, "strengths", STRENGTHS_TEXT, approved=True)
    assert "(Section" not in new[0]["text"]


def test_a_later_statement_is_saved_even_if_its_words_appear_in_an_earlier_note(c):
    step(c, "can you summarize the paper for me?", {"reply": SUMMARY_PROPOSAL})
    step(c, "add it")
    body, new = step(c, WEAKNESS, {"reply": "Okay, I see.", "views": [{"text": WEAKNESS, "section": "weaknesses"}]})
    check_saved(body, new, "weaknesses", WEAKNESS)


def test_the_same_statement_twice_in_the_same_section_is_told_not_silently_dropped(c):
    step(c, WEAKNESS, {"reply": "Okay.", "views": [{"text": WEAKNESS, "section": "weaknesses"}]})
    body, new = step(c, WEAKNESS + ".", {"reply": "Okay.", "views": [{"text": WEAKNESS, "section": "weaknesses"}]})
    assert new == []
    assert "already" in body["reply"].split("\n\n")[-1] and synth.names()["weaknesses"] in body["reply"]


def test_add_it_with_nothing_proposed_says_so_plainly(c):
    body, new = step(c, "add it", {"reply": "I can't place my wording into it."})
    assert new == [] and "can't place" not in body["reply"]
    assert body["reply"] == capture.NOT_ADDED
