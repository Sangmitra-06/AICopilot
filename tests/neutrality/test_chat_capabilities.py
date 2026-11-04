"""Item 3: capture, reword, gap reports, paper-conflict notes and drafting, all through /chat in plain language."""
import json
import re

import pytest

from app import chat_checks as cc, coverage, pointers, store, synth
from app.verify import BANNED
from conftest import make_reviewer

VIEW = "five participants per region seems low"
OFFER = "Noted. Want me to add that to the Weaknesses section of your draft?"


def post(c, message, rid="rev"):
    r = c.post("/chat/p1", json={"reviewer_id": rid, "message": message})
    assert r.status_code == 200, r.text
    return r.json()


def stated(view=VIEW, section="weaknesses", reply=OFFER):
    return {"reply": reply, "views": [{"text": view, "section": section}]}


def notes():
    return store.notes("p1")


def add_note(nid, field, text, **kw):
    store.log("p1", "note_added", {"id": nid, "field": field, "text": text, "span_ids": kw.get("span_ids", []),
                                   "page": None, "rect": None, "sentence": "", "revisit": False, "question": ""})


@pytest.fixture
def env(chat_env):
    c, set_model = chat_env
    make_reviewer("rev")
    return c, set_model


# ------------------------------------------------------------------ (a) capture

def test_a_stated_view_is_offered_for_the_right_section_in_their_own_words(env):
    c, set_model = env
    set_model(stated())
    body = post(c, f"I think {VIEW}.")
    assert body["capture"] == {"id": "v1", "text": VIEW, "section": "weaknesses", "label": "Summary of weaknesses"}
    assert notes() == []                                      # an offer, not yet in the draft
    types = [e["type"] for e in store.events("p1")]
    assert "view_stated" in types and "capture_offered" in types and "note_added" not in types


def test_a_bare_yes_puts_the_view_in_the_draft_verbatim(env):
    c, set_model = env
    set_model(stated(), {"reply": "Added to Weaknesses."})
    post(c, f"I think {VIEW}.")
    body = post(c, "yes")
    assert body["resolved"] == {"outcome": "accepted", "text": VIEW} and body["draft_changed"] is True
    [n] = notes()
    assert (n["text"], n["field"], n["by"] if "by" in n else "chat") == (VIEW, "weaknesses", "chat")
    assert any(i["text"] == VIEW and i["field"] == "weaknesses" for i in synth.items("p1"))
    model = set_model()
    post(c, "anything else?")
    assert VIEW in model.system.split("THE REVIEW DRAFT SO FAR")[1]   # the next prompt shows it in the draft


def test_a_bare_no_drops_the_offer_and_nothing_is_captured(env):
    c, set_model = env
    set_model(stated(), {"reply": "Okay, leaving it out."})
    post(c, f"I think {VIEW}.")
    body = post(c, "no")
    assert body["resolved"]["outcome"] == "rejected" and notes() == []
    assert store.chat_state("p1")["views"]["v1"]["outcome"] == "rejected"


def test_the_model_can_resolve_a_wordier_answer_and_move_it_to_another_section(env):
    c, set_model = env
    set_model(stated(), {"reply": "Moved it to Strengths.", "offer_response": "accept", "offer_section": "strengths"})
    post(c, f"I think {VIEW}.")
    body = post(c, "yes, but put it under strengths")
    assert body["resolved"]["outcome"] == "accepted" and notes()[0]["field"] == "strengths"


def test_an_offer_only_stays_open_for_the_next_turn(env):
    c, set_model = env
    set_model(stated(), {"reply": "Section 4 has the numbers."}, {"reply": "Sure."})
    post(c, f"I think {VIEW}.")
    post(c, "where are the numbers?")          # moved on without answering
    body = post(c, "yes")                       # a later "yes" must not capture the old view
    assert notes() == [] and body["resolved"] is None


def test_captured_text_is_editable_and_removable_through_the_existing_events_endpoint(env):
    c, set_model = env
    set_model(stated(), {"reply": "Added."})
    post(c, f"I think {VIEW}.")
    post(c, "yes")
    nid = notes()[0]["id"]
    ev = lambda t, p: c.post("/events", json={"paper_id": "p1", "type": t, "payload": p}).status_code
    assert ev("note_text_edited", {"id": nid, "text": "five participants per region"}) == 200
    assert [n["text"] for n in c.get("/notes/p1").json()] == ["five participants per region"]
    assert [i["text"] for i in synth.items("p1")] == ["five participants per region"]
    assert ev("note_removed", {"id": nid}) == 200
    assert c.get("/notes/p1").json() == [] and synth.items("p1") == []


def test_a_view_that_is_not_a_verbatim_span_of_their_message_is_ignored(env):
    c, set_model = env
    set_model(stated(view="the sample is tiny and unrepresentative"))
    body = post(c, f"I think {VIEW}.")
    assert body["capture"] is None and store.chat_state("p1")["views"] == {}


def test_a_view_without_an_actual_offer_in_the_reply_is_remembered_but_not_offered(env):
    c, set_model = env
    set_model(stated(reply="Table 2 has the per-region counts (Section 4)."), {"reply": "Sure."})
    body = post(c, f"I think {VIEW}.")
    assert body["capture"] is None and "v1" in store.chat_state("p1")["views"]
    post(c, "yes")
    assert notes() == []                       # nothing was offered, so a "yes" captures nothing


def test_a_view_the_model_invents_cannot_be_captured(env):
    c, set_model = env
    set_model(stated(view="the baseline is weak"))
    assert post(c, "what does Table 2 show?")["capture"] is None


# ------------------------------------------------------------------ (b) reword

ORIGINAL = "The baseline is weak and the writing is sloppy, I think."


def reword(text, original=ORIGINAL, reply=None):
    return {"reply": reply or f"Here's a tighter version: {text}", "reword": {"original": original, "text": text}}


def test_reword_keeps_the_reviewers_stance_words(env):
    c, set_model = env
    new = "I think the baseline is weak and the writing is sloppy."
    set_model(reword(new))
    body = post(c, f"reword this: {ORIGINAL}")
    assert body["checks"]["attempts"] == 1 and body["reword"] == {"original": ORIGINAL, "text": new}
    assert new in body["reply"]


@pytest.mark.parametrize("bad", [
    "I think the baseline is not great and the writing needs work.",    # their words replaced
    "I think the baseline is weak and the writing is somewhat sloppy.",  # a hedge added
    "The baseline is weak and the writing is sloppy.",                   # "I think" dropped
    "I think the baseline is very weak and the writing is sloppy.",      # an intensifier added
    "I think the baseline is not weak and the writing is sloppy.",       # stance flipped
])
def test_reword_that_changes_the_stance_is_regenerated_then_falls_back(env, bad):
    c, set_model = env
    set_model(reword(bad))
    body = post(c, f"reword this: {ORIGINAL}")
    assert body["checks"]["fallback"] is True and body["reword"] is None


def test_a_bad_first_reword_is_fixed_on_the_regeneration(env):
    c, set_model = env
    good = "I think the writing is sloppy and the baseline is weak."
    set_model(reword("I think the baseline is poor and the writing is sloppy."), reword(good))
    body = post(c, f"tighten this: {ORIGINAL}")
    assert body["checks"] == {"attempts": 2, "fallback": False} and body["reword"]["text"] == good


def test_reword_must_start_from_the_reviewers_own_text(env):
    c, set_model = env
    set_model(reword("The authors miss a baseline.", original="The authors miss a baseline."))
    assert post(c, "reword my weakness comment")["checks"]["fallback"] is True


def test_reword_can_start_from_a_note_already_in_the_draft(env):
    c, set_model = env
    add_note(7, "weaknesses", "The baseline is weak and the writing is sloppy, I think.")
    new = "I think the baseline is weak and the writing is sloppy."
    set_model(reword(new))
    assert post(c, "reword my second weakness")["reword"]["text"] == new


def test_reword_numbers_and_negations_are_kept(env):
    assert cc.stance_errors("It is not reproducible: only 5 runs.", "Only 5 runs, and it is reproducible.")
    assert cc.stance_errors("It is not reproducible: only 5 runs.", "It is not reproducible: only 6 runs.")
    assert not cc.stance_errors("It is not reproducible: only 5 runs.", "Only 5 runs; it is not reproducible.")


# ------------------------------------------------------------------ (c) gap reports

def test_what_is_missing_lists_every_gap_at_once_without_calling_the_model(env):
    c, set_model = env
    model = set_model(stated(), {"reply": "Sure."})
    add_note(11, "weaknesses", "Five participants per region seems low")                 # cites nothing
    add_note(12, "weaknesses", "Section 4 reports a single run per setting")             # cites a section
    add_note(13, "strengths", "Clear dataset description")
    post(c, "I think the sample of regions is not broad enough")                          # a view, never captured
    n = len(model.calls)
    body = post(c, "what's missing?")
    assert len(model.calls) == n and body["checks"]["attempts"] == 0                      # no model call
    text = body["reply"]
    assert "Required, nothing in it yet:" in text and "Paper summary" in text and "Soundness" in text
    assert "Five participants per region seems low" in text and "doesn't point to a section" in text
    assert "Section 4 reports a single run" not in text                                   # that one cites a section
    g = body["gaps"]
    assert [u["text"] for u in g["uncited"]] == ["Five participants per region seems low"]
    assert any(i["id"] == "comments" or i["id"] == "ethics" for i in g["optional_open"])


def test_a_gap_report_includes_what_was_said_earlier_but_never_made_it_into_the_draft(env):
    c, set_model = env
    set_model(stated(reply="Table 2 has the per-region counts (Section 4)."), {"reply": "Sure."})
    post(c, f"I think {VIEW}.")
    g = post(c, "what am I missing?")["gaps"]
    assert [u["text"] for u in g["uncaptured"]] == [VIEW]


def test_a_captured_view_is_not_reported_as_missing(env):
    c, set_model = env
    set_model(stated(), {"reply": "Added."})
    post(c, f"I think {VIEW}.")
    post(c, "yes")
    assert post(c, "any gaps?")["gaps"]["uncaptured"] == []


def test_a_rejected_view_is_not_reported_as_missing(env):
    c, set_model = env
    set_model(stated(), {"reply": "Okay."})
    post(c, f"I think {VIEW}.")
    post(c, "no")
    assert post(c, "any gaps?")["gaps"]["uncaptured"] == []


def test_the_model_can_ask_for_the_gap_report_in_other_words(env):
    c, set_model = env
    set_model({"reply": "One moment.", "intent": "gap_report"})
    body = post(c, "show me the holes in my review so far")
    assert body["gaps"] is not None and "Required, nothing in it yet:" in body["reply"]


def test_nothing_open_is_said_plainly(env):
    c, _ = env
    rs = {"sections": [{"id": "a", "name": "A", "required": True, "type": "text"}], "addressed": {"a": True},
          "skipped": {}, "notes": [], "views": {}, "promised": []}
    assert coverage.gap_text(coverage.gap_report(rs)).startswith("Nothing is open right now")


def test_gap_reports_vary_their_opening(env):
    rs = {"sections": [{"id": "a", "name": "A", "required": True, "type": "text"}], "addressed": {},
          "skipped": {}, "notes": [], "views": {}, "promised": []}
    openers = {coverage.gap_text(coverage.gap_report(rs), i).split("\n")[0] for i in range(3)}
    assert len(openers) == 3


def test_gap_reports_evaluate_nothing_about_the_paper(env):
    c, set_model = env
    add_note(11, "weaknesses", "Five participants per region seems low")
    text = post(c, "what's missing?")["reply"]
    outside_quotes = re.sub(r"“[^”]*”", " ", text)
    assert not BANNED.search(outside_quotes) and not cc.JUDGE.search(outside_quotes)
    assert cc.reply_errors(text, {"reviewer_text": "five participants per region seems low"}) == []


# ------------------------------------------------------------------ (d) paper-conflict notes

CONFLICT_VIEW = "Table 2 reports accuracy of 80 on SST-2"
POINTERS = {"pointers": [{"kind": "contradicts", "reviewer_phrase": "accuracy of 80 on SST-2", "span_id": "s4",
                          "paper_quote": "accuracy of 71.2 on SST-2", "explanation": "The paper gives 71.2."}]}


def test_a_conflict_with_the_paper_is_a_neutral_non_blocking_note(env, monkeypatch):
    c, set_model = env
    monkeypatch.setattr(pointers, "_chat", lambda msgs: json.dumps(POINTERS))
    set_model(stated(view=CONFLICT_VIEW, section="comments", reply="Noted. Want me to add that to the Comments section?"))
    body = post(c, f"{CONFLICT_VIEW}.")
    [note] = body["conflicts"]
    assert note["text"] == ("Section 4 Experiments (line 80) states “accuracy of 71.2 on SST-2”; your note says "
                            "“accuracy of 80 on SST-2”. Want to check?")
    assert body["reply"].endswith(note["text"]) and body["capture"]["text"] == CONFLICT_VIEW   # the capture still stands
    for word in ("wrong", "incorrect", "mistake", "error", "false", "inaccurate"):
        assert word not in note["text"].lower()
    assert cc.reply_errors(note["text"], {"reviewer_text": CONFLICT_VIEW}) == []


def test_the_conflict_check_failing_changes_nothing(env, monkeypatch):
    c, set_model = env

    def boom(msgs):
        raise RuntimeError("down")
    monkeypatch.setattr(pointers, "_chat", boom)
    set_model(stated(view=CONFLICT_VIEW, section="comments", reply="Noted. Want me to add that to the Comments section?"))
    body = post(c, f"{CONFLICT_VIEW}.")
    assert body["conflicts"] == [] and body["capture"] is not None and body["checks"]["fallback"] is False


def test_an_answer_pointer_is_not_a_conflict_note(env, monkeypatch):
    c, set_model = env
    p = json.loads(json.dumps(POINTERS))
    p["pointers"][0]["kind"] = "answers"
    monkeypatch.setattr(pointers, "_chat", lambda msgs: json.dumps(p))
    set_model(stated(view=CONFLICT_VIEW, section="comments", reply="Noted. Want me to add that to the Comments section?"))
    assert post(c, f"{CONFLICT_VIEW}.")["conflicts"] == []


# ------------------------------------------------------------------ (e) drafting is never blocked

def fake_drafter(monkeypatch):
    """A stand-in for the drafting model: one sentence per note, citing it, and an audit that passes."""
    def fake(msgs):
        system, user = msgs[0]["content"], msgs[-1]["content"]
        if "audit sentences" in system.lower():
            return json.dumps({"results": []})
        rows = re.findall(r"^\[(\S+)\] (.+)$", user, re.M)
        return json.dumps({"sentences": [{"text": t, "src": [k]} for k, t in rows]})
    monkeypatch.setattr(synth, "_chat", fake)


def test_draft_it_drafts_the_sections_that_have_content_and_leaves_the_rest(env, monkeypatch):
    c, set_model = env
    fake_drafter(monkeypatch)
    model = set_model({"reply": "unused"})
    add_note(21, "weaknesses", "Five participants per region seems low")
    body = post(c, "draft it")
    assert body["drafted"]["drafted"] == ["Summary of weaknesses"] and "Summary of strengths" in body["drafted"]["empty"]
    assert "Summary of weaknesses" in body["reply"] and "left those empty" in body["reply"]
    assert body["draft_changed"] is True and not model.calls
    assert [s["text"] for s in c.get("/draft/p1").json()["weaknesses"]["sentences"]] == ["Five participants per region seems low"]


def test_drafting_works_with_every_required_part_missing(env, monkeypatch):
    c, _ = env
    fake_drafter(monkeypatch)
    add_note(21, "comments", "Typo in the abstract")
    assert synth.missing_required("p1")                                   # required parts are missing
    body = post(c, "write it up")
    assert body["drafted"]["drafted"] == ["Comments, suggestions and typos"]


def test_an_empty_review_gets_a_plain_answer_not_an_error(env, monkeypatch):
    c, _ = env
    fake_drafter(monkeypatch)
    body = post(c, "draft my review")
    assert body["drafted"] == {"drafted": [], "empty": list(synth.names().values())}
    assert "nothing in your review yet" in body["reply"] and body["draft_changed"] is False
    assert c.get("/draft/p1").json() == {}


def test_drafting_is_not_blocked_by_a_paper_conflict(env, monkeypatch):
    c, _ = env
    fake_drafter(monkeypatch)
    monkeypatch.setattr(pointers, "_chat", lambda msgs: json.dumps(POINTERS))
    add_note(21, "weaknesses", CONFLICT_VIEW)
    assert post(c, "draft it")["drafted"]["drafted"] == ["Summary of weaknesses"]


def test_the_old_flows_draft_gate_is_unchanged(env, monkeypatch):
    c, _ = env
    monkeypatch.setattr(pointers, "_chat", lambda msgs: json.dumps({"pointers": []}))
    add_note(21, "comments", "Typo in the abstract")
    out = synth.make_draft("p1", [], "smooth")
    assert out["blocked"] is True and out["missing"]                      # the old gate still blocks; chat does not use it


def test_a_draft_request_can_come_from_the_model_in_other_words(env, monkeypatch):
    c, set_model = env
    fake_drafter(monkeypatch)
    add_note(21, "weaknesses", "Five participants per region seems low")
    set_model({"reply": "On it.", "intent": "draft"})
    assert post(c, "assemble what I have into a review")["drafted"]["drafted"] == ["Summary of weaknesses"]
