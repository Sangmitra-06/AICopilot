"""Loop 5: the assistant could ask the same question again and again. Nothing compared a
new question with earlier ones, the opening question was cached per part, and the
canned fallback was one fixed string."""
import json

import pytest

from app import criterion, guide
from app.verify import BANNED

C = {"id": "weaknesses", "name": "Summary of weaknesses", "tab": "Weaknesses", "style": "judge",
     "definition": "Reasons the paper should not be accepted.", "has_definition": True, "type": "text"}
Q1 = "What concerns, in your own words, would you want to raise?"
Q2 = "Which part of your reading led you to that concern?"
OK = '{"leading": false, "new_topic": false, "reason": ""}'


@pytest.fixture(autouse=True)
def one_part(monkeypatch):
    criterion.OPEN_CACHE.clear()
    monkeypatch.setattr(criterion.criteria, "by_id", lambda: {"weaknesses": C})


def model_says(monkeypatch, *questions):
    """The question writer returns these in order (the last repeats); the judge always passes."""
    it = iter(questions)
    last = {"q": questions[-1]}

    def fake(msgs):
        if msgs[0]["content"] == criterion.PROMPT_SYS:
            last["q"] = next(it, last["q"])
            return json.dumps({"question": last["q"]})
        return OK
    monkeypatch.setattr(criterion, "_chat", fake)


def model_down(monkeypatch):
    def boom(msgs):
        raise RuntimeError("model unavailable")
    monkeypatch.setattr(criterion, "_chat", boom)


def ask(kind, history=(), **kw):
    return criterion.next_question("weaknesses", "", list(history), kind, **kw)


def hist(*qs):
    return [{"q": q, "a": ""} for q in qs]


def test_a_repeated_question_from_the_model_is_rejected_and_rewritten(monkeypatch):
    model_says(monkeypatch, Q1, Q2)
    out = ask("angle", hist(Q1))
    assert out["question"] == Q2


def test_a_near_duplicate_is_also_a_repeat(monkeypatch):
    model_says(monkeypatch, "What concerns, in your own words, would you want to raise here?", Q2)
    assert ask("angle", hist(Q1))["question"] == Q2


def test_a_model_that_only_repeats_never_returns_the_same_question(monkeypatch):
    model_says(monkeypatch, Q1)
    out = ask("angle", hist(Q1))
    assert out["question"] != Q1


def test_the_cached_opening_question_is_not_served_twice(monkeypatch):
    model_says(monkeypatch, Q1, Q2)
    first = ask("open")
    assert first["question"] == Q1
    again = ask("open", hist(first["question"]))
    assert again["question"] != Q1


def test_fallbacks_do_not_repeat_and_eventually_stop(monkeypatch):
    model_down(monkeypatch)
    seen = []
    for _ in range(8):
        out = ask("angle", hist(*seen))
        if out.get("done"):
            break
        assert out["question"] not in seen, seen
        seen.append(out["question"])
    else:
        pytest.fail(f"never stopped asking: {seen}")
    assert out["question"] == "" and out["source"] == "exhausted"
    assert len(seen) >= 2


def test_questions_asked_earlier_in_the_session_count(monkeypatch):
    model_says(monkeypatch, Q1, Q2)
    assert ask("angle", [], asked=[Q1])["question"] == Q2


@pytest.mark.parametrize("kind", ["open", "nudge", "angle"])
@pytest.mark.parametrize("style", ["judge", "describe"])
def test_every_fallback_is_open_and_neutral(monkeypatch, kind, style):
    model_down(monkeypatch)
    monkeypatch.setitem(C, "style", style)
    seen = []
    for _ in range(8):
        out = ask(kind, hist("(an earlier question)", *seen) if kind == "nudge" else hist(*seen))
        if out.get("done"):
            break
        q = out["question"]
        assert not guide.rule_errors(q, "", ""), q
        assert not BANNED.search(q), q
        seen.append(q)
    assert seen


def test_asked_questions_come_from_the_event_log(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # store.py opens copilot.db relative to the working directory
    import importlib
    store = importlib.reload(importlib.import_module("app.store"))
    store.log("p1", "question_asked", {"criterion": "weaknesses", "kind": "open", "question": Q1})
    store.log("p1", "question_asked", {"criterion": "strengths", "kind": "open", "question": Q2})
    store.log("p1", "question_asked", {"criterion": "weaknesses", "kind": "explain", "question": ""})
    store.log("p2", "question_asked", {"criterion": "weaknesses", "kind": "open", "question": Q2})
    assert store.asked_questions("p1", "weaknesses") == [Q1]
