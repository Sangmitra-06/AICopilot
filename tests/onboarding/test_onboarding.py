"""Mandatory onboarding: rules in onboarding.py, replayed from events by store.fold_onboarding.

Everything here runs offline against an in-memory event list. No model is involved.
"""
import pytest

from app import onboarding as ob, store
from app.verify import BANNED

SPEC_FIELDS = ["reading_order", "workflow_mode", "summary_preference", "note_habit", "excellent_review_example",
               "bad_review_traits", "strength_criteria", "weakness_criteria", "over_under_penalize",
               "hardest_part", "experience_level"]


class Session:
    """A reviewer talking to the backend, with the event log held in a list."""

    def __init__(self, rid="r1"):
        self.rid, self.evs, self.asked = rid, [], []

    def state(self):
        return store.fold_onboarding(self.evs)

    def _log(self, events):
        self.evs += [{"type": e["type"], "payload": e["payload"], "ts": 0.0} for e in events]

    def step(self):
        events, resp = ob.next_step(self.state(), self.rid)
        self._log(events)
        if not resp["done"] and resp["question"] not in self.asked[-1:]:
            self.asked.append(resp["question"])
        return resp

    def say(self, text):
        if not self.state()["pending"]:
            self.step()  # the client fetched the question before replying
        self._log(ob.process(self.state(), text))
        return self.step()

    def run(self, answers, limit=60):
        """Answer each question from `answers` (a list, cycled) until onboarding closes."""
        resp, i = self.step(), 0
        while not resp["done"]:
            assert i < limit, "onboarding never closed"
            resp = self.say(answers[i % len(answers)])
            i += 1
        return resp

    def profile(self):
        return ob.profile_view(self.state())

    def src(self, field):
        return (self.profile()["fields"][field] or {}).get("source")

    def val(self, field):
        return (self.profile()["fields"][field] or {}).get("value")

    def event_types(self):
        return [e["type"] for e in self.evs]


# ------------------------------------------------------------------ shape of the conversation

def test_profile_has_exactly_the_specified_fields():
    assert sorted(ob.FIELDS) == sorted(SPEC_FIELDS)
    assert sorted(Session().profile()["fields"]) == sorted(SPEC_FIELDS)


def test_first_question_is_a_concrete_experience_question_not_a_label_question():
    q = Session().step()["question"].lower()
    assert "how many papers" in q
    for banned in ("novice", "beginner", "how experienced", "experience level", "expert"):
        assert banned not in q


@pytest.mark.parametrize("text", list(ob.QUESTIONS.values()) + list(ob.FOLLOWUPS.values()))
def test_every_prompt_is_one_neutral_question(text):
    assert text.count("?") == 1, text  # one question per turn
    assert not BANNED.search(text), text
    low = text.lower()
    assert not any(w in low for w in ("novice", "beginner", "experience level"))


def test_one_question_per_turn_and_asking_again_does_not_advance():
    s = Session()
    first = s.step()
    again = s.step()
    assert again["question"] == first["question"] and again["turn"] == first["turn"] == 0
    assert s.event_types().count("onboarding_asked") == 1  # re-asking logs nothing new


def test_answering_moves_to_a_different_field():
    s = Session()
    a = s.step()
    b = s.say("12 papers")
    assert a["field"] != b["field"] and b["turn"] == 1


# ------------------------------------------------------------------ skips, defaults, follow-ups

@pytest.mark.parametrize("skip", ["not sure", "no preference", "skip this one", "idk", "I don't know", "no idea.",
                                  "Skip", "dunno", "doesn't matter", "pass"])
def test_skip_answers_store_a_default_and_do_not_trigger_a_followup(skip):
    s = Session()
    s.say("5"); s.say("it is my area")  # experience first
    assert s.step()["field"] == "reading_order"
    nxt = s.say(skip)
    assert s.src("reading_order") == "default" and s.val("reading_order") == ob.DEFAULTS["reading_order"]
    assert nxt["field"] != "reading_order" and nxt["kind"] == "question"
    assert "followup" not in [e["payload"].get("kind") for e in s.evs if e["type"] == "onboarding_asked"]


def test_one_clarifying_followup_then_a_default():
    s = Session()
    s.say("3"); s.say("a bit")
    assert s.step()["field"] == "reading_order"
    r = s.say("hmm well")
    assert (r["field"], r["kind"]) == ("reading_order", "followup")
    r = s.say("still nothing useful here")
    assert r["field"] != "reading_order"
    assert s.src("reading_order") == "default"
    kinds = [e["payload"]["kind"] for e in s.evs if e["type"] == "onboarding_asked" and e["payload"]["field"] == "reading_order"]
    assert kinds == ["question", "followup"]


def test_followup_that_gets_a_real_answer_is_kept():
    s = Session()
    s.say("3"); s.say("a bit")
    s.say("hmm well")
    s.say("I start with the figures")
    assert s.val("reading_order") == "figures_first" and s.src("reading_order") == "answer"


def test_free_text_answers_are_stored_in_the_reviewers_own_words():
    s = Session()
    s.run(["4", "somewhat", "abstract", "alone", "after", "pdf",
           "Claims backed by the experiments they ran", "Missing ablations on the main component"])
    assert s.val("strength_criteria") == "Claims backed by the experiments they ran"
    assert s.val("weakness_criteria") == "Missing ablations on the main component"


# ------------------------------------------------------------------ extraction from free answers

def test_one_free_answer_fills_several_fields_and_those_are_not_asked_again():
    s = Session()
    s.say("12 papers"); s.say("it is my own area")
    s.say("I usually read the abstract first, take my notes in Notion, and I read on my own before we talk.")
    assert s.val("reading_order") == "abstract_first"
    assert (s.val("note_habit"), s.src("note_habit")) == ("separate_doc", "extracted")
    assert (s.val("workflow_mode"), s.src("workflow_mode")) == ("read_first", "extracted")
    asked = [e["payload"]["field"] for e in s.evs if e["type"] == "onboarding_asked"]
    s.run(["after", "Reproducible results", "Unclear writing", "Nothing", "Planning", "A detailed one", "Vague ones"])
    asked = [e["payload"]["field"] for e in s.evs if e["type"] == "onboarding_asked"]
    assert "note_habit" not in asked and "workflow_mode" not in asked


def test_extraction_needs_a_first_person_statement():
    s = Session()
    st = store.fold_onboarding([{"type": "onboarding_asked", "ts": 0, "payload": {
        "field": "weakness_criteria", "kind": "question", "question": "q"}}])
    evs = ob.process(st, "Only a few papers address this and the notes in the appendix are thin")
    assert [e["type"] for e in evs] == ["onboarding_answered", "profile_field_set"]  # nothing extracted


def test_a_review_count_inside_another_answer_is_picked_up():
    st = store.fold_onboarding([{"type": "onboarding_asked", "ts": 0, "payload": {
        "field": "subarea_familiarity", "kind": "question", "question": "q"}}])
    evs = ob.process(st, "This is outside my area. I've reviewed 25 papers though.")
    kinds = {(e["payload"].get("key")): e["payload"]["value"] for e in evs if e["type"] == "evidence_set"}
    assert kinds == {"subarea_familiarity": "unfamiliar", "papers_reviewed": 25}


# ------------------------------------------------------------------ experience inference

@pytest.mark.parametrize("papers,fam,level", [
    (0, "familiar", "low"), (2, "familiar", "low"), (3, "unfamiliar", "low"), (3, "some", "medium"),
    (5, "familiar", "medium"), (10, "unfamiliar", "medium"), (10, "some", "high"), (30, "familiar", "high"),
    (None, "unfamiliar", "low"), (None, "familiar", "medium"), (0, None, "low"), (12, None, "high"),
    (None, None, None)])
def test_infer_experience(papers, fam, level):
    assert ob.infer_experience(papers, fam) == level


@pytest.mark.parametrize("a1,a2,level", [
    ("0, this is my first time", "it is new to me", "low"),
    ("I have never reviewed", "I work on exactly this", "low"),
    ("about 30", "this is my area", "high"),
    ("six or so", "somewhat familiar", "medium"),
])
def test_experience_is_inferred_from_the_two_concrete_answers(a1, a2, level):
    s = Session()
    s.step(); s.say(a1); s.say(a2)
    assert s.val("experience_level") == level and s.src("experience_level") == "inferred"
    assert "novice" not in " ".join(s.asked).lower()


# ------------------------------------------------------------------ low-experience scaffolding

def reach_criteria(s, a1="0", a2="never worked on it"):
    s.step(); s.say(a1); s.say(a2)
    for a in ("abstract", "alone", "after", "pdf"):
        r = s.say(a)
    return r


def test_low_experience_gets_the_criteria_menu_with_other_last():
    s = Session()
    r = reach_criteria(s)
    assert r["field"] == "strength_criteria"
    labels = [m["label"] for m in r["menu"]]
    assert set(labels[:-1]) == {m["label"] for m in ob.menu_items()} and len(labels) == len(ob.menu_items()) + 1
    assert labels[-1] == "Other, in my words" and r["menu"][-1]["id"] == "other"


def test_menu_order_is_random_across_reviewers_but_stable_for_one():
    orders = set()
    for i in range(25):
        orders.add(tuple(m["id"] for m in ob.menu_for(f"reviewer{i}", "strength_criteria")))
    assert len(orders) > 1
    assert ob.menu_for("same", "strength_criteria") == ob.menu_for("same", "strength_criteria")
    s = Session("same")
    assert reach_criteria(s)["menu"] == s.step()["menu"]  # re-asking does not reshuffle


def test_walkthrough_comes_once_with_the_first_question_after_experience():
    s = Session()
    s.step(); s.say("0"); r = s.say("never worked on it")
    assert r["field"] == "reading_order" and "walkthrough" in r
    assert "walkthrough" in s.step()  # still shown if the same question is fetched again
    nxt = s.say("abstract")
    assert "walkthrough" not in nxt
    assert s.event_types().count("walkthrough_shown") == 1


def test_walkthrough_is_descriptive_and_lists_the_form_parts():
    w = ob.walkthrough()
    assert [p["id"] for p in w["parts"]][:3] == ["summary", "strengths", "weaknesses"]
    assert "Soundness" in w["text"] and not BANNED.search(w["text"])
    assert w["text"].count("\n") == 0 and len(w["text"].split()) < 90  # short


def test_high_experience_gets_no_menu_and_no_walkthrough():
    s = Session()
    s.step(); s.say("40 papers"); r = s.say("this is my area")
    assert "walkthrough" not in r
    for a in ("abstract", "together", "after", "pdf"):
        r = s.say(a)
    assert r["field"] == "strength_criteria" and "menu" not in r


def test_menu_picks_are_recorded_and_other_keeps_the_reviewers_words():
    s = Session()
    reach_criteria(s)
    menu = s.step()["menu"]
    s.say("1 and 3")
    got = s.profile()["fields"]["strength_criteria"]
    assert got["picked"] == [menu[0]["id"], menu[2]["id"]] and got["value"] == "1 and 3"
    s.say("other: I look at whether the data are released")
    w = s.profile()["fields"]["weakness_criteria"]
    assert w["value"] == "other: I look at whether the data are released" and "picked" not in w


# ------------------------------------------------------------------ caps and hard stops

def test_user_who_answers_idk_to_everything_finishes_with_all_defaults():
    s = Session()
    done = s.run(["idk"])
    assert done["reason"] == "complete" and done["turn"] == len(ob.ORDER)  # one answer per question, no repeats
    assert len(s.asked) == len(set(s.asked)) == len(ob.ORDER)
    prof = s.profile()["fields"]
    assert set(prof) == set(SPEC_FIELDS)
    assert all(prof[f]["source"] == "default" for f in SPEC_FIELDS)
    assert prof["experience_level"]["value"] == ob.DEFAULTS["experience_level"]
    assert prof["strength_criteria"]["value"] == ""  # a reviewer's criteria are never invented
    assert "onboarding_asked" in s.event_types() and s.event_types().count("onboarding_closed") == 1
    assert all(e["payload"]["kind"] == "question" for e in s.evs if e["type"] == "onboarding_asked")


OFF_TOPIC = ["the weather is lovely today", "my cat is called Bob", "what is your name?", "lol", "banana",
             "can you tell me a joke", "asdfgh", "?"]


def test_off_topic_user_cannot_loop_the_flow_or_poison_structured_fields():
    s = Session()
    done = s.run(OFF_TOPIC)
    assert done["done"] and done["turn"] <= ob.MAX_TURNS
    fu = {}
    for e in s.evs:
        if e["type"] == "onboarding_asked" and e["payload"]["kind"] == "followup":
            fu[e["payload"]["field"]] = fu.get(e["payload"]["field"], 0) + 1
    assert fu and all(n == 1 for n in fu.values())  # never more than one follow-up per field
    prof = s.profile()["fields"]
    for f in ("reading_order", "workflow_mode", "summary_preference", "note_habit"):
        assert prof[f]["source"] == "default", f
    assert prof["experience_level"]["source"] == "default"
    assert s.profile()["closed"]["reason"] in ("cap", "complete")


@pytest.mark.parametrize("bad", ["what is your name?", "can you tell me a joke", "?", "ok", ""])
def test_a_question_or_single_word_is_never_stored_as_a_free_text_answer(bad):
    s = Session()
    s.run(["2", "some", "abstract", "alone", "after", "pdf"] + [bad] * 20)
    assert s.src("strength_criteria") == "default" and s.val("strength_criteria") == ""


def test_hard_cap_closes_with_whatever_was_collected():
    s = Session()
    answers = ["3", "a bit"] + ["hmm"] * 40  # unclear forever after the evidence
    done = s.run(answers)
    assert done["reason"] == "cap" and done["turn"] == ob.MAX_TURNS
    closed = s.profile()["closed"]
    assert closed["reason"] == "cap" and closed["defaulted"]
    prof = s.profile()["fields"]
    assert prof["experience_level"]["value"] == "medium" and prof["experience_level"]["source"] == "inferred"
    assert all(prof[f] is not None for f in SPEC_FIELDS)


def test_nothing_changes_after_close():
    s = Session()
    s.run(["idk"])
    n = len(s.evs)
    assert s.say("12 papers")["done"] and s.step()["done"]
    assert len(s.evs) == n


def test_question_is_never_asked_a_third_time_for_any_answer_pattern():
    for pattern in (["idk"], ["hmm"], ["lol", "idk"], ["3", "a bit", "abstract", "alone", "after", "pdf", "x"]):
        s = Session()
        s.run(pattern)
        per_field = {}
        for e in s.evs:
            if e["type"] == "onboarding_asked":
                per_field[e["payload"]["field"]] = per_field.get(e["payload"]["field"], 0) + 1
        assert max(per_field.values()) <= 2, (pattern, per_field)


# ------------------------------------------------------------------ reflecting their words

def test_the_assistant_echoes_the_last_answer_in_the_reviewers_own_words():
    s = Session()
    s.step()
    r = s.say("a dozen or so, mostly workshop papers")
    assert r["reflect"] == "a dozen or so, mostly workshop papers"
    r = s.say("idk")
    assert "reflect" not in r  # nothing to echo after a skip


# ------------------------------------------------------------------ persistence through the endpoint

@pytest.fixture
def api(monkeypatch):
    import sqlite3
    from app import main
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.execute("create table events(id integer primary key, ts real, paper text, type text, payload text)")
    monkeypatch.setattr(store, "db", db)
    return main


def test_endpoint_persists_everything_as_events_and_state_comes_from_replay(api):
    r = api.onboarding_step("abc")
    assert r["field"] == "papers_reviewed" and not r["done"]
    r = api.onboarding_answer("abc", api.OnbAnswer(text="7 papers"))
    assert r["field"] == "subarea_familiarity" and r["profile"]["evidence"]["papers_reviewed"]["value"] == 7
    rows = store.db.execute("select paper,type from events order by id").fetchall()
    assert {p for p, _ in rows} == {"reviewer:abc"}
    assert [t for _, t in rows] == ["onboarding_asked", "onboarding_answered", "evidence_set", "onboarding_asked"]
    # a "restart": nothing is held in memory, the next request resumes from the log
    again = api.onboarding_step("abc")
    assert again["question"] == r["question"]
    assert api.profile_ep("abc")["evidence"]["papers_reviewed"]["value"] == 7


def test_endpoint_runs_a_full_idk_session_and_profiles_are_per_reviewer(api):
    r = api.onboarding_step("idk-user")
    while not r["done"]:
        r = api.onboarding_answer("idk-user", api.OnbAnswer(text="idk"))
    assert r["reason"] == "complete"
    assert api.profile_ep("someone-else")["closed"] is None
    assert api.onboarding_step("someone-else")["field"] == "papers_reviewed"


def test_endpoint_rejects_odd_reviewer_ids(api):
    from fastapi import HTTPException
    for bad in ("a b", "x" * 65, "../etc", "a:b"):
        with pytest.raises(HTTPException):
            api.onboarding_step(bad)
