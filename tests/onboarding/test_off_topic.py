"""Off-topic handling in the six free-text fields.

First off-topic reply: one concrete follow-up that offers a skip. Second: an empty value, and move on.
The junk itself is never stored. Rules decide first; the optional model check only gets replies the rules
cannot place, never judges quality, and its failure falls back to the rules.
"""
import json

import pytest

from app import onboarding as ob, llm
from app.prompts import NEUTRALITY
from test_onboarding import Session

FREE = ["strength_criteria", "weakness_criteria", "over_under_penalize", "hardest_part",
        "excellent_review_example", "bad_review_traits"]
JUNK = ["", "   ", "banana", "?", "what is your name?", "can you tell me a joke", "aaaaaaaa", "hahahaha",
        "the weather is lovely today", "my cat is called Bob", "I like pizza", "asdfasdf asdfasdf"]
VAGUE_BUT_SINCERE = ["I mostly go with my gut", "it depends on the paper", "I just trust my feelings",
                     "whatever seems right to me", "I don't really have a system", "I go by overall impression",
                     "usually just a general sense", "I tend to follow my instincts"]


def at(field, **kw):
    """A session sitting on `field`'s first question, earlier questions skipped with 'idk'."""
    s = Session(**kw)
    r = s.step()
    while r["field"] != field:
        r = s.say("idk")
    return s


def everything_stored(s):
    return json.dumps([e["payload"] for e in s.evs])


# ------------------------------------------------------------------ junk is never stored

@pytest.mark.parametrize("field", FREE)
@pytest.mark.parametrize("junk", JUNK)
def test_junk_gets_one_followup_with_a_skip_then_an_empty_value(field, junk):
    s = at(field)
    r = s.say(junk)
    assert (r["field"], r["kind"]) == (field, "followup")
    assert r["question"].startswith("I didn't catch that as an answer.") and r["question"].endswith("Or say skip.")
    assert r["question"].count("?") == 1
    assert s.profile()["fields"][field] is None  # nothing stored yet
    r = s.say(junk)
    assert r.get("field") != field
    got = s.profile()["fields"][field]
    assert got["value"] == "" and got["source"] == "default" and got["reason"] == "off_topic"
    if len(junk.strip()) > 3:
        assert junk not in everything_stored(s)  # not in the profile, and not in the answer log either


def test_the_followup_is_the_concrete_question_from_the_spec():
    r = at("weakness_criteria").say("banana")
    assert r["question"] == "I didn't catch that as an answer. What do you look for in a weakness? Or say skip."


@pytest.mark.parametrize("field", FREE)
def test_a_real_answer_after_the_followup_is_kept(field):
    s = at(field)
    s.say("banana")
    s.say("I look at whether the claims are supported by the experiments")
    got = s.profile()["fields"][field]
    assert got["source"] == "answer" and got["value"].startswith("I look at whether")


@pytest.mark.parametrize("field", FREE)
def test_skip_after_the_followup_ends_it_with_no_second_followup(field):
    s = at(field)
    s.say("banana")
    r = s.say("skip")
    assert r.get("field") != field and s.profile()["fields"][field]["value"] == ""
    asked = [e["payload"]["kind"] for e in s.evs if e["type"] == "onboarding_asked" and e["payload"]["field"] == field]
    assert asked == ["question", "followup"]


def test_all_junk_still_terminates_within_the_cap_and_keeps_no_junk():
    s = Session()
    s.run(["2", "somewhat", "abstract", "alone", "after", "pdf"] + ["my cat is called Bob", "lol", "?"] * 20)
    assert s.state()["closed"] is not None and s.state()["turn"] <= ob.MAX_TURNS
    for f in FREE:
        assert (s.profile()["fields"][f] or {}).get("value", "") == ""
    assert "my cat" not in everything_stored(s)


def test_idk_to_everything_still_terminates_in_one_pass():
    s = Session()
    done = s.run(["idk"])
    assert done["reason"] == "complete" and done["turn"] == len(ob.ORDER)


# ------------------------------------------------------------------ vague but sincere answers survive

@pytest.mark.parametrize("field", FREE)
@pytest.mark.parametrize("text", VAGUE_BUT_SINCERE)
def test_vague_sincere_answers_are_stored_verbatim_on_the_first_try(field, text):
    s = at(field)
    s.say(text)
    got = s.profile()["fields"][field]
    assert got["value"] == text and got["source"] == "answer"
    assert not [e for e in s.evs if e["type"] == "onboarding_asked" and e["payload"]["kind"] == "followup"
                and e["payload"]["field"] == field]


def test_menu_picks_by_number_are_on_topic():
    s = Session()
    s.step(); s.say("0"); s.say("never worked on it")
    for a in ("abstract", "alone", "after", "pdf"):
        s.say(a)
    s.say("1, 3")
    assert s.profile()["fields"]["strength_criteria"]["source"] == "answer"


# ------------------------------------------------------------------ the optional model check (reject-only)

class Check:
    def __init__(self, result=None, boom=False):
        self.result, self.boom, self.calls = result, boom, []

    def __call__(self, field, text):
        self.calls.append((field, text))
        if self.boom:
            raise RuntimeError("model down")
        return self.result


OBVIOUS_JUNK = ["the weather is lovely", "my cat is sleeping", "asdf lol", "the weather is lovely today",
                "my cat is called Bob", "I like pizza", "asdfasdf asdfasdf", "pineapple chunks on a margherita are my kind of thing"]
RULES_ACCEPT = "Missing ablations on the main component"  # topical vocabulary: the rules accept it


@pytest.mark.parametrize("field", FREE)
@pytest.mark.parametrize("junk", OBVIOUS_JUNK)
def test_a_model_that_always_says_on_topic_cannot_get_junk_stored(field, junk):
    c = Check(True)
    s = at(field, check=c)
    r = s.say(junk)
    assert (r["field"], r["kind"]) == (field, "followup")  # still treated as off-topic
    s.say(junk)
    assert s.profile()["fields"][field]["value"] == ""
    assert junk not in everything_stored(s)
    assert c.calls == []  # the model never even sees what the rules rejected


@pytest.mark.parametrize("field", FREE)
def test_vague_sincere_answers_survive_a_model_that_says_on_topic(field):
    c = Check(True)
    s = at(field, check=c)
    s.say("I mostly go with my gut")
    assert s.profile()["fields"][field]["value"] == "I mostly go with my gut"
    assert c.calls == [(field, "I mostly go with my gut")]  # the rules accepted it; the model only confirmed


@pytest.mark.parametrize("field", FREE)
def test_the_model_can_reject_a_reply_the_rules_accepted(field):
    c = Check(False)
    s = at(field, check=c)
    r = s.say(RULES_ACCEPT)
    assert (r["field"], r["kind"]) == (field, "followup") and s.profile()["fields"][field] is None
    s.say(RULES_ACCEPT)
    assert s.profile()["fields"][field]["value"] == "" and RULES_ACCEPT not in everything_stored(s)


@pytest.mark.parametrize("check", [Check(boom=True), Check(None), Check("yes"), Check(True), Check(0)])
def test_anything_but_an_explicit_no_keeps_what_the_rules_accepted(check):
    s = at("weakness_criteria", check=check)
    s.say(RULES_ACCEPT)
    assert s.profile()["fields"]["weakness_criteria"]["value"] == RULES_ACCEPT
    assert len(check.calls) == 1


@pytest.mark.parametrize("check", [Check(boom=True), Check(None), Check("yes")])
def test_a_failing_or_useless_model_check_never_blocks_onboarding(check):
    s = Session(check=check)
    done = s.run([RULES_ACCEPT, OBVIOUS_JUNK[0]])
    assert done["done"] and s.state()["turn"] <= ob.MAX_TURNS


def test_the_model_is_asked_once_per_rules_accepted_reply_and_never_for_the_rest():
    c = Check(True)
    s = at("weakness_criteria", check=c)
    s.say("banana"); s.say("?")       # hard junk, twice
    s2 = at("weakness_criteria", check=c)
    s2.say("skip")                    # a skip
    s3 = at("hardest_part", check=c)
    s3.say("the weather is lovely")   # rejected by the vocabulary rule
    assert c.calls == []
    s4 = at("hardest_part", check=c)
    s4.say("deciding how much detail to put in")
    assert len(c.calls) == 1


def test_menu_picks_never_reach_the_model():
    c = Check(False)
    s = Session(check=c)
    s.step(); s.say("0"); s.say("never worked on it")
    for a in ("abstract", "alone", "after", "pdf"):
        s.say(a)
    s.say("1, 3")
    assert s.profile()["fields"]["strength_criteria"]["source"] == "answer" and c.calls == []


def test_real_model_function_returns_the_models_yes_no(monkeypatch):
    monkeypatch.setattr(llm, "_chat", lambda msgs: '{"on_topic": true}')
    assert ob.model_on_topic("hardest_part", "anything") is True
    monkeypatch.setattr(llm, "_chat", lambda msgs: '{"on_topic": false}')
    assert ob.model_on_topic("hardest_part", "anything") is False
    monkeypatch.setattr(llm, "_chat", lambda msgs: '{"on_topic": "maybe"}')
    assert ob.model_on_topic("hardest_part", "anything") is None


def test_with_the_real_check_and_a_down_model_the_rules_decide_alone():
    # The suite blocks network calls: the real function raises here, as a down model would.
    for junk in OBVIOUS_JUNK:
        assert ob.free_text_ok("hardest_part", junk, ob.model_on_topic) is False
    for ok in ("the writing takes the most effort", "I mostly go with my gut"):
        assert ob.free_text_ok("hardest_part", ok, ob.model_on_topic) is True


def test_the_real_check_with_a_model_that_says_on_topic_still_rejects_junk(monkeypatch):
    monkeypatch.setattr(llm, "_chat", lambda msgs: '{"on_topic": true}')
    for junk in OBVIOUS_JUNK:
        assert ob.free_text_ok("hardest_part", junk, ob.model_on_topic) is False
    assert ob.free_text_ok("hardest_part", "I mostly go with my gut", ob.model_on_topic) is True


def test_the_topic_prompt_is_reject_only_neutral_and_never_asks_for_quality():
    assert NEUTRALITY in ob.TOPIC_SYS
    assert "false ONLY when the reply has no relation to the question" in ob.TOPIC_SYS
    assert "When in doubt, answer true" in ob.TOPIC_SYS
    assert "Never judge whether the reply is good, correct, complete, or well reasoned" in ob.TOPIC_SYS
