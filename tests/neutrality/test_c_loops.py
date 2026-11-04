"""Group (c): a reviewer who keeps answering "idk" or "no" must not trap the flow.
Either the flow terminates, or every turn moves it forward. Nothing is saved as a note."""
import json

import pytest

from app import chat, criterion
from ui_driver import TERMINAL, repeat_reply

IDK = ["idk", "I don't know", "not sure", "dunno", "no idea", "IDK."]
NOS = ["no", "No.", "nope", "nah", "not really"]
STAGES = ["ask", "confirm", "offer", "stayed", "draft", "score", "free"]


@pytest.fixture(autouse=True)
def model_must_not_run(monkeypatch):
    def boom(msgs):
        raise AssertionError("bare idk/no must be resolved by rule, without the model")
    monkeypatch.setattr(chat, "_chat", boom)


@pytest.mark.parametrize("text", IDK)
@pytest.mark.parametrize("stage", STAGES)
def test_idk_is_never_saved_as_an_answer_and_is_stable(text, stage):
    seq = {chat.classify(text, "weaknesses", "", stage)["intent"] for _ in range(6)}
    assert seq == {"dontknow"}  # same result every time; never "answer"


@pytest.mark.parametrize("text", NOS)
@pytest.mark.parametrize("start", STAGES)
def test_repeated_no_terminates_or_stops_asking(text, start):
    seq = repeat_reply(chat.classify, text, start, turns=10)
    ended = seq[-1][0] in TERMINAL
    assert ended or not any(asked for _, asked in seq[-3:]), seq


@pytest.mark.parametrize("text", NOS)
def test_no_is_never_saved_as_an_answer(text):
    for stage in STAGES:
        assert chat.classify(text, "weaknesses", "", stage)["intent"] != "answer"


C = {"id": "weaknesses", "name": "Summary of weaknesses", "tab": "Weaknesses", "style": "judge",
     "definition": "Reasons the paper should not be accepted.", "has_definition": True, "type": "text"}


@pytest.mark.parametrize("answer", ["idk", "no"])
@pytest.mark.parametrize("model", ["down", "stuck_on_one_question"])
@pytest.mark.parametrize("kind", ["nudge", "angle"])
def test_question_flow_ends_when_every_answer_is_idk_or_no(monkeypatch, answer, model, kind):
    criterion.OPEN_CACHE.clear()
    monkeypatch.setattr(criterion.criteria, "by_id", lambda: {"weaknesses": C})
    stuck = "What concerns, in your own words, would you want to raise?"

    def fake(msgs):
        if model == "down":
            raise RuntimeError("model unavailable")
        if msgs[0]["content"] == criterion.PROMPT_SYS:
            return json.dumps({"question": stuck})
        return '{"leading": false, "new_topic": false, "reason": ""}'
    monkeypatch.setattr(criterion, "_chat", fake)

    history, asked = [], []
    for turn in range(15):
        out = criterion.next_question("weaknesses", "", history, kind, asked)
        if out.get("done"):
            break
        q = out["question"]
        assert not criterion.is_repeat(q, asked), f"turn {turn}: repeated {q!r}"
        asked.append(q)
        history.append({"q": q, "a": answer})
    else:
        pytest.fail(f"never terminated: {asked}")
    assert out["source"] == "exhausted"
