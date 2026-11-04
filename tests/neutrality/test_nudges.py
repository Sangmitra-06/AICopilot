"""Item 4: the silent coverage map and guided nudges (selection, ordering, bookkeeping, gates)."""
import re

import pytest

from app import nudges, store
from app.verify import BANNED
from conftest import make_reviewer

SECTIONS = [
    {"id": "summary", "name": "Paper summary", "required": True, "type": "text"},
    {"id": "strengths", "name": "Summary of strengths", "required": True, "type": "text"},
    {"id": "weaknesses", "name": "Summary of weaknesses", "required": True, "type": "text"},
    {"id": "comments", "name": "Comments, suggestions and typos", "required": False, "type": "text"},
    {"id": "soundness", "name": "Soundness", "required": True, "type": "score"},
    {"id": "excitement", "name": "Excitement", "required": True, "type": "score"},
    {"id": "overall", "name": "Overall assessment", "required": True, "type": "score"},
    {"id": "confidence", "name": "Confidence", "required": True, "type": "score"},
    {"id": "reproducibility", "name": "Reproducibility", "required": False, "type": "score"},
    {"id": "ethics", "name": "Ethical concerns", "required": False, "type": "text"},
]


def rs(addressed=(), notes=(), promised=(), skipped=()):
    return {"sections": SECTIONS, "addressed": {s: True for s in addressed}, "skipped": {s: True for s in skipped},
            "notes": list(notes), "views": {}, "promised": list(promised), "titles": []}


def pick(reading="paper_order", hardest=None, nudge_state=None, **kw):
    return nudges.pick_nudge(rs(**kw), reading, hardest, nudge_state or {})


# ------------------------------------------------------------------ reading words and promises

def test_sections_are_recognised_by_their_names_and_plain_synonyms():
    assert nudges.mentions("I keep losing track of the weaknesses and the typos", SECTIONS) == ["weaknesses", "comments"]
    assert nudges.mentions("deciding the scores is the hard bit", SECTIONS) == ["overall"]
    assert nudges.mentions("the ethical side", SECTIONS) == ["ethics"]
    assert nudges.mentions("nothing to see", SECTIONS) == []


@pytest.mark.parametrize("msg,found", [
    ("I'll cover the ethics part later", ["ethics"]),
    ("I want to talk about weaknesses next. I'll do the summary at the end.", ["weaknesses", "summary"]),
    ("later I'll write the reproducibility bit", ["reproducibility"]),
    ("I need to see the soundness table", []),                # no action verb: not a promise
    ("The ethics statement is missing", []),                   # no future cue
])
def test_promises_to_cover_a_section(msg, found):
    assert nudges.promises(msg, SECTIONS) == found


# ------------------------------------------------------------------ which section next

@pytest.mark.parametrize("reading,first", [
    ("abstract_first", "summary"), ("in_order", "summary"), ("paper_order", "summary"),
    ("methods_first", "soundness"), ("results_first", "strengths"), ("figures_first", "strengths"),
    ("conclusion_first", "excitement"),
])
def test_nudges_follow_the_reviewers_reading_order(reading, first):
    assert pick(reading)["section"] == first


def test_the_next_uncovered_section_follows_the_same_order_as_sections_fill_in():
    order = []
    done = []
    for _ in range(10):
        c = pick("results_first", addressed=done)
        if not c:
            break
        order.append(c["section"])
        done.append(c["section"])
    assert order[:4] == ["strengths", "weaknesses", "soundness", "reproducibility"]   # results, then method sections
    assert set(order) == {s["id"] for s in SECTIONS}


def test_what_they_said_is_hardest_pulls_that_section_forward():
    c = pick("abstract_first", hardest="deciding the scores")
    assert c["section"] == "overall" and c["hardest"] == "deciding the scores"
    assert pick("abstract_first", hardest="nothing in particular")["section"] == "summary"


def test_a_promised_section_comes_before_the_rest():
    assert pick("abstract_first", promised=["ethics"])["section"] == "ethics"
    assert pick("abstract_first", promised=["ethics"])["kind"] == "promised"


def test_covered_and_skipped_sections_are_not_nudged():
    c = pick("abstract_first", addressed=["summary"], skipped=["soundness", "reproducibility", "strengths"])
    assert c["section"] == "weaknesses"


def test_content_that_cites_nothing_can_be_the_nudge_when_nothing_is_empty_first():
    note = {"key": "n1", "field": "weaknesses", "text": "Five participants per region seems low", "cited": False}
    c = pick("abstract_first", addressed=[s["id"] for s in SECTIONS], notes=[note])
    assert c["kind"] == "uncited" and c["section"] == "weaknesses"
    assert "Five participants per region seems low" in c["statement"]
    note["cited"] = True
    assert pick("abstract_first", addressed=[s["id"] for s in SECTIONS], notes=[note]) is None


def test_dismissed_or_overused_sections_are_never_chosen():
    state = {"summary": {"dismissed": True}, "strengths": {"offered": nudges.MAX_OFFERS}}
    assert pick("abstract_first", nudge_state=state)["section"] == "soundness"
    everything = {s["id"]: {"dismissed": True} for s in SECTIONS}
    assert pick("abstract_first", nudge_state=everything) is None


# ------------------------------------------------------------------ what a nudge says

def test_every_nudge_statement_is_about_the_review_and_evaluates_nothing():
    for kind, text in (("empty", None), ("promised", None), ("uncited", "Five participants per region seems low")):
        for s in SECTIONS:
            st = nudges.statement({"kind": kind, "label": s["name"], "text": text})
            outside = re.sub(r"“[^”]*”", " ", st)
            assert not BANNED.search(outside), st
            assert st.startswith(("Your draft has nothing", "You mentioned", "Under "))


def test_the_directive_carries_the_statement_the_section_and_the_reviewers_own_words():
    c = pick("abstract_first", hardest="deciding the scores")
    note = nudges.nudge_note(c)
    assert c["statement"] in note and "Overall assessment" in note and "“deciding the scores”" in note
    assert "Never say what should go in that section" in note and "never comment on the paper" in note
    assert "ONE light nudge" in note and "never as a stock closing line" in note


def test_natural_pauses():
    for msg in ("ok", "thanks", "got it", "ok.", "next", "that's all for now", "yep", "hmm"):
        assert nudges.natural_pause(msg), msg
    assert nudges.natural_pause("sure thing")                                   # three words, no question
    assert nudges.natural_pause("anything long really", just_answered_offer=True)
    for msg in ("what does the paper say about the datasets used?", "I think the sample is small and unbalanced",
                "why did they reject outliers?"):
        assert not nudges.natural_pause(msg), msg


# ------------------------------------------------------------------ bookkeeping in the event log

def fold(*events):
    return store.fold_chat([{"type": t, "payload": p, "ts": 0} for t, p in events])["nudges"]


def test_ignored_twice_is_a_dismissal():
    st = fold(("nudge_offered", {"section": "summary"}), ("nudge_resolved", {"section": "summary", "outcome": "ignored"}))
    assert st["summary"] == {"offered": 1, "ignored": 1, "dismissed": False, "pending": False}
    st = fold(("nudge_offered", {"section": "summary"}), ("nudge_resolved", {"section": "summary", "outcome": "ignored"}),
              ("nudge_offered", {"section": "summary"}), ("nudge_resolved", {"section": "summary", "outcome": "ignored"}))
    assert st["summary"]["dismissed"] is True and st["summary"]["offered"] == 2


def test_an_explicit_not_now_is_a_dismissal_and_following_is_not():
    assert fold(("nudge_offered", {"section": "ethics"}), ("nudge_resolved", {"section": "ethics", "outcome": "dismissed"}))["ethics"]["dismissed"]
    assert not fold(("nudge_offered", {"section": "ethics"}), ("nudge_resolved", {"section": "ethics", "outcome": "followed"}))["ethics"]["dismissed"]


# ------------------------------------------------------------------ the gates, through the endpoint

def post(c, message, rid="rev"):
    r = c.post("/chat/p1", json={"reviewer_id": rid, "message": message})
    assert r.status_code == 200, r.text
    return r.json()


NUDGING = {"reply": "Noted. Your draft has nothing under Paper summary yet. Want to start there?", "nudge_used": True}
PLAIN = {"reply": "Sure.", "nudge_used": False}


@pytest.fixture
def env(chat_env):
    c, set_model = chat_env
    make_reviewer("rev", hardest_part="deciding how much a missing ablation should count",
                  reading_order="I read the abstract first", reading_order__value="abstract_first")
    return c, set_model


def test_a_pause_gets_a_directive_and_a_used_nudge_is_tracked(env):
    c, set_model = env
    model = set_model(NUDGING)
    body = post(c, "ok")
    assert "NUDGE (optional)" in model.system and "Your draft has nothing under Paper summary yet." in model.system
    assert body["nudge"] == {"section": "summary", "label": "Paper summary", "kind": "empty"}
    assert store.chat_state("p1")["nudges"]["summary"]["offered"] == 1
    assert store.thread("p1")[-1]["meta"]["nudge"] == "summary"


def test_a_long_message_or_a_question_gets_no_directive(env):
    c, set_model = env
    model = set_model(NUDGING)
    for msg in ("I think the sample is small and unbalanced across regions", "what does Table 2 report?"):
        assert post(c, msg)["nudge"] is None
        assert "NUDGE (optional)" not in model.system


def test_a_directive_the_model_did_not_use_is_not_tracked(env):
    c, set_model = env
    set_model(PLAIN)
    assert post(c, "ok")["nudge"] is None and store.chat_state("p1")["nudges"] == {}


def test_a_flag_without_the_section_in_the_reply_is_not_tracked(env):
    c, set_model = env
    set_model({"reply": "Noted.", "nudge_used": True})
    assert post(c, "ok")["nudge"] is None


def test_never_twice_in_a_row(env):
    c, set_model = env
    model = set_model(NUDGING)
    post(c, "ok")
    assert post(c, "ok")["nudge"] is None and "NUDGE (optional)" not in model.system


def test_never_right_after_a_judgment_decline(env):
    c, set_model = env
    model = set_model({"reply": "That's your call to make, not mine. Table 2 is where the numbers are (Section 4)."})
    post(c, "is this novel?")
    set_model(NUDGING)
    assert post(c, "ok")["nudge"] is None and "NUDGE (optional)" not in model.system
    assert post(c, "ok")["nudge"] is not None                    # one turn later it is allowed again


def test_never_on_the_turn_that_declines(env):
    c, set_model = env
    model = set_model({"reply": "That's your call to make, not mine. Table 2 has the numbers (Section 4)."})
    post(c, "do you agree?")
    assert "NUDGE (optional)" not in model.system


def test_never_during_onboarding(chat_env):
    c, set_model = chat_env
    model = set_model(NUDGING)
    body = c.post("/chat/p1", json={"reviewer_id": "newbie", "message": "ok"}).json()
    assert body["mode"] == "onboarding" and not model.calls


def test_not_now_dismisses_and_the_section_is_never_nudged_again(env):
    c, set_model = env
    set_model(NUDGING)
    post(c, "ok")
    model = set_model({"reply": "No problem. Your draft has nothing under Summary of strengths yet.", "nudge_used": True})
    post(c, "not now")                                           # dismisses Paper summary; also a pause, but...
    assert store.chat_state("p1")["nudges"]["summary"]["dismissed"] is True
    for _ in range(6):
        post(c, "ok")
        assert "Your draft has nothing under Paper summary yet" not in model.system


def test_a_promise_in_chat_is_remembered_and_pulls_that_section_forward(env):
    c, set_model = env
    set_model(PLAIN)
    post(c, "I'll cover the ethics part later")
    assert store.chat_state("p1")["promised"] == ["ethics"]
    model = set_model(PLAIN)
    post(c, "ok")
    assert "You mentioned you would cover Ethical concerns; nothing is there yet." in model.system
