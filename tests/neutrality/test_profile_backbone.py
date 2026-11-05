"""The onboarding profile leads the conversation (fix item 6), in the reviewer's own words.

Reading order decides where the walk goes and is said first; summary_preference decides the summary; workflow_mode sets
the pace ("together" leads step by step, "read first" waits); strength/weakness criteria and note habit give one light
prompt when a section is on screen; hardest_part and experience level shape the prompt; bad_review_traits are reminders
when they check their draft. Their words are quoted exactly, never ranked or used to say anything about the paper, at
most one profile reference per turn, never the same one twice in a row, and every reply still passes the checks.

The profile below is the real session's (onboarding answers, events 1-38 of its log).
"""
import re

import pytest

from app import chat_checks as cc, main, prompts, store, walk
from app.verify import BANNED
from conftest import make_reviewer
from test_walk_section_match import SESSION_LAYOUT, spans_for

SESSION = dict(
    reading_order="I start with intro then I like to get into methods and results", reading_order__value="intro_first",
    workflow_mode="together", workflow_mode__value="collaborative",
    summary_preference="yes and I want it before I read", summary_preference__value="before_reading",
    note_habit="in the pdf", note_habit__value="annotate_pdf",
    strength_criteria="backed up methods", weakness_criteria="thin results",
    over_under_penalize="none", hardest_part="the time that it takes",
    excellent_review_example="clarity and precision", bad_review_traits="restating the limitations section]",
    experience_level="low",
)
THEIR_WORDS = " ".join(v for k, v in SESSION.items() if not k.endswith("__value"))
LENS = {"strength_criteria": "“backed up methods”", "weakness_criteria": "“thin results”", "note_habit": "“in the pdf”"}


def reviewer(rid="rev", **change):
    make_reviewer(rid, **{**SESSION, **change})


@pytest.fixture
def env(chat_env, monkeypatch):
    c, set_model = chat_env
    monkeypatch.setitem(main.CACHE, "p1", spans_for(SESSION_LAYOUT))
    return c, set_model


def say(c, message):
    r = c.post("/chat/p1", json={"reviewer_id": "rev", "message": message})
    assert r.status_code == 200, r.text
    return r.json()


def open_(c):
    return c.post("/chat/p1/open", json={"reviewer_id": "rev"}).json()


def refs_used(text):
    return [f for f, q in LENS.items() if q in text]


def assert_neutral(text, summary=False):
    """The reply passes the chat checks, and outside the reviewer's quoted words the app's own text rates nothing.
    `summary`: the opening summary they asked for in onboarding (a summary is allowed there)."""
    ctx = {"reviewer_text": THEIR_WORDS, "summary_requested": summary, "summary_pref": "before_reading" if summary else None}
    assert cc.reply_errors(text, ctx) == [], text
    outside = re.sub(r"“[^”]*”", " ", text)
    assert not BANNED.search(outside) and not walk.rates(outside), text


# ------------------------------------------------------------------ the PROFILE block

def block(**kw):
    from app import chatflow, onboarding
    reviewer()
    view = onboarding.profile_view(store.onboarding("rev"))
    return prompts.profile_block(chatflow.profile_phrases(view), "before_reading", **chatflow.profile_kw(view), **kw)


def test_the_profile_block_quotes_every_stated_field_and_says_how_it_leads(chat_env):
    from app import onboarding
    b = block()
    for field in ("reading_order", "workflow_mode", "summary_preference", "note_habit", "strength_criteria",
                  "weakness_criteria", "hardest_part", "excellent_review_example", "bad_review_traits"):
        assert f'"{onboarding.tidy(SESSION[field], edges_only=True)}"' in b, field
    for needle in ("how you lead this conversation", "Never use the profile to express an opinion about the paper",
                   "at most one profile reference per reply", "never the same one as in your previous reply",
                   "Do not rank, grade, re-interpret or paraphrase", "PACE: they want to work through the paper together",
                   "HOW MUCH TO EXPLAIN: explain terms", "time is the hard part", "never changes the NEUTRALITY"):
        assert needle in b, needle
    assert "low" not in re.findall(r'"([^"]*)"', b)                          # the level is never quoted as a label


def test_rules_for_fields_they_did_not_state_are_left_out():
    b = prompts.profile_block({"note_habit": "in the pdf"}, None)
    assert "strength" not in b.lower() and "PACE" not in b and "time is the hard part" not in b


@pytest.mark.parametrize("workflow,needle", [("read_first", "do not lead, do not nudge"), ("collaborative", "Lead step by step")])
def test_the_pace_follows_workflow_mode(workflow, needle):
    assert needle in prompts.profile_block({}, None, workflow=workflow)


# ------------------------------------------------------------------ "together": the walk leads, with one lens prompt

def test_the_opening_leads_with_the_reading_order_and_the_summary_preference(env):
    c, set_model = env
    reviewer()
    set_model({"reply": "The authors report X [p2-s1]."}, {"reply": "plain"})
    msgs = open_(c)["messages"]
    assert [m["kind"] for m in msgs] == ["summary", "section"]
    assert msgs[0]["reply"].startswith("You asked for a short summary before reading")
    assert msgs[1]["reply"].startswith("You said you like to start with the intro, then the methods, so here's the intro")


def test_each_section_on_screen_carries_one_lens_prompt_in_their_words_and_never_the_same_twice(env):
    c, set_model = env
    reviewer()
    set_model({"reply": "plain"})
    opening = [m["reply"] for m in open_(c)["messages"]]
    later = [say(c, "next")["reply"] for _ in range(4)]
    assert not any(refs_used(r) for r in opening)                           # the opening carries no lens line
    used = [refs_used(r) for r in later]
    assert all(len(u) == 1 for u in used), used                             # one per section, never more
    seq = [u[0] for u in used]
    assert seq == ["strength_criteria", "weakness_criteria", "note_habit", "strength_criteria"]
    assert all(a != b for a, b in zip(seq, seq[1:]))                        # never the same twice in a row
    for r in opening + later:
        assert_neutral(r)


def test_the_first_section_after_the_opening_has_no_lens_line_and_the_next_one_does(env):
    c, set_model = env
    reviewer()
    set_model({"reply": "plain"})
    first = open_(c)["messages"][-1]
    assert first["kind"] == "section" and "is what counts as a" not in first["reply"]
    assert store.thread("p1")[-1]["meta"].get("profile_ref") is None
    assert "You said “backed up methods” is what counts as a strength for you." in say(c, "next")["reply"]


def test_the_lens_prompt_quotes_them_and_asks_them_to_look(env):
    c, set_model = env
    reviewer()
    set_model({"reply": "plain"})
    open_(c)
    first = say(c, "next")["reply"]
    assert "You said “backed up methods” is what counts as a strength for you. Want to read this part with that in mind?" in first
    assert "You said “thin results” is what counts as a weakness for you." in say(c, "next")["reply"]
    third = say(c, "next")["reply"]
    assert "Since you said you keep notes “in the pdf”, you can drag a box over any passage here to mark it" in third


def test_a_habit_other_than_the_pdf_is_offered_as_saving_in_their_words(env):
    c, set_model = env
    reviewer(strength_criteria=None, weakness_criteria=None, note_habit="in a separate doc",
             note_habit__value="separate_doc")
    set_model({"reply": "plain"})
    open_(c)
    assert "Since you said you keep notes “in a separate doc”, tell me anything here you want to keep" in say(c, "next")["reply"]


# ------------------------------------------------------------------ model turns: one profile reference, rotated

def test_the_next_model_turn_is_given_one_profile_reference_in_their_words(env):
    c, set_model = env
    reviewer()
    set_model({"reply": "plain"})
    open_(c)
    say(c, "next")                                                          # this section used strength_criteria
    model = set_model({"reply": "Section 3 describes the probe [p4-s1]."})
    say(c, "what is a probe?")
    note = [l for l in model.system.splitlines() if "PROFILE REFERENCE" in l]
    assert len(note) == 1 and "weakness_criteria = “thin results”" in note[0]   # not the one used last turn


def test_a_reference_the_model_used_is_not_offered_again_next_turn(env):
    c, set_model = env
    reviewer(note_habit=None)
    set_model({"reply": "plain"})
    open_(c)
    say(c, "next")                                                          # strength
    set_model({"reply": "You said “thin results” is what counts as a weakness for you; Section 4 has the numbers [p8-s1]."})
    say(c, "where are the numbers?")
    assert store.thread("p1")[-1]["meta"]["profile_ref"] == "weakness_criteria"
    model = set_model({"reply": "Okay."})
    say(c, "and the baselines?")
    assert "strength_criteria = “backed up methods”" in model.system and "weakness_criteria = “" not in model.system


# ------------------------------------------------------------------ quoting: stray edge marks go, no word changes

def test_a_stray_bracket_at_the_edge_is_dropped_when_quoted_back(env):
    c, _ = env
    reviewer()
    reply = say(c, "what's missing?")["reply"]
    assert "“restating the limitations section”" in reply and "section]" not in reply
    assert '"restating the limitations section"' in block()


@pytest.mark.parametrize("raw,quoted", [
    ("restating the limitations section]", "restating the limitations section"),
    ("“in the pdf”", "in the pdf"),
    ("(backed up methods", "backed up methods"),
    ("yes, intro first, then methods", "yes, intro first, then methods"),       # words are never removed
    ("thin results, please", "thin results, please"),
    ("don't over-claim", "don't over-claim"),                                  # inner marks stay
    ("]", "]"),                                                               # never emptied
])
def test_edges_only_tidy_never_rewords(raw, quoted):
    from app import onboarding
    assert onboarding.tidy(raw, edges_only=True) == quoted


# ------------------------------------------------------------------ the summary rule once the summary was given

def test_after_the_opening_summary_the_rule_says_it_was_given_and_not_to_offer_another(env):
    c, set_model = env
    reviewer()
    set_model({"reply": "The authors report X [p2-s1]."}, {"reply": "plain"})
    assert open_(c)["messages"][0]["kind"] == "summary"
    model = set_model({"reply": "Okay."})
    say(c, "where do they describe the probe?")
    rule = model.system.split("SUMMARY RULE: ")[1].splitlines()[0]
    assert rule == prompts.SUMMARY_GIVEN and "may offer one early" not in model.system


def test_without_an_opening_summary_the_rule_is_unchanged(env):
    c, set_model = env
    reviewer(summary_preference="after I read it", summary_preference__value="after_reading")
    set_model({"reply": "plain"})
    open_(c)
    model = set_model({"reply": "Okay."})
    say(c, "where do they describe the probe?")
    assert "SUMMARY RULE: " + prompts.SUMMARY_RULES["after_reading"] in model.system


def test_if_the_opening_summary_failed_the_rule_still_lets_it_be_offered(env):
    c, set_model = env
    reviewer()
    set_model({"reply": "This is a novel paper [p2-s1]."})                  # rejected twice: no summary is shown
    assert [m["kind"] for m in open_(c)["messages"]] == ["section"]
    model = set_model({"reply": "Okay."})
    say(c, "where do they describe the probe?")
    assert "SUMMARY RULE: " + prompts.SUMMARY_RULES["before_reading"] in model.system


def test_no_profile_reference_on_a_turn_that_carries_a_nudge_or_a_decline(env):
    c, set_model = env
    reviewer()
    set_model({"reply": "plain"})
    open_(c)
    model = set_model({"reply": "That's your call to make, not mine."})
    say(c, "is this paper novel?")
    assert "PROFILE REFERENCE" not in model.system.split("THIS TURN:")[-1]


def test_model_replies_with_their_words_still_pass_the_checks(env):
    c, set_model = env
    reviewer()
    set_model({"reply": "plain"})
    open_(c)
    body = say_with(c, set_model, "You said “thin results” is what counts as a weakness for you. Table 2 has the per-model "
                                  "numbers [p8-s1].", "where are the results?")
    assert body["checks"]["fallback"] is False and "“thin results”" in body["reply"]
    assert_neutral(body["reply"])


def say_with(c, set_model, reply, message):
    set_model({"reply": reply})
    return say(c, message)


# ------------------------------------------------------------------ "read first": the app waits

def test_read_first_waits_and_leads_nothing_until_asked(env):
    c, set_model = env
    reviewer(workflow_mode="on my own first", workflow_mode__value="read_first")
    set_model({"reply": "The authors report X [p2-s1]."}, {"reply": "plain"})
    msgs = open_(c)["messages"]
    assert [m["kind"] for m in msgs] == ["summary", "wait"]
    assert msgs[1]["reply"].startswith("You said “on my own first”, so I'll wait until you ask.")
    assert msgs[0]["reply"].endswith("Ask me about any part whenever you like.")       # no "let's go through it together"
    assert store.walk_state("p1")["pointer"] is None
    model = set_model({"reply": "Section 3 describes it [p4-s1]."})
    body = say(c, "ok thanks")
    this_turn = model.system.split("THIS TURN:")[1] if "THIS TURN:" in model.system else ""
    assert "PROFILE REFERENCE" not in this_turn and "NUDGE" not in this_turn and body["nudge"] is None
    assert not refs_used(body["reply"])
    for m in msgs:
        assert_neutral(m["reply"], summary=m["kind"] == "summary")


def test_read_first_next_starts_the_walk_when_they_ask(env):
    c, set_model = env
    reviewer(workflow_mode="on my own first", workflow_mode__value="read_first")
    set_model({"reply": "plain"})
    open_(c)
    body = say(c, "next")
    assert store.walk_state("p1")["pointer"] == 0 and body["walk"]["section"] == "1 Introduction"
    assert not refs_used(body["reply"])                                     # they lead; no lens prompts


# ------------------------------------------------------------------ checking the draft: their bad-review reminder

def add(nid, field, text):
    store.log("p1", "note_added", {"id": nid, "field": field, "text": text, "span_ids": [], "page": None, "rect": None,
                                   "sentence": "", "revisit": False, "question": ""})


def test_whats_missing_reminds_them_in_their_words_and_points_out_repeated_points(env):
    c, set_model = env
    reviewer()
    add(1, "weaknesses", "The limitations section says only three models were tested")
    add(2, "comments", "only three models were tested, as the limitations section says")
    reply = say(c, "what's missing?")["reply"]
    assert "You said “restating the limitations section” is a trait you don't want in a review" in reply
    assert "These points in your draft repeat each other:" in reply
    assert_neutral(reply)


def test_the_reminder_is_not_repeated_on_the_next_check(env):
    c, _ = env
    reviewer()
    first = say(c, "what's missing?")["reply"]
    second = say(c, "what's missing?")["reply"]
    assert "is a trait you don't want in a review" in first and "is a trait you don't want in a review" not in second


def test_no_reminder_or_duplicates_when_there_is_nothing_to_say(env):
    c, _ = env
    reviewer(bad_review_traits=None)
    add(1, "weaknesses", "The baselines are from 2019")
    reply = say(c, "what's missing?")["reply"]
    assert "is a trait you don't want in a review" not in reply and "repeat each other" not in reply


# ------------------------------------------------------------------ the app's own profile lines say nothing about the paper

def test_every_app_written_profile_line_is_neutral(chat_env):
    from app import onboarding, profile
    reviewer()
    view = onboarding.profile_view(store.onboarding("rev"))
    lines = [profile.lens_line(f, view) for f in profile.LENS] + [profile.bad_traits_line(view),
             walk.wait_line("on my own first", {"section": "1 Introduction", "said": "intro"})]
    for line in lines:
        assert line
        assert_neutral(line)
