"""Fix 2: while an offer is pending, any reply that affirms it counts as yes, even with extra words; a reply that
names another section re-targets the offer instead of dropping it; and in both cases the note is written."""
import pytest

from app import store
from conftest import make_reviewer

SENTENCE = "The paper probes syntax in pretrained encoders using three datasets"
MESSAGE = f"My summary sentence: {SENTENCE}"


def post(c, message):
    r = c.post("/chat/p1", json={"reviewer_id": "rev", "message": message})
    assert r.status_code == 200, r.text
    return r.json()


def offer(chat_env, section="summary", later="Okay."):
    """A pending offer for SENTENCE under `section`; the model's reply to the next message is `later`."""
    c, set_model = chat_env
    make_reviewer("rev")
    set_model({"reply": "Got it. Want me to add that to your draft?", "views": [{"text": SENTENCE, "section": section}]}, later)
    body = post(c, MESSAGE)
    assert body["capture"]["section"] == section and store.notes("p1") == []
    return c


def fields():
    return [(n["text"], n["field"]) for n in store.notes("p1") if not n["removed"]]


@pytest.mark.parametrize("answer", [
    "yes", "Yes!", "yes lets add it", "Yes lets add it as my sentence", "sure, add it", "Sure, add it please",
    "go ahead", "yes please", "yeah add that", "ok go ahead and add it", "yes, add it to the paper summary",
])
def test_any_reply_that_affirms_the_offer_writes_the_note(chat_env, answer):
    c = offer(chat_env, later="Done.")
    body = post(c, answer)
    assert fields() == [(SENTENCE, "summary")], body["reply"]
    assert body["resolved"] == {"outcome": "accepted", "text": SENTENCE} and body["draft_changed"] is True


@pytest.mark.parametrize("answer, section", [
    ("no i mean add the paper summary", "summary"),
    ("No, I mean strengths", "strengths"),
    ("actually put it under the weaknesses", "weaknesses"),
    ("yes, but put it under strengths", "strengths"),
    ("not there, add it to the comments", "comments"),
])
def test_naming_another_section_retargets_the_offer_and_writes_the_note(chat_env, answer, section):
    c = offer(chat_env, section="weaknesses" if section != "weaknesses" else "strengths", later="Okay.")
    body = post(c, answer)
    assert fields() == [(SENTENCE, section)], body["reply"]
    assert store.chat_state("p1")["views"]["v1"]["outcome"] == "accepted"


@pytest.mark.parametrize("answer", ["no", "nope", "no, don't add it", "no thanks", "don't add that"])
def test_a_refusal_writes_nothing(chat_env, answer):
    c = offer(chat_env, later="Okay.")
    body = post(c, answer)
    assert fields() == [] and body["resolved"]["outcome"] == "rejected"


@pytest.mark.parametrize("message", ["yes but where does the paper describe the datasets?",
                                     "ok so what does Section 4 report?"])
def test_a_yes_that_leads_into_a_question_is_not_taken_for_the_answer(chat_env, message):
    c = offer(chat_env, later="Section 4 reports accuracy.")
    body = post(c, message)
    assert fields() == [] and body["resolved"] is None


def test_the_offer_still_lasts_one_turn(chat_env):
    c = offer(chat_env, later="Table 2 has the counts.")
    post(c, "where are the counts?")
    assert post(c, "yes lets add it")["resolved"] is None and fields() == []
