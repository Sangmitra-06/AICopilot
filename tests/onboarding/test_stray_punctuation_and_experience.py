"""Item 4: onboarding answers are read through stray punctuation and a leading "yes", and clear experience answers are not
followed up.
  (a) "yes, before '" is "before" and the question is not asked again.
  (b) "very familiar", "I know it quite well", "new to me" are answers; no follow-up.
"""
import pytest

from app import onboarding as ob
from test_onboarding import Session


def at(field):
    """A session whose pending question is `field` (earlier ones answered/skipped)."""
    s = Session()
    resp = s.step()
    while resp["field"] != field:
        resp = s.say("skip")
    return s


# ------------------------------------------------------------------ (a) stray punctuation

@pytest.mark.parametrize("reply,value", [
    ("yes, before '", "before_reading"), ("yes, before", "before_reading"), ("Yes - before!", "before_reading"),
    ("'before'", "before_reading"), ("before ''", "before_reading"), ("\"before\"", "before_reading"),
    ("yeah, before i read it ``", "before_reading"), ("ok, after '", "after_reading"), ("yes, after.", "after_reading"),
    ("sure, afterwards", "after_reading"), ("`after`", "after_reading"),
])
def test_summary_preference_is_read_through_stray_punctuation_and_a_leading_yes(reply, value):
    s = at("summary_preference")
    nxt = s.say(reply)
    assert s.val("summary_preference") == value and s.src("summary_preference") == "answer"
    assert nxt["field"] != "summary_preference"                                  # moved on: not asked again


def test_the_exact_case_is_not_reasked():
    s = at("summary_preference")
    nxt = s.say("yes, before '")
    assert nxt["kind"] == "question" and nxt["field"] == "note_habit"
    assert [e for e in s.evs if e["type"] == "onboarding_asked" and e["payload"]["field"] == "summary_preference"
            and e["payload"]["kind"] == "followup"] == []


def test_a_bare_yes_is_still_unclear_and_asked_once():
    s = at("summary_preference")
    nxt = s.say("yes")
    assert nxt["field"] == "summary_preference" and nxt["kind"] == "followup"


def test_the_stored_words_are_the_reviewers_own_untouched():
    s = at("summary_preference")
    s.say("yes, before '")
    assert s.profile()["fields"]["summary_preference"]["raw"] == "yes, before '"


@pytest.mark.parametrize("reply,field,value", [
    ("yes, alone first '", "workflow_mode", "read_first"),
    ("\"alone\"", "workflow_mode", "read_first"),
    ("ok, 7 '", "papers_reviewed", 7), ("'12'", "papers_reviewed", 12),
])
def test_other_structured_questions_get_the_same_tolerance(reply, field, value):
    s = at(field)
    s.say(reply)
    evidence = s.state()["evidence"]
    got = evidence[field]["value"] if field in ob.EVIDENCE else s.val(field)
    assert got == value


def test_tidy_leaves_ordinary_answers_alone():
    for t in ["I start with the intro", "5 papers", "don't know", "it's my area"]:
        assert ob.tidy(t) == t
    assert ob.tidy("yes") == "yes"                                               # never emptied
    assert ob.tidy("  yes, before ' ") == "before"


# ------------------------------------------------------------------ (b) clear experience answers

CLEAR = [
    ("very familiar", "familiar"), ("I know it quite well", "familiar"), ("new to me", "unfamiliar"),
    ("I know this area well", "familiar"), ("I know it pretty well", "familiar"), ("quite familiar", "familiar"),
    ("it's new to me", "unfamiliar"), ("completely new to me", "unfamiliar"), ("totally new", "unfamiliar"),
    ("I've never worked on this", "unfamiliar"), ("pretty new to me", "unfamiliar"),
    ("I'm a beginner in this area", "unfamiliar"), ("somewhat familiar", "some"), ("I know it a bit", "some"),
    ("It's my own area", "familiar"), ("yes, very familiar", "familiar"), ("Very familiar!", "familiar"),
]


@pytest.mark.parametrize("reply,value", CLEAR)
def test_a_clear_familiarity_answer_gets_no_followup(reply, value):
    s = at("subarea_familiarity")
    nxt = s.say(reply)
    assert s.state()["evidence"]["subarea_familiarity"]["value"] == value
    assert nxt["field"] != "subarea_familiarity" and nxt["kind"] == "question"
    assert not [e for e in s.evs if e["type"] == "onboarding_asked" and e["payload"]["field"] == "subarea_familiarity"
                and e["payload"]["kind"] == "followup"]


@pytest.mark.parametrize("reply,count", [("quite a lot", 20), ("a few", 3), ("none yet", 0), ("this is my first", 0),
                                         ("about ten", 10)])
def test_a_clear_papers_answer_gets_no_followup(reply, count):
    s = Session()
    s.step()
    nxt = s.say(reply)
    assert s.state()["evidence"]["papers_reviewed"]["value"] == count and nxt["field"] == "subarea_familiarity"


def test_vague_answers_are_still_followed_up_once_then_defaulted():
    s = at("subarea_familiarity")
    nxt = s.say("hmm hard to say really")
    assert nxt["field"] == "subarea_familiarity" and nxt["kind"] == "followup"
    nxt = s.say("dunno, mixed")
    assert nxt["field"] != "subarea_familiarity"


def test_experience_level_is_still_inferred_from_the_evidence():
    s = Session()
    s.step()
    s.say("12")
    s.say("I know it quite well")
    assert s.val("experience_level") == "high"
