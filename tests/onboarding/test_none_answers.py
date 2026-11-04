"""Sincere "nothing to add" answers in the free-text onboarding fields. (The PROFILE side is in
tests/neutrality/test_none_in_profile.py.)

In over_under_penalize, hardest_part and bad_review_traits, "none", "nothing", "no", "nope", "not really", "I don't
think so" and the like are real answers: stored with the value "none", marked as an answer (not a skip, not a default),
with no off-topic follow-up. In the other free-text fields a bare "no" is unclear: ask once. Clear junk is still
rejected, "idk" is still a skip everywhere, and a "none" is left out of the PROFILE block.
"""
import pytest

from app import chatflow, onboarding as ob
from test_off_topic import Check, FREE, at, everything_stored
from test_http import client  # noqa: F401  (the fixture: the real app over a temporary database)
from test_onboarding import Session

NONE_FIELDS = ["over_under_penalize", "hardest_part", "bad_review_traits"]
OTHER_FIELDS = ["strength_criteria", "weakness_criteria", "excellent_review_example"]

# The phrasings from the spec, exactly, and the same with the punctuation, case and curly apostrophes real typing has.
SPEC = ["none", "none that I know", "nothing", "no", "nope", "not really", "not that I can think of",
        "I don't think so", "I don't tend to"]
TYPED = ["None.", "None that I know of.", "Nothing!", "No.", "Nope.", "Not really.", "Not that I can think of.",
         "I don’t think so.", "I don’t tend to.", "No, not really.", "Honestly, nothing.", "No, I don't think so.",
         "Nah", "Not particularly", "Nothing in particular", "None really", "I do not tend to", "Um, no.",
         "No, nothing comes to mind", "I don't think so, no", "NONE"]


def asked_kinds(s, field):
    return [e["payload"]["kind"] for e in s.evs if e["type"] == "onboarding_asked" and e["payload"]["field"] == field]


def answered_outcomes(s, field):
    return [e["payload"]["outcome"] for e in s.evs if e["type"] == "onboarding_answered" and e["payload"]["field"] == field]


# ------------------------------------------------------------------ where "none" makes sense: a real answer

@pytest.mark.parametrize("field", NONE_FIELDS)
@pytest.mark.parametrize("said", SPEC + TYPED)
def test_a_sincere_nothing_is_stored_as_an_explicit_answer_without_a_follow_up(field, said):
    s = at(field)
    r = s.say(said)
    got = s.profile()["fields"][field]
    assert got["value"] == "none" and got["source"] == "answer"                  # a real answer: not a skip, not a default
    assert got["raw"] == said and "reason" not in got
    assert r.get("field") != field                                                # moved on: no off-topic follow-up
    assert asked_kinds(s, field) == ["question"] and answered_outcomes(s, field) == ["answered"]


@pytest.mark.parametrize("field", NONE_FIELDS)
def test_the_model_check_is_never_consulted_for_a_nothing(field):
    check = Check(False)                                                          # would veto, if it were asked
    s = at(field, check=check)
    s.say("none that I know")
    assert check.calls == [] and s.profile()["fields"][field]["value"] == "none"


@pytest.mark.parametrize("field", NONE_FIELDS)
def test_a_nothing_is_acknowledged_like_any_real_answer_over_http(field, client):
    from test_http import answer as post_answer
    body = client.get("/onboarding/n1").json()
    for a in ["7 papers", "it is my own area", "abstract", "alone", "after I read it", "pdf",
              "claims that the experiments back up", "results reported without variance"]:
        body = post_answer(client, "n1", a).json()
    while body["field"] != field:
        body = post_answer(client, "n1", "idk").json()
    body = post_answer(client, "n1", "nothing really").json()
    assert body["ack"] in chatflow.ACKS and body["profile"]["fields"][field]["value"] == "none"


# ------------------------------------------------------------------ elsewhere a bare "no" is unclear: ask once

@pytest.mark.parametrize("field", OTHER_FIELDS)
@pytest.mark.parametrize("said", ["no", "nope", "none", "nothing", "not really", "I don't think so", "No."])
def test_a_bare_no_is_unclear_in_the_other_fields_and_asked_once(field, said):
    s = at(field)
    r = s.say(said)
    assert (r["field"], r["kind"]) == (field, "followup")
    assert r["question"].startswith("I didn't catch that as an answer.") and r["question"].endswith("Or say skip.")
    assert s.profile()["fields"][field] is None                                   # nothing stored yet, and never "none"
    r = s.say(said)
    assert r.get("field") != field
    got = s.profile()["fields"][field]
    assert got["value"] == "" and got["source"] == "default" and got["reason"] == "no_answer"
    assert asked_kinds(s, field) == ["question", "followup"]                       # asked once, then on


@pytest.mark.parametrize("field", OTHER_FIELDS)
def test_a_real_answer_after_the_follow_up_is_kept_and_a_skip_ends_it(field):
    s = at(field)
    s.say("no")
    s.say("results reported without variance")
    assert s.profile()["fields"][field]["source"] == "answer"
    s2 = at(field)
    s2.say("no")
    r = s2.say("skip")
    assert r.get("field") != field and s2.profile()["fields"][field]["value"] == ""


# ------------------------------------------------------------------ what is NOT a "nothing"

@pytest.mark.parametrize("field", NONE_FIELDS)
@pytest.mark.parametrize("said", ["idk", "not sure", "I don't know", "no idea", "skip", "no preference", "pass"])
def test_a_skip_is_still_a_skip_everywhere_never_a_none(field, said):
    s = at(field)
    s.say(said)
    got = s.profile()["fields"][field]
    assert got["source"] == "default" and got["value"] == "" and answered_outcomes(s, field) == ["skipped"]


@pytest.mark.parametrize("field", NONE_FIELDS)
@pytest.mark.parametrize("said", [
    "no baselines in the main table", "none of the reviews I have seen were bad", "nothing about the writing bothers me",
    "no, but a missing ablation does",
])
def test_an_answer_that_merely_starts_with_no_is_kept_as_the_reviewers_words(field, said):
    s = at(field)
    s.say(said)
    got = s.profile()["fields"][field]
    assert got["source"] == "answer" and got["value"] == said                      # verbatim, not collapsed to "none"


@pytest.mark.parametrize("said", ["no baselines in the main table", "none of the work is reproducible"])
def test_a_substantive_answer_in_the_other_fields_is_kept_too(said):
    s = at("weakness_criteria")
    s.say(said)
    assert s.profile()["fields"]["weakness_criteria"]["value"] == said


# ------------------------------------------------------------------ clear junk is still rejected, when unsure we accept

JUNK = ["asdf", "my cat is sleeping", "asdfasdf asdfasdf", "the weather is lovely today", "?", "lol", "what is your name?"]


@pytest.mark.parametrize("field", FREE)
@pytest.mark.parametrize("junk", JUNK)
def test_clear_junk_is_rejected_in_every_free_text_field(field, junk):
    s = at(field)
    r = s.say(junk)
    assert (r["field"], r["kind"]) == (field, "followup")
    s.say(junk)
    got = s.profile()["fields"][field]
    assert got["value"] == "" and got["source"] == "default" and got["reason"] == "off_topic"
    assert "none" != got["value"] and (len(junk) <= 3 or junk not in everything_stored(s))


@pytest.mark.parametrize("field,word", [("strength_criteria", "clarity"), ("weakness_criteria", "reproducibility"),
                                        ("hardest_part", "scoring"), ("bad_review_traits", "vagueness"),
                                        ("over_under_penalize", "novelty"), ("excellent_review_example", "specificity")])
def test_a_single_topical_word_is_a_sincere_answer(field, word):
    s = at(field)
    r = s.say(word)
    assert s.profile()["fields"][field]["value"] == word and r.get("field") != field


@pytest.mark.parametrize("field", FREE)
@pytest.mark.parametrize("junk", ["asdf", "banana", "qwerty", "hmm"])
def test_a_single_word_that_is_not_about_reviewing_is_still_rejected(field, junk):
    s = at(field)
    assert s.say(junk)["kind"] == "followup"


@pytest.mark.parametrize("field", NONE_FIELDS)
def test_vague_sincere_answers_are_still_accepted(field):
    s = at(field)
    s.say("I mostly go with my gut")
    assert s.profile()["fields"][field]["value"] == "I mostly go with my gut"


# ------------------------------------------------------------------ onboarding always terminates

@pytest.mark.parametrize("answers", [
    ["idk"], ["no"], ["none"], ["nothing"], ["not really"], ["asdf"], ["my cat is sleeping"],
    ["7 papers", "my area", "abstract", "alone", "after I read it", "pdf"] + ["no"] * 30,
    ["7 papers", "my area", "abstract", "alone", "after I read it", "pdf"] + ["nothing", "idk", "asdf", "no"] * 10,
])
def test_onboarding_terminates_whatever_is_answered(answers):
    s = Session()
    done = s.run(answers)
    assert done["done"] and s.state()["turn"] <= ob.MAX_TURNS
    assert set(f for f in ob.FIELDS if s.profile()["fields"][f] is None) == set()


def test_idk_to_everything_still_ends_in_one_pass_with_every_field_a_default():
    s = Session()
    done = s.run(["idk"])
    assert done["reason"] == "complete" and done["turn"] == len(ob.ORDER)
    prof = s.profile()["fields"]
    assert all(prof[f]["source"] == "default" for f in ob.FIELDS)
    assert all(prof[f]["value"] != "none" for f in NONE_FIELDS)                    # a skip never becomes a "none"


def test_none_to_every_question_gives_none_where_it_makes_sense_and_defaults_elsewhere():
    s = Session()
    s.run(["7 papers", "my own area", "abstract", "alone", "after I read it", "pdf"] + ["none"] * 20)
    prof = s.profile()["fields"]
    # (the "ask once" fields use extra turns, so the 14-answer cap can close onboarding before the last field)
    assert [prof[f]["value"] for f in NONE_FIELDS[:2]] == ["none"] * 2 and all(prof[f]["source"] == "answer" for f in NONE_FIELDS[:2])
    assert [prof[f]["value"] for f in OTHER_FIELDS] == [""] * 3 and all(prof[f]["source"] == "default" for f in OTHER_FIELDS)
    assert s.profile()["closed"]["reason"] in ("complete", "cap")


def test_structured_fields_keep_their_own_rules():
    s = Session()
    s.say("no")                                                                    # papers reviewed: none, a real zero
    assert s.state()["evidence"]["papers_reviewed"]["value"] == 0
    s.say("my own area")
    s.say("abstract")
    s.say("alone")
    s.say("after I read it")
    r = s.say("no")                                                                # note habit: a skip, as before
    assert s.profile()["fields"]["note_habit"]["source"] == "default" and r["field"] == "strength_criteria"
