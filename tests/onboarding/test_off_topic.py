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


# ------------------------------------------------------------------ the optional model check

class Check:
    def __init__(self, result=None, boom=False):
        self.result, self.boom, self.calls = result, boom, []

    def __call__(self, field, text):
        self.calls.append((field, text))
        if self.boom:
            raise RuntimeError("model down")
        return self.result


AMBIGUOUS = "pineapple chunks on a margherita are my kind of thing"  # >1 word, no question, no known vocabulary


def test_model_can_rescue_an_ambiguous_reply():
    c = Check(True)
    s = at("hardest_part", check=c)
    s.say(AMBIGUOUS)
    assert c.calls == [("hardest_part", AMBIGUOUS)]
    assert s.profile()["fields"]["hardest_part"]["value"] == AMBIGUOUS


def test_model_saying_no_is_the_same_as_the_rules():
    s = at("hardest_part", check=Check(False))
    r = s.say(AMBIGUOUS)
    assert r["kind"] == "followup" and s.profile()["fields"]["hardest_part"] is None


@pytest.mark.parametrize("check", [Check(boom=True), Check(None), Check("yes")])
def test_a_failing_or_useless_model_check_never_blocks_onboarding(check):
    s = Session(check=check)
    done = s.run([AMBIGUOUS])
    assert done["done"] and s.state()["turn"] <= ob.MAX_TURNS
    assert s.profile()["fields"]["hardest_part"]["value"] == ""
    assert check.calls  # it was consulted, and the flow went on regardless


def test_the_model_is_not_consulted_when_the_rules_are_sure():
    c = Check(True)
    s = at("weakness_criteria", check=c)
    s.say("banana"); s.say("?")  # hard junk, twice
    s2 = at("weakness_criteria", check=c)
    s2.say("Missing ablations on the main component")  # known vocabulary
    assert c.calls == []


def test_the_model_check_is_not_asked_about_skips():
    c = Check(True)
    s = at("weakness_criteria", check=c)
    s.say("skip")
    assert c.calls == []


def test_real_model_function_returns_the_models_yes_no(monkeypatch):
    monkeypatch.setattr(llm, "_chat", lambda msgs: '{"on_topic": true}')
    assert ob.model_on_topic("hardest_part", "anything") is True
    monkeypatch.setattr(llm, "_chat", lambda msgs: '{"on_topic": "maybe"}')
    assert ob.model_on_topic("hardest_part", "anything") is None


def test_real_model_function_failing_falls_back_to_rules_through_free_text_ok():
    # The suite blocks network calls: the real function raises here, as a down model would.
    assert ob.free_text_ok("hardest_part", AMBIGUOUS, ob.model_on_topic) is False
    assert ob.free_text_ok("hardest_part", "the writing takes the most effort", ob.model_on_topic) is True


def test_the_topic_prompt_carries_the_neutrality_block_and_never_asks_for_quality():
    assert NEUTRALITY in ob.TOPIC_SYS
    assert "Never judge whether the reply is good, correct, complete, or well reasoned" in ob.TOPIC_SYS
