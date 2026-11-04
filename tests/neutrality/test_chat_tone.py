"""Item 5: tone. Acknowledge briefly, vary phrasing, allow plain statements; onboarding acknowledges each
answer without grading it."""
import re

import pytest

from app import chat_checks as cc, chatflow, onboarding as ob
from app.verify import BANNED
from conftest import make_reviewer

PRAISE = re.compile(r"\b(good|great|nice|interesting|excellent|perfect|wonderful|helpful|fair|right|correct|"
                    r"smart|insightful|thoughtful|valid|love|appreciate)\b", re.I)


def post(c, message, rid="newbie"):
    r = c.post("/chat/p1", json={"reviewer_id": rid, "message": message})
    assert r.status_code == 200, r.text
    return r.json()


def ack_of(reply):
    return reply.split("\n\n")[0]


# ------------------------------------------------------------------ the acknowledgements themselves

def test_no_acknowledgement_grades_the_answer():
    every = chatflow.ACKS + chatflow.ACKS_SKIPPED + [a.format(w="x y z w") for a in chatflow.ACKS_QUOTING]
    for a in every:
        assert not PRAISE.search(a), a
        assert not BANNED.search(a) and not cc.OPINION.search(a), a
        assert a.count("?") == 0


def test_consecutive_acknowledgements_differ():
    for pool in (chatflow.ACKS, chatflow.ACKS_SKIPPED, chatflow.ACKS_QUOTING):
        assert len(set(pool)) == len(pool) >= 3
        picks = [chatflow.onboarding_ack("answered", "one two three four five", True, t) if pool is not chatflow.ACKS_SKIPPED
                 else chatflow.onboarding_ack("skipped", "idk", True, t) for t in range(12)]
        assert all(a != b for a, b in zip(picks, picks[1:]))


def test_an_unclear_reply_or_a_first_message_gets_no_acknowledgement():
    assert chatflow.onboarding_ack("unclear", "banana", True, 3) == ""
    assert chatflow.onboarding_ack(None, "hi", True, 0) == ""


def test_the_reviewers_own_words_are_reflected_back_for_longer_free_text_only():
    a = chatflow.onboarding_ack("answered", "claims that the experiments actually back up", True, 0)
    assert "claims that the experiments actually back up" in a and a.startswith("Got it: ")
    assert "claims" not in chatflow.onboarding_ack("answered", "claims that the experiments actually back up", False, 0)
    assert "7 papers" not in chatflow.onboarding_ack("answered", "7 papers", True, 0)       # too short to quote


# ------------------------------------------------------------------ onboarding in the chat thread

def test_the_first_message_gets_an_introduction_and_the_first_question(chat_env):
    c, _ = chat_env
    body = post(c, "hi")
    assert body["reply"].startswith(chatflow.INTRO) and "how many papers" in body["reply"].lower()
    assert body["reply"].count("?") == 1 and "skip any of them" in body["reply"]


def test_every_answer_is_acknowledged_in_a_few_words_before_the_next_question(chat_env):
    c, _ = chat_env
    post(c, "hi")
    answers = ["7 papers", "it is my own area", "I read the abstract first", "on my own first", "after I read it",
               "annotations in the pdf", "claims that the experiments actually back up",
               "results reported without variance"]
    acks, questions = [], []
    for a in answers:
        reply = post(c, a)["reply"]
        ack, _, rest = reply.partition("\n\n")
        assert rest and len(ack.split()) <= 20, reply                      # a few words, then the next question
        assert rest.count("?") == 1 and not PRAISE.search(ack), reply
        acks.append(ack)
        questions.append(rest)
    assert acks[-2].startswith("Got it:") or "claims that the experiments" in acks[-2]   # free text was reflected
    assert all(a != b for a, b in zip(acks, acks[1:]))                                      # phrasing varies
    assert len(set(questions)) == len(questions)


def test_a_skip_is_acknowledged_as_a_skip_not_as_an_answer(chat_env):
    c, _ = chat_env
    post(c, "hi")
    reply = post(c, "idk")["reply"]
    assert ack_of(reply) in chatflow.ACKS_SKIPPED and "familiar" in reply.lower()


def test_an_unclear_answer_goes_straight_to_the_follow_up(chat_env):
    c, _ = chat_env
    post(c, "hi")
    reply = post(c, "banana")["reply"]
    assert not any(reply.startswith(a) for a in chatflow.ACKS + chatflow.ACKS_SKIPPED)
    assert reply.count("?") == 1


def test_the_closing_message_after_the_last_answer_is_acknowledged_too(chat_env):
    c, _ = chat_env
    body = post(c, "hi")
    for _ in range(30):
        body = post(c, "idk")
        if body["onboarding"]["done"]:
            break
    assert body["onboarding"]["done"] and ack_of(body["reply"]) in chatflow.ACKS_SKIPPED
    assert "That's all I need" in body["reply"]


# ------------------------------------------------------------------ chat mode

def plain(text):
    return {"reply": text}


@pytest.fixture
def env(chat_env):
    c, set_model = chat_env
    make_reviewer("rev")
    return c, set_model


def talk(c, msg):
    return post(c, msg, rid="rev")


def test_a_plain_statement_is_a_fine_reply(env):
    c, set_model = env
    set_model(plain("Noted. Section 4 lists the datasets, and Table 2 has the per-dataset accuracy."))
    body = talk(c, "which datasets do they use?")
    assert body["checks"] == {"attempts": 1, "fallback": False} and "?" not in body["reply"]


def test_the_prompt_asks_the_model_not_to_open_the_way_it_just_did(env):
    c, set_model = env
    model = set_model(plain("Section 4 lists the datasets."))
    talk(c, "which datasets do they use?")
    assert "Your last reply began" not in model.system                       # nothing before it to avoid
    talk(c, "and the metrics?")
    assert "Your last reply began “Section 4 lists”. Begin this one differently." in model.system


def test_after_two_questions_in_a_row_the_next_reply_is_asked_to_be_a_statement(env):
    c, set_model = env
    model = set_model(plain("Which table do you mean?"))
    talk(c, "one")
    talk(c, "two")
    assert "ended with a question" not in model.system
    talk(c, "three")
    assert "Your last two replies ended with a question." in model.system
    model = set_model(plain("Table 2 has it."))
    talk(c, "four")
    talk(c, "five")
    assert "ended with a question" not in model.system


def test_onboarding_turns_do_not_count_as_the_assistants_openings(env):
    c, set_model = env
    post(c, "hi", rid="newbie")                                                # an onboarding exchange in the thread
    model = set_model(plain("Section 4 lists the datasets."))
    talk(c, "which datasets do they use?")
    assert "Your last reply began" not in model.system
