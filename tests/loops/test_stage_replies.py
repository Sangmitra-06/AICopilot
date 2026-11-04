"""Loop 1: a bare "no" meant different things at different stages, and the UI
bounced between 'offer' and 'ask' for as long as the reviewer kept typing "no"."""
import pytest

from app import chat
from ui_driver import TERMINAL, repeat_reply


def intent(text, stage):
    return chat.classify(text, "weaknesses", "", stage)["intent"]


def test_bare_no_is_resolved_per_stage():
    assert intent("no", "confirm") != intent("no", "offer")


@pytest.mark.parametrize("text,stage,expected", [
    ("yes", "confirm", "add_more"),
    ("no", "confirm", "nothing_to_add"),
    ("yes", "offer", "move_on"),
    ("no", "offer", "stay"),
    ("no", "ask", "nothing_to_add"),
    ("yes", "draft", "draft_now"),
])
def test_bare_replies_by_stage(text, stage, expected):
    assert intent(text, stage) == expected


@pytest.mark.parametrize("text,stage", [
    ("yes", "ask"), ("no", "draft"), ("yes", "stayed"), ("no", "stayed"),
    ("yes", "score"), ("no", "score"), ("no", "free"),
])
def test_bare_reply_that_answers_nothing_is_unclear(text, stage):
    assert intent(text, stage) == "unclear"


@pytest.mark.parametrize("start", ["confirm", "offer", "ask"])
def test_repeating_no_stops_asking(start):
    seq = repeat_reply(chat.classify, "no", start, turns=8)
    last = seq[-3:]
    ended = seq[-1][0] in TERMINAL
    assert ended or not any(asked for _, asked in last), seq
