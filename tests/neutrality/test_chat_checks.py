"""Item 2: every chat reply passes the neutrality checks; regenerate once, then a neutral fallback."""
import logging

import pytest

from app import chat_checks as cc, chatflow, store
from conftest import make_reviewer

CTX = {"reviewer_text": "I think the baseline seems weak and the sample is small", "wants_decline": False,
       "summary_pref": "after_reading", "summary_requested": False}


def errs(reply, **over):
    return cc.reply_errors(reply, {**CTX, **over})


# ------------------------------------------------------------------ the checks themselves

@pytest.mark.parametrize("reply", [
    "Section 4 reports accuracy of 71.2 on SST-2 and 64.0 on CoLA.",
    "You find the baseline weak, and Table 2 is where the baselines are listed.",   # their word, addressed to them
    'The authors write "a strong baseline" in Section 4; you said weak. Want to look at Table 2?',
    "The method uses weak supervision from parsed sentences (Section 3).",           # a technical term
    "Okay, so the sample size is on your mind. Is that okay to put under weaknesses?",
    "Noted. That sits next to the datasets paragraph in Section 4.",
])
def test_ordinary_neutral_replies_pass(reply):
    assert errs(reply) == []


@pytest.mark.parametrize("reply", [
    "This paper is novel.",
    "The results are convincing and the method is key.",
    "The baseline is weak.",                # unaddressed: the reviewer's word does not license it
    "The evaluation is sound.",
    "The comparison is fair.",
    "I agree with you here.",
    "You're right about that.",
    "Good point, the sample is small.",
    "That's a fair concern.",
    "I think the paper is fine.",
    "I would accept it.",
])
def test_opinions_and_evaluations_are_rejected(reply):
    assert errs(reply), reply


@pytest.mark.parametrize("reply", [
    "Section 4 has the numbers. Back to Weaknesses?",
    "Noted. Anything else to add?",
    "That is in Table 2. Want to move on?",
    "Got it. Back to the strengths section.",
])
def test_a_stock_closing_re_ask_is_rejected(reply):
    assert any("stock line" in e for e in errs(reply)), reply


def test_a_pile_of_questions_is_rejected_and_two_are_not():
    assert errs("Which table? Which dataset? Which metric?")
    assert not errs("Which table is that? And which metric?")


def test_quoted_words_are_not_checked():
    assert errs('Section 2 says "this novel, key, strong approach" in the first line.') == []


def test_a_judgment_question_must_be_declined_in_the_first_sentence():
    ctx = {"wants_decline": True}
    assert errs("Yes, it looks original to me.", **ctx)
    assert errs("Section 4 lists three baselines. That one is your call.", **ctx)        # decline not first
    long_decline = ("That's your call, but there is a very long explanation of why it could go one way or the "
                    "other for every reviewer who reads a paper like this one on a given day of the week, "
                    "and I will go through all of it now.")
    assert len(long_decline.split()) > 35
    assert errs(long_decline, **ctx)                                                      # first sentence too long
    assert errs("That's a judgment call, so it stays with you. You said you look for results reported with "
                "variance; Table 2 shows none, if you want to check.", **ctx) == []


def test_summaries_are_only_volunteered_when_the_profile_allows_it_and_need_pointers():
    s = "Here's a short summary: the authors report accuracy on three datasets (Section 4)."
    assert errs(s, summary_requested=False)                          # after_reading: not volunteered
    assert not errs(s, summary_requested=True)                       # asked for: fine
    assert not errs(s, summary_pref="before_reading")                # wanted early: fine
    assert errs("Here's a short summary: the authors report accuracy on three datasets.", summary_requested=True)


@pytest.mark.parametrize("msg", [
    "is this novel?", "do you agree?", "should I accept", "is the baseline comparison fair?",
    "The baseline is weak. Do you agree", "what score would you give it", "is this a good paper?",
])
def test_requests_for_the_assistants_judgment_are_recognised(msg):
    assert cc.asks_for_judgment(msg), msg


@pytest.mark.parametrize("msg", [
    "The baseline is weak and the writing is sloppy, I think.",     # the reviewer stating their view
    "I think this is a good paper.",
    "reword this: The comparison is not fair.",
    "The evaluation is not sound and the results are unconvincing.",
    "why did they reject outliers?", "what does valid mean?", "where do they state the contribution?",
])
def test_the_reviewer_stating_their_own_view_is_not_a_judgment_request(msg):
    assert not cc.asks_for_judgment(msg), msg


# ------------------------------------------------------------------ regenerate once, then the fallback

def post(c, message, rid="rev"):
    return c.post("/chat/p1", json={"reviewer_id": rid, "message": message}).json()


BAD = {"reply": "The baseline is weak and this paper is novel."}
GOOD = {"reply": "Table 2 lists the baselines (Section 4)."}


def test_a_bad_reply_is_regenerated_once_and_the_good_one_is_shown(chat_env):
    c, set_model = chat_env
    model = set_model(BAD, GOOD)
    make_reviewer("rev")
    body = post(c, "which baselines do they use?")
    assert body["reply"] == GOOD["reply"] and body["checks"] == {"attempts": 2, "fallback": False}
    assert len(model.calls) == 2
    retry = model.calls[1]
    assert retry[-2]["role"] == "assistant" and retry[-1]["role"] == "user"
    assert "Problems with the last one" in retry[-1]["content"] and "evaluative" in retry[-1]["content"]


def test_two_bad_replies_give_a_short_neutral_fallback(chat_env):
    c, set_model = chat_env
    model = set_model(BAD)
    make_reviewer("rev")
    body = post(c, "which baselines do they use?")
    assert body["reply"] == chatflow.FALLBACK and body["checks"] == {"attempts": 2, "fallback": True}
    assert len(model.calls) == 2 and not cc.reply_errors(body["reply"], CTX)


def test_the_correction_turns_never_reach_the_history(chat_env):
    c, set_model = chat_env
    model = set_model(BAD, GOOD, GOOD)
    make_reviewer("rev")
    post(c, "first")
    post(c, "second")
    hist = model.calls[-1][1:-1]
    assert [m["content"] for m in hist] == ["first", GOOD["reply"]]


def test_a_down_model_is_a_fallback_not_a_500(chat_env, monkeypatch):
    c, _ = chat_env

    def boom(msgs):
        raise RuntimeError("model down")
    monkeypatch.setattr(chatflow, "_chat", boom)
    make_reviewer("rev")
    r = c.post("/chat/p1", json={"reviewer_id": "rev", "message": "hi"})
    assert r.status_code == 200 and r.json()["reply"] == chatflow.FALLBACK


# ------------------------------------------------------------------ judgment questions

@pytest.mark.parametrize("q", ["is this novel?", "do you agree?", "should I accept?", "is the baseline comparison fair?"])
def test_judgment_question_gets_a_one_sentence_decline_then_help(chat_env, q):
    c, set_model = chat_env
    model = set_model({"reply": "That's your call to make, not mine. You said you look for results reported "
                                "with variance; I can show where Table 2 reports them."})
    make_reviewer("rev")
    body = post(c, q)
    assert body["checks"]["attempts"] == 1 and body["reply"].startswith("That's your call")
    assert "request for your own judgment" in model.system  # the model was told to decline first


def test_a_model_that_answers_a_judgment_question_gets_the_decline_fallback(chat_env):
    c, set_model = chat_env
    set_model({"reply": "Yes, it looks original and I would say it is a solid contribution."})
    make_reviewer("rev", weakness_criteria="results reported without variance")
    body = post(c, "is this novel?")
    assert body["checks"]["fallback"] is True
    assert body["reply"].startswith("That's a judgment call, so it stays with you.")
    assert "results reported without variance" in body["reply"]
    assert len([x for x in body["reply"].split(".") if x.strip()]) <= 3  # one-sentence decline plus a redirect


def test_a_reply_that_never_declines_is_regenerated(chat_env):
    c, set_model = chat_env
    set_model({"reply": "Table 2 reports accuracy on two datasets."},
              {"reply": "That one is yours to decide. Table 2 reports accuracy on two datasets (Section 4)."})
    make_reviewer("rev")
    body = post(c, "do you agree?")
    assert body["checks"]["attempts"] == 2 and body["reply"].startswith("That one is yours")


# ------------------------------------------------------------------ logging how often the checks reject

def test_rejections_and_fallbacks_are_logged_and_counted(chat_env, caplog):
    c, set_model = chat_env
    make_reviewer("rev")
    before = dict(cc.STATS)
    with caplog.at_level(logging.INFO, logger="copilot.chat"):
        set_model(GOOD)
        post(c, "one")        # passes first try
        set_model(BAD, GOOD)
        post(c, "two")        # regenerated
        set_model(BAD)
        post(c, "three")      # fallback
    st = store.chat_check_stats("p1")
    assert st == {"replies": 3, "rejected_first_try": 2, "regenerated_ok": 1, "fallbacks": 1,
                  "reject_rate": 0.667, "fallback_rate": 0.333}
    assert cc.STATS["replies"] - before.get("replies", 0) == 3
    assert cc.STATS["fallbacks"] - before.get("fallbacks", 0) == 1
    msgs = [r.getMessage() for r in caplog.records if r.name == "copilot.chat"]
    assert any("replaced by the fallback" in m for m in msgs) and any("regenerated" in m for m in msgs)


def test_stats_for_a_paper_with_no_chat_are_zero(chat_env):
    assert store.chat_check_stats("p1")["reject_rate"] == 0.0
