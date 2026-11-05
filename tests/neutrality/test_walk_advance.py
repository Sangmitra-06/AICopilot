"""Item 3: advancing through the reading order. A per-paper pointer into the order; "ok"/"next"/"got it"/"move on" (or a
finished captured point) moves to the next section ("You said you like to read the intro first and then the methods, so let's go to the methods now") and cites its spans; a covered
section is never revisited unless asked; the end of the order offers the open review-form sections; "go to results"
jumps and resets the pointer; "stop guiding" stops for good. All of it is app-written, none of it judges the paper.
"""
import re

import pytest

from app import chat_checks as cc, main, store, walk
from app.verify import BANNED
from conftest import asked, make_reviewer

SECTIONS = ["Abstract", "1 Introduction", "2 Related Work", "3 Method", "4 Experiments", "5 Results", "6 Conclusion"]


def rich(sections=SECTIONS):
    out = []
    for k, sec in enumerate(sections):
        for i in range(1, 3):
            out.append({"id": f"p{k + 1}-s{i}", "text": f"text of {sec} {i}", "page": k + 1, "lines": [i, i],
                        "section": sec, "kind": "body", "bbox": [10, 10 * i, 100, 10 * i + 8], "segs": [(20, i)]})
    out.append({"id": "p9-s1", "text": "Smith 2019.", "page": 9, "lines": [1, 1], "section": "References",
                "kind": "body", "bbox": [1, 1, 2, 2], "segs": [(10, 1)]})
    return out


@pytest.fixture
def env(chat_env, monkeypatch):
    c, set_model = chat_env
    monkeypatch.setitem(main.CACHE, "p1", rich())
    return c, set_model


def start(c, said="I start with the intro and then go to methods, then experiments.", **more):
    make_reviewer("rev", reading_order=said, reading_order__value="intro_first", **more)
    r = c.post("/chat/p1/open", json={"reviewer_id": "rev"})
    assert r.status_code == 200 and r.json()["opened"] is True
    return r.json()


def say(c, message):
    r = c.post("/chat/p1", json={"reviewer_id": "rev", "message": message})
    assert r.status_code == 200, r.text
    return r.json()


def sections_cited(body):
    return {x["section"] for x in body["cites"]}


def pointer():
    return store.walk_state("p1")["pointer"]


OFFERING = "Noted. Want me to add that to your draft under the weaknesses?"
ORDER = ["1 Introduction", "3 Method", "4 Experiments", "Abstract", "2 Related Work", "5 Results", "6 Conclusion"]


def test_the_order_the_opening_fixed_is_what_the_walk_follows(env):
    c, _ = env
    start(c)
    assert [e["section"] for e in store.walk_state("p1")["order"]] == ORDER
    assert pointer() == 0


@pytest.mark.parametrize("signal", ["ok", "OK", "okay", "next", "Next.", "got it", "Got it!", "move on", "Move on please",
                                    "ok, next", "done", "continue", "alright"])
def test_a_done_signal_moves_to_the_next_section_in_the_reviewers_words_and_cites_it(env, signal):
    c, set_model = env
    start(c)
    model = set_model({"reply": "should not be asked"})
    body = say(c, signal)
    assert body["reply"].startswith("You said you like to read the intro first and then the methods, so let's go to the methods now") and "(Section 3)" in body["reply"]
    assert sections_cited(body) == {"3 Method"} and body["cites"][0]["page"] == 4
    assert body["parts"] and any(p["cite"] for p in body["parts"])
    assert asked(model) == [] and pointer() == 1
    assert body["checks"] == {"attempts": 0, "fallback": False}


def test_the_exact_wording_for_the_first_move(env):
    c, _ = env
    start(c, "I start with the intro and then go to methods.")
    assert say(c, "ok")["reply"].startswith("You said you like to read the intro first and then the methods, so let's go to the methods now")


def test_sections_the_reviewer_did_not_name_are_not_claimed_as_theirs(env):
    c, _ = env
    start(c, "I start with the intro and then go to methods.")
    say(c, "next")                                                                # -> methods (named)
    body = say(c, "next")                                                         # -> the abstract (paper order fill)
    assert body["reply"].startswith("Moving to the abstract") and "as you said" not in body["reply"]
    assert sections_cited(body) == {"Abstract"}


def test_every_section_is_walked_once_and_the_end_offers_the_open_review_sections(env):
    c, set_model = env
    start(c)
    seen = [store.walk_state("p1")["covered"][0]]
    for _ in range(len(ORDER) - 1):
        body = say(c, "next")
        assert len(sections_cited(body)) == 1
        seen.append(next(iter(sections_cited(body))))
    assert seen == ORDER                                                          # in order, none twice
    model = set_model({"reply": "A normal answer."})
    end = say(c, "next")
    assert end["reply"].startswith("That was the last section in your order.")
    assert end["cites"] == [] and end["gaps"] is not None
    assert end["gaps"]["required_open"] or end["gaps"]["optional_open"]          # the open review-form sections
    assert "nothing in it yet" in end["reply"]
    assert asked(model) == [] and store.walk_state("p1")["done"] is True
    again = say(c, "ok")                                                          # the walk is over: ordinary chat again
    assert again["reply"] == "A normal answer." and len(model.calls) == 1


def test_a_covered_section_is_not_revisited_after_a_jump_either(env):
    c, _ = env
    start(c)
    say(c, "next")                                                                # method
    say(c, "next")                                                                # experiments
    say(c, "go back to the intro")                                                # asked for: allowed, and says so
    assert pointer() == 0
    body = say(c, "next")
    assert sections_cited(body) == {"Abstract"}                                   # method and experiments were shown: skipped
    covered = store.walk_state("p1")["covered"]
    assert len(covered) == len(set(covered))


@pytest.mark.parametrize("message,section,word", [
    ("go to results", "5 Results", "results"),
    ("Jump to the experiments", "4 Experiments", "experiments"),
    ("let's look at the related work", "2 Related Work", "related work"),
    ("take me to section 6", "6 Conclusion", "section 6"),
    ("go straight to the conclusion please", "6 Conclusion", "conclusion"),
    ("show me the abstract", "Abstract", "abstract"),
])
def test_a_jump_goes_there_resets_the_pointer_and_cites_the_section(env, message, section, word):
    c, set_model = env
    start(c)
    model = set_model({"reply": "should not be asked"})
    body = say(c, message)
    assert body["reply"].startswith("Going to ") and "as you asked" in body["reply"]
    assert sections_cited(body) == {section} and asked(model) == []
    order = [e["section"] for e in store.walk_state("p1")["order"]]
    assert pointer() == order.index(section)                                      # the pointer is where they went


def test_after_a_jump_next_continues_from_there(env):
    c, _ = env
    start(c)
    say(c, "go to results")
    body = say(c, "next")
    assert sections_cited(body) == {"6 Conclusion"}
    assert say(c, "next")["reply"].startswith("That was the last section")


@pytest.mark.parametrize("message", [
    "go to the results and tell me whether they hold up", "show me where they report accuracy",
    "can you go to results? I want to know if they are convincing", "show me my draft", "read my draft back",
    "go to the weaknesses part of my review"])
def test_a_request_that_is_more_than_a_jump_is_left_to_the_ordinary_chat(env, message):
    c, set_model = env
    start(c)
    model = set_model({"reply": "Table 2 is in the results (Section 4)."})
    body = say(c, message)
    assert not body["reply"].startswith("Going to") and store.walk_state("p1")["pointer"] == 0


@pytest.mark.parametrize("message", ["stop guiding", "Stop guiding me", "please stop the walkthrough", "no more guiding",
                                     "don't guide me", "I'll take it from here", "stop walking me through it"])
def test_stop_guiding_stops_and_the_walk_never_resumes(env, message):
    c, set_model = env
    start(c)
    model = set_model({"reply": "Fine."})
    body = say(c, message)
    assert "stop guiding" in body["reply"].lower() or "stopped" in body["reply"].lower()
    assert body["cites"] == [] and asked(model) == [] and store.walk_state("p1")["stopped"] is True
    after = say(c, "ok")                                                          # no more walking: ordinary chat
    assert not after["reply"].startswith(("Moving", "On to", "Next,")) and len(model.calls) == 1
    again = say(c, "next")
    assert not again["reply"].startswith(("Moving", "On to", "Next,")) and again["cites"] == []
    jump = say(c, "go to results")                                                # a jump is a question for the chat now
    assert not jump["reply"].startswith("Going to")
    assert pointer() == 0 and len(store.walk_state("p1")["covered"]) == 1


def test_without_a_stop_a_promised_section_would_be_nudged(env):
    c, set_model = env
    make_reviewer("rev")                                                          # control: no walk, same promise
    store.log("p1", "section_promised", {"section": "summary"})
    model = set_model({"reply": "Okay."})
    say(c, "ok")
    assert "NUDGE (optional)" in model.system


def test_after_stopping_the_app_adds_no_nudges(env):
    c, set_model = env
    start(c)
    say(c, "stop guiding")
    store.log("p1", "section_promised", {"section": "summary"})
    model = set_model({"reply": "Okay.", "nudge_used": True})
    say(c, "ok")
    assert len(model.calls) == 1 and "NUDGE (optional)" not in model.system


def test_before_the_opening_or_with_no_walk_ok_is_ordinary_chat(env):
    c, set_model = env
    make_reviewer("rev")
    model = set_model({"reply": "Okay."})
    body = say(c, "ok")                                                           # /open was never called
    assert body["reply"] == "Okay." and len(model.calls) == 1


def test_a_saved_point_stays_on_the_section_and_next_moves_on(env):
    # Save-then-tell: the statement itself is saved, so there is no confirmation turn to move on after. The reviewer may
    # have more to say about this section; "next" moves on, as anywhere in the walk.
    c, set_model = env
    start(c)
    set_model({"reply": OFFERING, "views": [{"text": "The ablation study is missing", "section": "weaknesses"}]})
    saved = say(c, "The ablation study is missing")
    assert saved["added"] and saved["reply"].endswith("Saved under Summary of weaknesses. Say “move it” if that's wrong.")
    assert "go to the methods" not in saved["reply"] and pointer() == 0
    body = say(c, "next")
    assert body["reply"].startswith("You said you like to read the intro first and then the methods, so let's go to the methods now")
    assert sections_cited(body) == {"3 Method"} and pointer() == 1
    assert any(p["cite"] for p in body["parts"]) and "".join(p["text"] for p in body["parts"]) == body["reply"]


def test_a_refused_save_does_not_move_on(env):
    c, set_model = env
    start(c)
    set_model({"reply": OFFERING, "views": [{"text": "The ablation study is missing", "section": "weaknesses"}]})
    say(c, "The ablation study is missing")
    set_model({"reply": "Okay."})
    body = say(c, "don't add that")
    assert "go to the methods" not in body["reply"] and pointer() == 0 and store.notes("p1") == []


def test_ordinary_chat_during_the_walk_does_not_move_the_pointer(env):
    c, set_model = env
    start(c)
    set_model({"reply": "The authors define it in Section 3 [p4-s1]."})
    body = say(c, "what does the method section call its main component?")
    assert pointer() == 0 and "Moving" not in body["reply"]


def test_a_walk_turn_is_one_prompt_and_never_carries_a_nudge(env):
    c, set_model = env
    start(c)
    model = set_model({"reply": "x"})
    for _ in range(3):
        body = say(c, "ok")
        assert body["nudge"] is None and body["reply"].count("?") == 0
    assert asked(model) == []
    metas = [t["meta"] for t in store.thread("p1") if t.get("role") == "assistant" and t.get("kind") == "chat"]
    assert not any(m.get("nudge") for m in metas)


def test_a_nudge_in_a_capture_turn_means_no_advance_on_top_of_it(env):
    c, set_model = env
    start(c)
    set_model({"reply": OFFERING, "views": [{"text": "The ablation study is missing", "section": "weaknesses"}]})
    say(c, "The ablation study is missing")
    set_model({"reply": "Okay. Your draft has nothing under Summary yet.", "nudge_used": True})
    store.log("p1", "section_promised", {"section": "summary"})
    body = say(c, "yes")
    assert body["nudge"] and "go to the methods" not in body["reply"] and pointer() == 0   # one prompt per turn


def test_the_walk_survives_a_reload(env):
    c, _ = env
    start(c)
    say(c, "next")
    st = store.walk_state("p1")                                                   # replayed from the event log
    assert st["pointer"] == 1 and st["covered"] == ["1 Introduction", "3 Method"] and not st["stopped"]
    thread = c.get("/thread/p1").json()
    last = [t for t in thread if t.get("role") == "assistant"][-1]
    assert last["meta"]["walk"] == "3 Method" and last["meta"]["cites"] and last["meta"]["parts"]


# ------------------------------------------------------------------ the words the app uses never evaluate

def test_no_evaluative_words_in_anything_the_walk_says(env):
    c, _ = env
    start(c)
    said = []
    for m in ["next"] * 6 + ["go to results", "stop guiding"]:
        said.append(say(c, m)["reply"])
    for r in said:
        assert not BANNED.search(r) and not cc.reply_errors(r, {"reviewer_text": ""}), r


@pytest.mark.parametrize("title,expected", [
    ("3 Method", "the method"), ("Abstract", "the abstract"), ("4 BERT Analysis", "the BERT Analysis"),
    ("7 Strong Baselines", "the next section"), ("2 Our Novel Approach", "the next section"),
    ("5 Limited Results", "the next section"), ("The Dataset", "the dataset")])
def test_a_heading_with_an_evaluative_word_is_never_repeated_by_the_app(title, expected):
    assert walk.title_phrase(title) == expected


def test_ids_never_reach_the_reviewer(env):
    c, _ = env
    start(c)
    for m in ["next", "go to results", "next", "next"]:
        assert not re.search(r"\bp\d+-s\d+\b|\[p\d", say(c, m)["reply"])
