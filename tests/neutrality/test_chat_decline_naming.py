"""A decline may name the thing it declines ("Whether I agree isn't something I can weigh in on"), under the same
narrow rule as for evaluative words: naming is allowed, asserting is not."""
import hashlib

import pytest

from app import chat_checks as cc, llm, verify
from conftest import make_reviewer

CTX = {"reviewer_text": "is this novel? do you agree? should I accept?", "wants_decline": False,
       "summary_pref": "after_reading", "summary_requested": False}

# Declines that name what was asked. Each must pass the chat checks.
NAMING = [
    "Whether I agree isn't something I can weigh in on.",
    "I can't weigh in on accept or reject.",
    "Whether I agree isn't something I can weigh in on, since that call is yours.",
    "I can't weigh in on accept or reject; that call is yours. Table 2 has the numbers (Section 4).",
    "I won't say if I agree; that call is yours.",
    "I can't tell you whether to accept or reject it; that stays with you.",
    "Whether I would accept it isn't mine to say.",
    "I can't weigh in on whether it's novel, since that's your call.",
    "That's a judgment call, so I won't say whether I'd accept it. Section 4 has the numbers.",
    "Whether it should be accepted is your call, not mine.",
]

# Sentences that take a side. Each must stay blocked, with or without a decline wrapped around it.
ASSERTING = [
    "I agree, the baseline is weak.",
    "I agree.",
    "I'd accept it.",
    "I would accept it.",
    "I think it should be accepted.",
    "It should be accepted.",
    "I disagree with you here.",
    "I can't weigh in on whether it's novel, but I'd accept it.",
    "I won't say if I agree, though I agree the comparison matters.",
    "That's your call, and I would accept it.",
    "I can't weigh in on it, but I agree.",
    "I can't weigh in on whether it is novel and I agree.",
    "Whether I agree is your call. I'd accept it, though.",
]


@pytest.mark.parametrize("sentence", NAMING)
@pytest.mark.parametrize("wants_decline", [False, True])
def test_a_decline_that_names_what_it_declines_passes(sentence, wants_decline):
    assert cc.reply_errors(sentence, {**CTX, "wants_decline": wants_decline}) == [], sentence


@pytest.mark.parametrize("sentence", ASSERTING)
def test_asserting_an_opinion_stays_blocked(sentence):
    assert cc.reply_errors(sentence, CTX), sentence


@pytest.mark.parametrize("sentence", ASSERTING)
def test_asserting_stays_blocked_even_after_a_clean_decline(sentence):
    reply = "That's a judgment call, so it stays with you. " + sentence
    assert cc.reply_errors(reply, {**CTX, "wants_decline": True}), reply


@pytest.mark.parametrize("sentence", ["I agree with you.", "I'd accept it.", "Whether I agree is something you can see in "
                                      "the numbers, and I agree."])
def test_naming_is_not_a_loophole_for_a_reply_that_never_declines(sentence):
    assert cc.reply_errors(sentence, CTX)


# ------------------------------------------------------------------ through the endpoint

def post(c, message):
    r = c.post("/chat/p1", json={"reviewer_id": "rev", "message": message})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("q,reply", [
    ("do you agree?", "Whether I agree isn't something I can weigh in on, since that call is yours. Table 2 has the "
                      "numbers (Section 4), if you want to check them against your own criteria."),
    ("should I accept?", "I can't weigh in on accept or reject; that call is yours. Table 2 has the numbers "
                         "(Section 4)."),
])
def test_these_declines_are_shown_on_the_first_try(chat_env, q, reply):
    c, set_model = chat_env
    make_reviewer("rev")
    model = set_model({"reply": reply})
    body = post(c, q)
    assert body["reply"] == reply and body["checks"] == {"attempts": 1, "fallback": False} and len(model.calls) == 1


@pytest.mark.parametrize("q,leak", [
    ("do you agree?", "I agree, the baseline is weak."),
    ("should I accept?", "I'd accept it."),
    ("should I accept?", "I think it should be accepted."),
])
def test_these_are_never_shown(chat_env, q, leak):
    c, set_model = chat_env
    make_reviewer("rev")
    set_model({"reply": leak})
    body = post(c, q)
    assert body["checks"]["fallback"] is True and leak not in body["reply"]
    assert body["reply"].startswith("That's a judgment call, so it stays with you.")


# ------------------------------------------------------------------ what was not touched

def test_verify_and_the_judge_regex_are_unchanged():
    """Pinned: changing either on purpose means updating this test on purpose."""
    h = lambda p: hashlib.sha1(p.encode()).hexdigest()[:12]
    assert (h(verify.BANNED.pattern), h(llm.JUDGE.pattern)) == (PINNED_BANNED, PINNED_JUDGE)


PINNED_BANNED = "6df06988fbdc"
PINNED_JUDGE = "72489dde4e2b"
