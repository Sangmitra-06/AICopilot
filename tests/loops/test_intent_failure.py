"""Loop 4: when the intent model failed, the message was classified as an 'answer'
and saved as a point in the reviewer's review. A failure must never write anything."""
import pytest

from app import chat

MSG = "Five participants per region seems low"


def boom(*a, **k):
    raise RuntimeError("model unavailable")


@pytest.mark.parametrize("reply", ["not json", '{"intent": "banana"}', '{"nope": 1}'])
def test_bad_model_output_is_not_saved_as_a_point(monkeypatch, reply):
    monkeypatch.setattr(chat, "_chat", lambda msgs: reply)
    out = chat.classify(MSG, "weaknesses", "", "ask")
    assert out["intent"] == "unread"
    assert out["via"] == "fallback"


def test_model_error_is_not_saved_as_a_point(monkeypatch):
    monkeypatch.setattr(chat, "_chat", boom)
    out = chat.classify(MSG, "weaknesses", "", "ask")
    assert out["intent"] == "unread"
    assert out["via"] == "fallback"


def test_a_question_mark_does_not_rescue_a_failed_read(monkeypatch):
    monkeypatch.setattr(chat, "_chat", boom)
    assert chat.classify("Is that five per region?", "weaknesses", "", "ask")["intent"] == "unread"


def test_rules_still_work_when_the_model_is_down(monkeypatch):
    monkeypatch.setattr(chat, "_chat", boom)
    assert chat.classify("idk", "weaknesses", "", "ask")["intent"] == "dontknow"
    assert chat.classify("nothing else", "weaknesses", "", "ask")["intent"] == "done"
    assert chat.classify("no", "weaknesses", "", "offer")["intent"] == "stay"


def test_a_working_model_still_returns_answers(monkeypatch):
    monkeypatch.setattr(chat, "_chat", lambda msgs: '{"intent": "answer", "goto": null}')
    out = chat.classify(MSG, "weaknesses", "", "ask")
    assert out["intent"] == "answer" and out["via"] == "model"
