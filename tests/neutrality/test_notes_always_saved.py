"""Item 4: every "Added to X" line has a matching note in GET /notes and in the Review draft panel, the Paper summary
section included; and "what else do I have to add?" and "draft it" both take it into account."""
import pytest

from app import store
from conftest import make_reviewer
from test_chat_capabilities import fake_drafter, post

SUMMARY_SENTENCE = "The paper probes syntax in pretrained encoders with three datasets"
OTHER = "The probing dataset is released with the paper"


@pytest.fixture
def env(chat_env, monkeypatch):
    c, set_model = chat_env
    make_reviewer("rev")
    fake_drafter(monkeypatch)
    return c, set_model


def state_notes(c):
    return c.get("/notes/p1").json()


def offer_and_accept(c, set_model, section, text, label):
    set_model({"reply": "Got it. Want me to add that to your draft?", "views": [{"text": text, "section": section}]}, {"reply": "Okay."})
    offered = post(c, f"My view: {text}")
    assert offered["capture"]["section"] == section
    assert state_notes(c) == [] or all(n["text"] != text for n in state_notes(c))        # nothing is written before a yes
    done = post(c, "yes")
    assert f"Added to {label}" in done["reply"], done["reply"]
    return done


@pytest.mark.parametrize("section,label", [("summary", "Paper summary"), ("strengths", "Summary of strengths"),
                                           ("weaknesses", "Summary of weaknesses"), ("comments", "Comments, suggestions and typos")])
def test_every_added_line_has_a_note_in_notes_under_that_section(env, section, label):
    c, set_model = env
    done = offer_and_accept(c, set_model, section, SUMMARY_SENTENCE, label)
    notes = state_notes(c)
    assert [(n["text"], n["field"]) for n in notes] == [(SUMMARY_SENTENCE, section)]
    assert done["added"] == {"note_id": notes[0]["id"], "section": section, "label": label}
    assert done["draft_changed"] is True


def test_the_full_summary_flow_notes_gaps_and_draft(env):
    c, set_model = env
    offer_and_accept(c, set_model, "summary", SUMMARY_SENTENCE, "Paper summary")
    assert [n["field"] for n in state_notes(c)] == ["summary"]

    set_model({"reply": "unused"})
    gaps = post(c, "what else do I have to add?")
    required = next(l for l in gaps["reply"].splitlines() if l.startswith("- Required"))
    assert "Paper summary" not in required and "Summary of strengths" in required      # the summary is no longer open

    drafted = post(c, "draft it")
    assert SUMMARY_SENTENCE in drafted["reply"] and "Paper summary" in drafted["reply"]
    gen = c.get("/draft/p1").json()
    assert [s["text"] for s in gen["summary"]["sentences"]] == [SUMMARY_SENTENCE]


def test_a_note_accepted_after_the_draft_was_made_is_saved_too(env):
    c, set_model = env
    offer_and_accept(c, set_model, "summary", SUMMARY_SENTENCE, "Paper summary")
    post(c, "draft it")
    done = offer_and_accept(c, set_model, "summary", OTHER, "Paper summary")
    assert {n["text"] for n in state_notes(c)} == {SUMMARY_SENTENCE, OTHER}
    assert done["added"]["note_id"] in {n["id"] for n in state_notes(c)}
    redraft = post(c, "draft it")
    assert OTHER in redraft["reply"] and SUMMARY_SENTENCE in redraft["reply"]


def test_a_retargeted_offer_is_saved_where_the_line_says(env):
    c, set_model = env
    set_model({"reply": "Got it. Want me to add that to your draft?", "views": [{"text": SUMMARY_SENTENCE, "section": "weaknesses"}]}, {"reply": "Okay."})
    post(c, f"My view: {SUMMARY_SENTENCE}")
    done = post(c, "no I mean the paper summary")
    assert "Added to Paper summary" in done["reply"]
    assert [(n["text"], n["field"]) for n in state_notes(c)] == [(SUMMARY_SENTENCE, "summary")]


def test_an_added_line_without_a_note_cannot_be_made(env):
    c, set_model = env
    set_model({"reply": "Added to Paper summary, in your own words."})
    body = post(c, "ok")
    assert "Added to" not in body["reply"] and state_notes(c) == []
