"""Fix 1, under save-then-tell: a reply holds at most one line about the draft, and it is the app's, never the model's.
A statement is saved at once; every offer or claim the model wrote is removed and the app's "Saved under ..." line is the
only one."""
import re

import pytest

from app import store
from conftest import make_reviewer

SENTENCE = "The paper probes syntax in pretrained encoders using three datasets"
MESSAGE = f"My summary sentence: {SENTENCE}"
EXTRACT = f"VIEW | summary | {SENTENCE}"
APP_LINE = "Saved under Paper summary. Say “move it” if that's wrong."
DRAFT_LINE = re.compile(r"(?i)\b(?:want me to add|i can add|would you like me to add|saved under|added to)\b")


def post(c, message):
    r = c.post("/chat/p1", json={"reviewer_id": "rev", "message": message})
    assert r.status_code == 200, r.text
    return r.json()


def fields():
    return [(n["text"], n["field"]) for n in store.notes("p1")]


@pytest.fixture
def env(chat_env):
    c, set_model = chat_env
    make_reviewer("rev")
    return c, set_model


@pytest.mark.parametrize("model_offer", [
    "Want me to add your sentence to Paper summary as written?",
    "I can add this to Paper summary in your words.",
    "Would you like me to add your summary sentence to the Paper summary section?",
])
def test_prose_reply_with_a_model_offer_gets_only_the_apps_line(env, model_offer):
    c, set_model = env
    set_model(f"That reads as a description of the paper. {model_offer}", EXTRACT)
    body = post(c, MESSAGE)
    assert len(DRAFT_LINE.findall(body["reply"])) == 1, body["reply"]
    assert body["reply"].endswith(APP_LINE) and "as written" not in body["reply"]
    assert fields() == [(SENTENCE, "summary")]


def test_json_reply_with_a_model_offer_and_views_gets_only_the_apps_line(env):
    c, set_model = env
    set_model({"reply": "Got it. Want me to add your sentence to Paper summary as written?",
               "views": [{"text": SENTENCE, "section": "summary"}]})
    body = post(c, MESSAGE)
    assert len(DRAFT_LINE.findall(body["reply"])) == 1, body["reply"]
    assert body["reply"] == f"Got it.\n\n{APP_LINE}"
    assert store.thread("p1")[-1]["meta"]["saved"] == [store.notes("p1")[0]["id"]]


def test_a_reply_that_was_only_the_model_offer_becomes_only_the_apps_line(env):
    c, set_model = env
    set_model({"reply": "Want me to add your sentence to Paper summary?",
               "views": [{"text": SENTENCE, "section": "summary"}]})
    assert post(c, MESSAGE)["reply"] == APP_LINE


def test_a_model_claim_plus_the_apps_line_is_still_one_line(env):
    c, set_model = env
    set_model({"reply": "Added to Paper summary, in your own words. Saved under Strengths.",
               "views": [{"text": SENTENCE, "section": "summary"}]})
    body = post(c, MESSAGE)
    assert body["reply"] == APP_LINE and len(DRAFT_LINE.findall(body["reply"])) == 1
