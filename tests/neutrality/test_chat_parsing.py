"""Reading the model's output: tolerant of fences, surrounding text and plain prose, with the neutrality checks
applied to whatever is read, and an empty reply retried once before the fallback."""
import json
import logging

import pytest

from app import chat_checks as cc, chatflow, store
from conftest import make_reviewer

REPLY = "Table 2 reports accuracy on SST-2 and CoLA (Section 4)."
OBJ = {"reply": REPLY, "views": [{"text": "five participants per region seems low", "section": "weaknesses"}],
       "nudge_used": True}
TEXT = json.dumps(OBJ)


# ------------------------------------------------------------------ parse_reply

@pytest.mark.parametrize("raw,form", [
    (TEXT, "json"),
    ("```json\n" + TEXT + "\n```", "fenced"),
    ("```\n" + TEXT + "\n```", "fenced"),
    ("  ```JSON " + TEXT + " ``` ", "fenced"),
    ("Sure, here you go:\n" + TEXT + "\nLet me know if that helps.", "embedded"),
    ("Here is the answer. ```json\n" + TEXT + "\n``` Hope it helps.", "embedded"),
    ('Note {"a": 1} first. ' + TEXT, "embedded"),             # an object without "reply" is skipped
])
def test_json_in_any_wrapping_is_read_with_its_fields(raw, form):
    j, reply, got = chatflow.parse_reply(raw)
    assert (got, reply) == (form, REPLY)
    assert j["views"][0]["text"] == "five participants per region seems low" and j["nudge_used"] is True


def test_the_first_object_with_a_reply_wins():
    two = json.dumps({"reply": "first"}) + " and then " + json.dumps({"reply": "second"})
    assert chatflow.parse_reply(two)[1:] == ("first", "embedded")


@pytest.mark.parametrize("raw", [
    "Table 2 reports accuracy on SST-2 and CoLA.",
    "```\nTable 2 reports accuracy.\n```",
    "Here is a thought with {braces} but no JSON object.",
    'Use {"a": 1} for that; it is not an answer object.',
    '"Just a quoted sentence."',
])
def test_plain_prose_is_the_reply_and_every_other_field_is_empty(raw):
    j, reply, form = chatflow.parse_reply(raw)
    assert form == "prose" and j == {} and reply and "```" not in reply


def test_prose_in_a_fence_loses_the_fence():
    assert chatflow.parse_reply("```\nTable 2 reports accuracy.\n```")[1] == "Table 2 reports accuracy."


@pytest.mark.parametrize("raw", [None, "", "   \n ", '{"reply": ""}', '{"reply": null, "views": []}',
                                 '{"views": []}', '{"reply": "cut off in the mid', "[1, 2]", "{not json}",
                                 "```json\n{\"reply\": \n```", 42])
def test_nothing_usable_is_empty(raw):
    j, reply, form = chatflow.parse_reply(raw)
    assert (j, reply, form) == ({}, "", "empty")


# ------------------------------------------------------------------ end to end

def post(c, message, rid="rev"):
    r = c.post("/chat/p1", json={"reviewer_id": rid, "message": message})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def env(chat_env):
    c, set_model = chat_env
    make_reviewer("rev")
    return c, set_model


def forms():
    return [e["payload"].get("form") for e in store.events("p1") if e["type"] == "chat_check"]


def test_fenced_json_works_like_plain_json_including_capture(env):
    c, set_model = env
    set_model("```json\n" + json.dumps({"reply": "Noted. Want me to add that to the Weaknesses section?",
              "views": [{"text": "five participants per region seems low", "section": "weaknesses"}]}) + "\n```")
    body = post(c, "I think five participants per region seems low")
    assert body["checks"] == {"attempts": 1, "fallback": False} and body["added"]["section"] == "weaknesses"
    assert forms() == ["fenced"]


def test_json_with_surrounding_prose_works(env):
    c, set_model = env
    set_model("Of course!\n" + json.dumps({"reply": REPLY}) + "\nAnything else?")
    body = post(c, "which datasets do they use?")
    assert body["reply"] == REPLY and body["checks"]["attempts"] == 1 and forms() == ["embedded"]


def test_plain_prose_is_shown_and_its_fields_are_empty(env):
    c, set_model = env
    set_model("Table 2 reports accuracy on SST-2 and CoLA (Section 4).")
    body = post(c, "which datasets do they use?")
    assert body["reply"] == "Table 2 reports accuracy on SST-2 and CoLA (Section 4)."
    assert body["checks"] == {"attempts": 1, "fallback": False} and forms() == ["prose"]


def test_prose_cannot_capture_or_reword_but_can_carry_a_nudge(env):
    c, set_model = env
    set_model("Noted. Want me to add that to the Weaknesses section? Your draft has nothing under Paper summary yet.")
    body = post(c, "ok")
    assert body["capture"] is None and body["reword"] is None            # these need the structured fields
    assert store.chat_state("p1")["views"] == {}
    # A nudge does not: a directive was given and the reply addresses the section (nudge_used is optional).
    assert body["nudge"] == {"section": "summary", "label": "Paper summary", "kind": "empty"}


# Plain prose gets exactly the same neutrality checks as JSON.
LEAKY_PROSE = ["This paper is novel and the results are convincing.", "I agree with you; the baseline is weak.",
               "The comparison is fair.", "You're right about that.", "I would accept it.",
               "Table 2 has the numbers. Back to Weaknesses?"]


@pytest.mark.parametrize("prose", LEAKY_PROSE)
def test_prose_containing_an_opinion_is_still_blocked(env, prose):
    c, set_model = env
    model = set_model(prose)
    body = post(c, "which baselines do they use?")
    assert body["checks"] == {"attempts": 2, "fallback": True} and prose not in body["reply"]
    assert body["reply"] == chatflow.FALLBACK and len(model.calls) == 2


def test_prose_that_leaks_on_a_judgment_question_gets_the_decline_fallback(env):
    c, set_model = env
    set_model("Yes, it is novel.")
    body = post(c, "is this novel?")
    assert body["checks"]["fallback"] is True and body["reply"].startswith("That's a judgment call")


def test_prose_that_declines_properly_is_accepted(env):
    c, set_model = env
    set_model("That's your call to make, not mine. Table 2 is where the numbers are (Section 4).")
    body = post(c, "is this novel?")
    assert body["checks"] == {"attempts": 1, "fallback": False}


def test_prose_is_regenerated_once_like_any_other_reply(env):
    c, set_model = env
    set_model("The baseline is weak.", REPLY)
    body = post(c, "which baselines do they use?")
    assert body["reply"] == REPLY and body["checks"]["attempts"] == 2 and forms() == ["prose"]


# ------------------------------------------------------------------ an empty reply is retried once, then the fallback

@pytest.mark.parametrize("empty", ["", "   ", '{"reply": ""}', '{"views": []}', '{"reply": "cut off'])
def test_an_empty_reply_is_retried_once_with_a_format_instruction(env, empty):
    c, set_model = env
    model = set_model(empty, {"reply": REPLY})
    body = post(c, "which datasets do they use?")
    assert body["reply"] == REPLY and body["checks"] == {"attempts": 2, "fallback": False}
    last = model.calls[1][-1]
    assert last["role"] == "user" and last["content"] == chatflow.BAD_FORMAT
    assert "required format" in last["content"] and "Problems with the last one" not in last["content"]


def test_two_empty_replies_give_the_fallback_after_exactly_one_retry(env):
    c, set_model = env
    model = set_model("")
    body = post(c, "which datasets do they use?")
    assert body["reply"] == chatflow.FALLBACK and body["checks"] == {"attempts": 2, "fallback": True}
    assert len(model.calls) == 2


def test_a_model_that_returns_nothing_at_all_or_raises_is_retried_once(env, monkeypatch):
    c, _ = env
    answers = iter([None, RuntimeError("down"), json.dumps({"reply": REPLY})])
    calls = []

    def fake(msgs):
        calls.append(msgs)
        a = next(answers)
        if isinstance(a, Exception):
            raise a
        return a
    monkeypatch.setattr(chatflow, "_chat", fake)
    body = post(c, "which datasets do they use?")           # None -> retried -> raises -> fallback (2 attempts only)
    assert body["checks"] == {"attempts": 2, "fallback": True} and len(calls) == 2
    body = post(c, "and the metrics?")                       # next call gets the good answer
    assert body["reply"] == REPLY


def test_an_empty_first_reply_does_not_use_up_the_neutrality_retry_unfairly(env):
    """Empty then a rule-breaking reply: the one retry is spent, so the second failure is the fallback."""
    c, set_model = env
    set_model("", "This paper is novel.")
    body = post(c, "which datasets do they use?")
    assert body["checks"] == {"attempts": 2, "fallback": True} and body["reply"] == chatflow.FALLBACK


# ------------------------------------------------------------------ logging what came back

def test_a_reply_that_is_not_plain_json_is_logged_truncated_to_500_chars(env, caplog):
    c, set_model = env
    long_prose = "Table 2 reports accuracy on SST-2 and CoLA. " * 40            # about 1,760 characters
    set_model(long_prose)
    with caplog.at_level(logging.WARNING, logger="copilot.chat"):
        post(c, "which datasets do they use?")
    [rec] = [r for r in caplog.records if "not plain JSON" in r.getMessage()]
    msg = rec.getMessage()
    assert "read as prose" in msg and long_prose[:500] in msg and long_prose[:501] not in msg


def test_an_empty_reply_is_logged_too(env, caplog):
    c, set_model = env
    set_model("", {"reply": REPLY})
    with caplog.at_level(logging.WARNING, logger="copilot.chat"):
        post(c, "which datasets do they use?")
    assert any("read as empty" in r.getMessage() and "raw[:500] = ''" in r.getMessage() for r in caplog.records)


def test_plain_json_is_not_logged_as_a_problem(env, caplog):
    c, set_model = env
    set_model({"reply": REPLY})
    with caplog.at_level(logging.WARNING, logger="copilot.chat"):
        post(c, "which datasets do they use?")
    assert not [r for r in caplog.records if "not plain JSON" in r.getMessage()]
