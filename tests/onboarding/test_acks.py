"""Onboarding acknowledgements in the /onboarding/* path (the one the chat-first frontend uses).

POST /onboarding/{rid}/answer returns an "ack": a few neutral words acknowledging a real answer, shown before the next
question. It is empty after a skip, after an off-topic reply that earned a follow-up, on a GET, and on a 409. It never
comments on whether the answer is good, and never repeats the reviewer's words back.
"""
import re

import pytest

from app import chatflow, onboarding as ob
from app.verify import BANNED
from app import chat_checks as cc
from test_http import client  # noqa: F401  (the fixture: the real app over a temporary database)

PRAISE = re.compile(r"\b(good|great|nice|interesting|excellent|perfect|wonderful|helpful|fair|right|correct|smart|"
                    r"insightful|thoughtful|valid|love|appreciate|impressive|strong|weak|clear|thorough)\b", re.I)


def answer(client, rid, text):
    r = client.post(f"/onboarding/{rid}/answer", json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


def first(client, rid="r1"):
    return client.get(f"/onboarding/{rid}").json()


# ------------------------------------------------------------------ when there is an acknowledgement

def test_a_real_answer_is_acknowledged_in_a_few_plain_words(client):
    first(client)
    body = answer(client, "r1", "7 papers")
    assert body["ack"] in chatflow.ACKS
    assert len(body["ack"].split()) <= 4 and "?" not in body["ack"]
    assert body["field"] == "subarea_familiarity" and body["question"].startswith("How familiar")   # the question is separate


def test_the_acknowledgement_never_repeats_the_reviewers_words(client):
    first(client)
    said = "I mostly read the abstract first and then the results table"
    answer(client, "r1", "7 papers")
    answer(client, "r1", "it is my own area")
    body = answer(client, "r1", said)
    assert body["ack"] in chatflow.ACKS and "abstract" not in body["ack"].lower()


def test_a_get_has_no_acknowledgement(client):
    assert first(client)["ack"] == ""
    assert first(client)["ack"] == ""


@pytest.mark.parametrize("skip", ["idk", "not sure", "skip this one", "no preference", "I don't know"])
def test_a_skipped_answer_gets_no_acknowledgement(client, skip):
    first(client)
    body = answer(client, "r1", skip)
    assert body["ack"] == "" and body["field"] == "subarea_familiarity"       # moved on, quietly


def test_an_off_topic_reply_that_earns_a_follow_up_gets_none(client):
    first(client)
    body = answer(client, "r1", "the weather is lovely today")
    assert body["kind"] == "followup" and body["ack"] == ""


def test_the_real_answer_after_the_follow_up_is_acknowledged(client):
    first(client)
    assert answer(client, "r1", "banana")["ack"] == ""
    body = answer(client, "r1", "7 papers")
    assert body["kind"] == "question" and body["ack"] in chatflow.ACKS


def test_a_second_off_topic_reply_is_defaulted_without_an_acknowledgement(client):
    first(client)
    answer(client, "r1", "banana")
    body = answer(client, "r1", "lol")
    assert body["ack"] == "" and body["kind"] == "question"


def test_the_free_text_follow_up_path_is_the_same(client):
    body = first(client)
    for a in ["7 papers", "it is my own area", "abstract", "alone", "after I read it", "pdf"]:
        body = answer(client, "r1", a)
    assert body["field"] == "strength_criteria"
    assert answer(client, "r1", "banana")["ack"] == ""                       # off-topic: follow-up, no acknowledgement
    assert answer(client, "r1", "claims that the experiments back up")["ack"] in chatflow.ACKS


def test_a_409_has_no_acknowledgement_and_changes_nothing(client):
    r = client.post("/onboarding/fresh/answer", json={"text": "7 papers"})
    assert r.status_code == 409 and r.json()["ack"] == ""


def test_the_last_question_is_acknowledged_too_when_the_answer_was_real(client):
    body = first(client)
    answers = ["7 papers", "it is my own area", "abstract", "alone", "after I read it", "pdf",
               "claims that the experiments back up", "results reported without variance",
               "I over-weigh missing baselines", "deciding how much an ablation should count",
               "a review that points at specific sections", "a review that is vague and short"]
    for a in answers:
        body = answer(client, "r1", a)
    assert body["done"] is True and body["ack"] in chatflow.ACKS


def test_a_session_of_skips_ends_without_a_single_acknowledgement(client):
    body = first(client)
    acks = []
    while not body["done"]:
        body = answer(client, "r1", "idk")
        acks.append(body["ack"])
    assert acks and set(acks) == {""}


# ------------------------------------------------------------------ varied, and never evaluative

def test_consecutive_acknowledgements_differ(client):
    body = first(client)
    answers = ["7 papers", "it is my own area", "abstract", "alone", "after I read it", "pdf",
               "claims that the experiments back up", "results reported without variance",
               "I over-weigh missing baselines", "deciding how much an ablation should count",
               "a review that points at specific sections", "a review that is vague and short"]
    acks = []
    for a in answers:
        body = answer(client, "r1", a)
        acks.append(body["ack"])
    assert all(a in chatflow.ACKS for a in acks)
    assert all(x != y for x, y in zip(acks, acks[1:]))                      # never the same phrase twice in a row
    assert len(set(acks)) >= 4                                               # and a real variety


def test_the_pool_is_big_enough_to_vary():
    assert len(set(chatflow.ACKS)) == len(chatflow.ACKS) >= 5


@pytest.mark.parametrize("ack", chatflow.ACKS)
def test_no_acknowledgement_contains_evaluative_words(ack):
    assert not PRAISE.search(ack), ack
    assert not BANNED.search(ack) and not cc.OPINION.search(ack), ack
    assert cc.reply_errors(ack, {"reviewer_text": ""}) == []                 # it would pass the chat checks too


def test_acknowledgements_over_http_are_never_evaluative_whatever_was_answered(client):
    body = first(client)
    for a in ["7 papers", "it is my own area", "abstract", "alone", "after I read it", "pdf",
              "the baseline is weak and the writing is excellent", "great results are convincing",
              "I love novel work", "this is the best answer ever"]:
        body = answer(client, "r1", a)
        assert not PRAISE.search(body["ack"]) and not BANNED.search(body["ack"])
        assert a.lower() not in body["ack"].lower()


def test_the_acknowledgement_does_not_depend_on_how_good_the_answer_sounds(client):
    """The same plain pool is used for any answer that was understood: nothing is added or taken away by its content."""
    first(client)
    a = answer(client, "r1", "7 papers")["ack"]
    b = answer(client, "r1", "it is my own area, I publish in this subarea every year")["ack"]
    assert a in chatflow.ACKS and b in chatflow.ACKS and a != b
