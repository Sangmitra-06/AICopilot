"""Fix 1: a reply holds at most one offer to add something to the draft, and when the app records an offer the
wording is the app's, never the model's."""
import re

import pytest

from app import store
from conftest import make_reviewer

SENTENCE = "The paper probes syntax in pretrained encoders using three datasets"
MESSAGE = f"My summary sentence: {SENTENCE}"
EXTRACT = f"VIEW | summary | {SENTENCE}"
APP_OFFER = "Want me to add that to Paper summary?"
OFFER_SENTENCE = re.compile(r"(?i)\b(?:want me to add|i can add|would you like me to add)\b")


def post(c, message):
    r = c.post("/chat/p1", json={"reviewer_id": "rev", "message": message})
    assert r.status_code == 200, r.text
    return r.json()


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
def test_prose_reply_with_a_model_offer_gets_only_the_apps_offer(env, model_offer):
    c, set_model = env
    set_model(f"That reads as a description of the paper. {model_offer}", EXTRACT)
    body = post(c, MESSAGE)
    assert len(OFFER_SENTENCE.findall(body["reply"])) == 1, body["reply"]
    assert body["reply"].endswith(APP_OFFER) and "as written" not in body["reply"]
    assert body["capture"]["section"] == "summary"


def test_json_reply_with_a_model_offer_and_views_gets_only_the_apps_offer(env):
    c, set_model = env
    set_model({"reply": "Got it. Want me to add your sentence to Paper summary as written?",
               "views": [{"text": SENTENCE, "section": "summary"}]})
    body = post(c, MESSAGE)
    assert len(OFFER_SENTENCE.findall(body["reply"])) == 1, body["reply"]
    assert body["reply"] == f"Got it.\n\n{APP_OFFER}"
    assert store.thread("p1")[-1]["meta"]["offer"] == "v1"


def test_a_reply_that_was_only_the_model_offer_becomes_only_the_apps_offer(env):
    c, set_model = env
    set_model({"reply": "Want me to add your sentence to Paper summary?",
               "views": [{"text": SENTENCE, "section": "summary"}]})
    assert post(c, MESSAGE)["reply"] == APP_OFFER
