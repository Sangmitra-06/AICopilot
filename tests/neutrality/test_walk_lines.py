"""Walk lines refer back to onboarding in a natural sentence (fix item 3).

The real session: reading_order "I start with intro then I like to get into methods and results"; after the intro, "next"
said "Moving to the methods, as you said." It should read like "You said you like to read the intro first and then the
methods, so let's go to the methods now." "again" only for a section the reviewer has already seen.
"""
import re

import pytest

from app import main, store, walk
from app.verify import BANNED
from conftest import make_reviewer
from test_walk_section_match import SESSION_LAYOUT, SESSION_READING, spans_for

INTRO_DESC = "The authors open by describing the problem [p2-s1]."


@pytest.fixture
def env(chat_env, monkeypatch):
    c, set_model = chat_env
    monkeypatch.setitem(main.CACHE, "p1", spans_for(SESSION_LAYOUT))
    set_model({"reply": "plain words"})          # descriptions fail their pointer check: the app's line carries the pointer
    make_reviewer("rev", reading_order=SESSION_READING, reading_order__value="intro_first")
    assert c.post("/chat/p1/open", json={"reviewer_id": "rev"}).json()["opened"]
    return c


def say(c, message):
    r = c.post("/chat/p1", json={"reviewer_id": "rev", "message": message})
    assert r.status_code == 200, r.text
    return r.json()["reply"]


def first_line(reply):
    return re.sub(r"\s*\((?:Section|Abstract)[^)]*\)", "", reply.split("\n\n")[0])


def test_the_session_next_after_the_intro_refers_back_to_what_they_said(env):
    assert first_line(say(env, "next")) == \
        "You said you like to read the intro first and then the methods, so let's go to the methods now."


def test_the_next_named_section_refers_back_too_without_first(env):
    say(env, "next")
    assert first_line(say(env, "next")) == \
        "You said you like to read the methods and then the results, so let's go to the results now."


def test_a_section_they_did_not_name_claims_nothing(env):
    say(env, "next"); say(env, "next")
    line = first_line(say(env, "next"))
    assert line == "Moving to the abstract." and "you said" not in line.lower()


def test_no_again_on_a_first_visit(env):
    lines = [first_line(say(env, m)) for m in ("next", "next", "go to the discussion", "next")]
    assert not any(re.search(r"\bagain\b", l, re.I) for l in lines), lines


def test_again_only_when_going_back_to_a_section_already_seen(env):
    say(env, "next")
    assert first_line(say(env, "go to the intro")) == "Let's look at the intro again, as you asked."


def test_the_lines_say_nothing_about_the_paper(env):
    for m in ("next", "next", "next", "go to the intro"):
        line = first_line(say(env, m))
        assert not walk.rates(line) and not BANNED.search(line), line


def test_two_sections_for_the_same_word_do_not_repeat_it():
    order = [{"section": "1 Introduction", "said": "intro"}, {"section": "2 Approach", "said": "methods"},
             {"section": "3 Experimental setup", "said": "methods"}]
    assert walk.move_lead(order[2], order=order) == \
        "Still on the methods you mentioned, let's go to the experimental setup now"
