"""Fix 2, under save-then-tell: a stated view is saved at once. Right after that, an affirming reply ("yes", "sure, add
it") changes nothing and never saves it twice; a reply that names another section moves it there; an explicit refusal
("don't add that") takes it out again; a question is just a question. All of it lasts one turn, like the old offer did.
(Before save-then-tell these tests drove a pending offer; the rules they guard are the same.)"""
import pytest

from app import store
from conftest import make_reviewer

SENTENCE = "The paper probes syntax in pretrained encoders using three datasets"
MESSAGE = f"My summary sentence: {SENTENCE}"


def post(c, message):
    r = c.post("/chat/p1", json={"reviewer_id": "rev", "message": message})
    assert r.status_code == 200, r.text
    return r.json()


def saved(chat_env, section="summary", later="Okay."):
    """SENTENCE saved under `section`; the model's reply to the next message is `later`."""
    c, set_model = chat_env
    make_reviewer("rev")
    set_model({"reply": "Got it.", "views": [{"text": SENTENCE, "section": section}]}, later)
    body = post(c, MESSAGE)
    assert fields() == [(SENTENCE, section)] and body["added"]["section"] == section
    return c


def fields():
    return [(n["text"], n["field"]) for n in store.notes("p1") if not n["removed"]]


@pytest.mark.parametrize("answer", [
    "yes", "Yes!", "yes lets add it", "Yes lets add it as my sentence", "sure, add it", "Sure, add it please",
    "go ahead", "yes please", "yeah add that", "ok go ahead and add it", "yes, add it to the paper summary",
])
def test_an_affirming_reply_after_the_save_never_saves_it_twice(chat_env, answer):
    c = saved(chat_env, later="Done.")
    body = post(c, answer)
    assert fields() == [(SENTENCE, "summary")], body["reply"]
    assert "Saved under" not in body["reply"] and "Added to" not in body["reply"]       # no second claim


@pytest.mark.parametrize("answer, section", [
    ("no i mean add the paper summary", "summary"),
    ("No, I mean strengths", "strengths"),
    ("actually put it under the weaknesses", "weaknesses"),
    ("yes, but put it under strengths", "strengths"),
    ("not there, add it to the comments", "comments"),
])
def test_naming_another_section_moves_the_note_there(chat_env, answer, section):
    c = saved(chat_env, section="weaknesses" if section != "weaknesses" else "strengths", later="Okay.")
    body = post(c, answer)
    assert fields() == [(SENTENCE, section)], body["reply"]
    assert body["reply"].startswith("Moved to") and body["added"]["section"] == section


@pytest.mark.parametrize("answer", ["no, don't add it", "don't add that"])
def test_an_explicit_refusal_takes_it_out_again(chat_env, answer):
    c = saved(chat_env, later="Okay.")
    body = post(c, answer)
    assert fields() == [] and body["reply"].startswith("Undone")


@pytest.mark.parametrize("answer", ["no", "nope", "no thanks"])
def test_a_bare_no_is_not_read_as_an_instruction_and_the_note_stays(chat_env, answer):
    c = saved(chat_env, later="Okay.")
    post(c, answer)
    assert fields() == [(SENTENCE, "summary")]


@pytest.mark.parametrize("message", ["yes but where does the paper describe the datasets?",
                                     "ok so what does Section 4 report?"])
def test_a_yes_that_leads_into_a_question_changes_nothing(chat_env, message):
    c = saved(chat_env, later="Section 4 reports accuracy.")
    body = post(c, message)
    assert fields() == [(SENTENCE, "summary")] and "Moved to" not in body["reply"]


def test_a_correction_only_counts_right_after_the_save(chat_env):
    c = saved(chat_env, later="Table 2 has the counts.")
    post(c, "where are the counts?")
    post(c, "No, I mean strengths")
    post(c, "don't add that")
    assert fields() == [(SENTENCE, "summary")]
