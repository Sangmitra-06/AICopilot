"""Item 1: clear answers to the structured onboarding questions are understood, never re-asked."""
import pytest

from test_onboarding import Session


def at(field):
    s = Session()
    r = s.step()
    while r["field"] != field:
        r = s.say("skip")
    return s


def assert_understood(field, reply, value):
    s = at(field)
    nxt = s.say(reply)
    rec = s.profile()["evidence" if field in ("papers_reviewed", "subarea_familiarity") else "fields"][field] or {}
    assert rec.get("value") == value and rec.get("source") == "answer", (reply, rec)
    assert not (nxt.get("field") == field), "asked again: %r" % reply
    assert not [e for e in s.evs if e["type"] == "onboarding_asked" and e["payload"]["field"] == field
                and e["payload"]["kind"] == "followup"]


@pytest.mark.parametrize("reply,value", [
    ("yes lets do it before I start reading", "before_reading"), ("yes, before", "before_reading"),
    ("before", "before_reading"), ("after I read", "after_reading"), ("yes please before", "before_reading"),
    ("I'd like it before", "before_reading"), ("I want one before I begin", "before_reading"),
    ("sure, after I've read it", "after_reading"), ("after reading", "after_reading"), ("lets do it after", "after_reading"),
    ("Before!!", "before_reading"), ("yes, after the paper", "after_reading"),
    ("not at all", "none"), ("no thanks", "none"), ("no", "none"), ("never", "none"), ("I don't need one", "none"),
])
def test_summary_question(reply, value):
    assert_understood("summary_preference", reply, value)


@pytest.mark.parametrize("reply,value", [
    ("I'll read first", "read_first"), ("yes read it myself first", "read_first"), ("on my own", "read_first"),
    ("alone", "read_first"), ("I prefer to read alone", "read_first"),
    ("talk it through", "collaborative"), ("together", "collaborative"), ("with you, as I read", "collaborative"),
    ("let's talk it through together", "collaborative"), ("you and me, talking", "collaborative"),
    ("yes, collaborative", "collaborative"), ("discuss it as we go", "collaborative"),
])
def test_workflow_question(reply, value):
    assert_understood("workflow_mode", reply, value)


@pytest.mark.parametrize("reply,value", [
    ("in the pdf", "annotate_pdf"), ("pdf annotations", "annotate_pdf"), ("separate doc", "separate_doc"),
    ("a separate document", "separate_doc"), ("in a doc", "separate_doc"), ("paper", "handwritten"),
    ("on paper", "handwritten"), ("pen and paper", "handwritten"), ("head", "in_head"), ("in my head", "in_head"),
    ("mostly in my head", "in_head"), ("yes, in the pdf", "annotate_pdf"), ("my notes app", "separate_doc"),
    ("I use a notebook", "handwritten"),
])
def test_note_question(reply, value):
    assert_understood("note_habit", reply, value)


@pytest.mark.parametrize("reply,value", [
    ("I am new to it", "unfamiliar"), ("I'm new to it", "unfamiliar"), ("new", "unfamiliar"), ("very new", "unfamiliar"),
    ("new to me", "unfamiliar"), ("not at all", "unfamiliar"), ("very familiar", "familiar"),
    ("I am very familiar", "familiar"), ("it's my area", "familiar"), ("I've worked on it for years", "familiar"),
    ("somewhat", "some"), ("a fair bit", "some"), ("a little", "some"), ("moderately familiar", "some"),
])
def test_subarea_question(reply, value):
    assert_understood("subarea_familiarity", reply, value)


@pytest.mark.parametrize("reply,value", [
    ("5", 5), ("a few", 3), ("never", 0), ("none", 0), ("I'm new to it", 0), ("a handful", 5), ("hundreds", 30),
])
def test_papers_question(reply, value):
    s = Session()
    s.step()
    s.say(reply)
    assert s.profile()["evidence"]["papers_reviewed"]["value"] == value
    assert not [e for e in s.evs if e["type"] == "onboarding_asked" and e["payload"]["kind"] == "followup"]
