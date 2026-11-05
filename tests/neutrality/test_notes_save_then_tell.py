"""Save-then-tell for notes (fix item 5).

The real session: the reviewer pasted a sentence of the opening summary, said "add all of it", stated a view, asked to
save it also as a strength, then to move it to "the strenghts", and finally "I want you to add thes ummary I dont see that
yet": nothing they asked for was in the Review draft. Now a statement is saved right away in the reviewer's exact words,
in the best-fitting section, and the app says "Saved under <section>. Say 'move it' if that's wrong."; "also add it to
...", "put it in ...", "add the summary" / "add all of it" (the app's own text, labeled as drafted from the paper's
claims) and "undo" act on it. Only the app says where something went, and only after the note is in GET /notes.

The replay below uses the session's exact messages and the session's real opening summary; GET /notes after each one is
also written to tests/chat/fixtures/session_notes.json, which the panel test (tests/chat/draft.test.mjs) renders.
"""
import json
import os
import re

import pytest

from app import notecmd, store, synth
from conftest import make_reviewer

# A STAND-IN for the session's opening summary (the paper is under review: none of its text is kept here),
# three descriptive sentences with markers for this test paper, as the model wrote it.
SESSION_SUMMARY = (
    "The authors report probing syntax in three pretrained encoders with linear and MLP probes, using sentences from an "
    "automatically parsed corpus [s1]. They state that syntactic information peaks in the middle layers, and that probe "
    "accuracy drops by 4–9% when control tasks are used [s2]. They further report that larger encoders show the same "
    "layer pattern, and that probe capacity changes accuracy by less than 2% across settings [s4].")
STATEMENT = "it is very sound in methodology, I like the probing and teh ablation combination"
FIXTURE = os.path.join(os.path.dirname(__file__), "..", "chat", "fixtures", "session_notes.json")


def say(c, message):
    r = c.post("/chat/p1", json={"reviewer_id": "rev", "message": message})
    assert r.status_code == 200, r.text
    return r.json()


def notes(c):
    r = c.get("/notes/p1")
    assert r.status_code == 200
    return r.json()


def where(c):
    names = synth.names()
    return sorted((names.get(n["field"], n["field"]), n["text"], n.get("label")) for n in notes(c))


def open_paper(c, set_model):
    make_reviewer("rev", summary_preference="yes and I want it before I read", summary_preference__value="before_reading")
    set_model({"reply": SESSION_SUMMARY}, {"reply": "plain"})        # the summary; the section description fails quietly
    body = c.post("/chat/p1/open", json={"reviewer_id": "rev"}).json()
    summary = body["messages"][0]["reply"]
    shown = summary.split("\n\n")[1]                                   # what the reviewer read, pointers and all
    return shown


def test_the_session_replayed_message_by_message(chat_env):
    c, set_model = chat_env
    shown = open_paper(c, set_model)
    first_sentence = shown.split(". They state")[0] + "."
    full = " ".join(shown.split())
    snapshots = []

    def step(message, model_reply, expect_line, expect_notes):
        set_model(model_reply)
        before = where(c)
        body = say(c, message)
        got = where(c)
        assert got == sorted(expect_notes), (message, got)
        assert body["reply"].endswith(expect_line) or expect_line in body["reply"], (message, body["reply"])
        assert body["draft_changed"] is (got != before), message       # the panel reloads whenever a note changed
        snapshots.append({"message": message, "reply": body["reply"],
                          "notes": [{"id": k, "field": n["field"], "text": n["text"], "label": n.get("label")}
                                    for k, n in enumerate(sorted(notes(c), key=lambda n: (n["field"], n["text"])))]})
        return body

    # 1. the summary sentence, pasted: saved right away, their exact words, best-fitting section
    step(first_sentence, {"reply": "Okay, that sentence is from the opening summary.",
                          "views": [{"text": first_sentence, "section": "summary"}]},
         "Saved under Paper summary. Say “move it” if that's wrong.",
         [("Paper summary", first_sentence, None)])
    # 2. "add all of it": the whole summary the app wrote, labeled; the pasted sentence becomes the whole text
    step("add all of it", None, "Added to Paper summary, marked as drafted from the paper's claims.",
         [("Paper summary", full, notecmd.CLAIMS_LABEL)])
    # 3. a statement; the model's own "Added to ..." claim never reaches the reviewer
    b = step(STATEMENT, {"reply": "Added to Soundness, in your own words. The probing and ablation are described in "
                                  "Section 3.", "views": [{"text": STATEMENT, "section": "soundness"}]},
             "Saved under Soundness. Say “move it” if that's wrong.",
             [("Paper summary", full, notecmd.CLAIMS_LABEL), ("Soundness", STATEMENT, None)])
    assert b["reply"].count("Soundness") == 1 and "Added to" not in b["reply"]
    # 4. "yeah and also as a strength": a second copy, in Summary of strengths
    step("yeah and also as a strength", None, "Also saved under Summary of strengths.",
         [("Paper summary", full, notecmd.CLAIMS_LABEL), ("Soundness", STATEMENT, None),
          ("Summary of strengths", STATEMENT, None)])
    # 5. "I want it to go in the strenghts" (typo): it is in strengths only
    step("I want it to go in the strenghts", None, "Moved to Summary of strengths.",
         [("Paper summary", full, notecmd.CLAIMS_LABEL), ("Summary of strengths", STATEMENT, None)])
    # 6. "I want you to add thes ummary I dont see that yet": it is there, and the app says so
    step("I want you to add thes ummary I dont see that yet", None,
         "That's already under Paper summary, marked as drafted from the paper's claims.",
         [("Paper summary", full, notecmd.CLAIMS_LABEL), ("Summary of strengths", STATEMENT, None)])

    data = {"criteria": [{"id": i, "name": n} for i, n in synth.names().items()], "steps": snapshots}
    if os.environ.get("UPDATE_SESSION_FIXTURE"):
        os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
        with open(FIXTURE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    with open(FIXTURE, encoding="utf-8") as f:
        assert json.load(f) == data, "the panel fixture is out of date: rerun with UPDATE_SESSION_FIXTURE=1"


def test_commands_are_answered_by_the_app_without_a_model_call(chat_env):
    c, set_model = chat_env
    open_paper(c, set_model)
    set_model({"reply": "Okay.", "views": [{"text": STATEMENT, "section": "soundness"}]})
    say(c, STATEMENT)
    model = set_model({"reply": "should not be asked"})
    for m in ("yeah and also as a strength", "I want it to go in the strenghts", "undo", "add all of it"):
        say(c, m)
    assert model.calls == []


def test_the_model_never_writes_where_a_note_went(chat_env):
    c, set_model = chat_env
    open_paper(c, set_model)
    set_model({"reply": "Saved under Summary of strengths. I've added that to your draft. Section 3 describes the "
                        "probing.", "views": [{"text": STATEMENT, "section": "soundness"}]})
    reply = say(c, STATEMENT)["reply"]
    assert "Summary of strengths" not in reply and "I've added" not in reply
    assert reply.endswith("Saved under Soundness. Say “move it” if that's wrong.")


def test_a_prose_reply_still_saves_through_the_extraction_call(chat_env):
    c, set_model = chat_env
    open_paper(c, set_model)
    set_model("The probing and ablation are described in Section 3.", f"VIEW | soundness | {STATEMENT}")
    reply = say(c, STATEMENT)["reply"]
    assert where(c)[-1] == ("Soundness", STATEMENT, None)
    assert reply.endswith("Saved under Soundness. Say “move it” if that's wrong.")


# ------------------------------------------------------------------ move, also, undo

@pytest.fixture
def saved(chat_env):
    c, set_model = chat_env
    open_paper(c, set_model)
    set_model({"reply": "Okay.", "views": [{"text": STATEMENT, "section": "soundness"}]})
    say(c, STATEMENT)
    return c, set_model


def test_move_it_asks_where_and_the_next_message_moves_it(saved):
    c, _ = saved
    ask = say(c, "move it")["reply"]
    assert ask.startswith("Which section should it go under?") and "Summary of weaknesses" in ask
    assert say(c, "weaknesses")["reply"] == "Moved to Summary of weaknesses."
    assert where(c)[-1] == ("Summary of weaknesses", STATEMENT, None)


def test_put_it_in_a_section_moves_it(saved):
    c, _ = saved
    assert say(c, "put it in strengths")["reply"] == "Moved to Summary of strengths."
    assert [w for w in where(c) if w[1] == STATEMENT] == [("Summary of strengths", STATEMENT, None)]


@pytest.mark.parametrize("command,undone", [
    ("put it in strengths", "Undone: it's back under Soundness."),
    ("yeah and also as a strength", "Undone: I removed it from Summary of strengths."),
])
def test_undo_reverts_the_last_change(saved, command, undone):
    c, _ = saved
    before = where(c)
    say(c, command)
    assert say(c, "undo")["reply"] == undone
    assert where(c) == before


def test_undo_a_saved_statement_removes_it(saved):
    c, _ = saved
    assert say(c, "undo")["reply"] == "Undone: I removed it from Soundness."
    assert not [w for w in where(c) if w[1] == STATEMENT]


def test_undo_add_all_of_it_puts_the_pasted_sentence_back(chat_env):
    c, set_model = chat_env
    shown = open_paper(c, set_model)
    sentence = shown.split(". They state")[0] + "."
    set_model({"reply": "Okay.", "views": [{"text": sentence, "section": "summary"}]})
    say(c, sentence)
    say(c, "add all of it")
    say(c, "undo")
    assert where(c) == [("Paper summary", sentence, None)]


def test_add_the_summary_with_nothing_to_add_says_so_and_saves_nothing(chat_env):
    c, set_model = chat_env
    make_reviewer("rev")                                       # no summary wanted: the app never wrote one
    set_model({"reply": "plain"})
    c.post("/chat/p1/open", json={"reviewer_id": "rev"})
    reply = say(c, "add the summary")["reply"]
    assert reply == notecmd.NOTHING_TO_ADD and notes(c) == []


def test_add_the_summary_into_a_named_section(chat_env):
    c, set_model = chat_env
    open_paper(c, set_model)
    assert say(c, "add the summary to comments")["reply"] == \
        "Added to Comments, suggestions and typos, marked as drafted from the paper's claims."


def test_a_summary_the_reviewer_asked_for_in_chat_can_be_added(chat_env):
    c, set_model = chat_env
    make_reviewer("rev")
    set_model({"reply": "plain"})
    c.post("/chat/p1/open", json={"reviewer_id": "rev"})
    set_model({"reply": "The authors say they study probing of syntax in pretrained encoders [s1]."})
    say(c, "can you give me a summary of the paper?")
    assert say(c, "add the summary")["reply"].startswith("Added to Paper summary")
    assert where(c) == [("Paper summary", "The authors say they study probing of syntax in pretrained encoders "
                                          "(Abstract).", notecmd.CLAIMS_LABEL)]


def test_the_draft_text_the_model_sees_marks_the_apps_summary_as_not_the_reviewers(chat_env):
    from app import chatflow
    c, set_model = chat_env
    open_paper(c, set_model)
    say(c, "add the summary")
    assert "not the reviewer's words" in chatflow.draft_text("p1")


# ------------------------------------------------------------------ reading the commands

SECTIONS = [{"id": i, "name": n} for i, n in {"summary": "Paper summary", "strengths": "Summary of strengths",
                                               "weaknesses": "Summary of weaknesses", "soundness": "Soundness",
                                               "comments": "Comments, suggestions and typos"}.items()]


@pytest.mark.parametrize("message,expected", [
    ("add all of it", ("add", "all", None)),
    ("yeah and also as a strength", ("also", "strengths")),
    ("also add it to the summary", ("also", "summary")),
    ("I want it to go in the strenghts", ("move", "strengths")),
    ("I want you to add thes ummary I dont see that yet", ("add", "summary", "summary")),
    ("add the summary", ("add", "summary", "summary")),
    ("move it", ("move", None)),
    ("put it under weaknesses", ("move", "weaknesses")),
    ("no, that belongs in weaknesses", ("move", "weaknesses")),
    ("undo", ("undo",)),
    ("undo that", ("undo",)),
])
def test_commands(message, expected):
    assert notecmd.read(message, SECTIONS) == expected


@pytest.mark.parametrize("message", [
    STATEMENT,
    "I also think the baselines are weak as a weakness",
    "I would put that down to the small dataset",
    "The authors add a summary of results",
    "what is the summary?",
    "don't add the summary",
    "ok", "next", "yes",
])
def test_statements_and_questions_are_not_commands(message):
    assert notecmd.read(message, SECTIONS) is None


def test_the_apps_lines_say_nothing_about_the_paper():
    from app import walk
    for line in (notecmd.saved_line(["Soundness"]), notecmd.also_line("Summary of strengths"),
                 notecmd.moved_line("Summary of strengths"), notecmd.proposal_line("Paper summary"),
                 notecmd.already_line("Paper summary"), notecmd.undo_line("moved", "Soundness"), notecmd.NOTHING_TO_ADD,
                 notecmd.NOTHING_SAVED):
        assert not walk.rates(line.replace("Soundness", "")), line


@pytest.mark.parametrize("message", ["Yes lets add it as my sentence", "yeah add that to my draft please", "sure, add it"])
def test_a_request_to_add_is_not_sent_to_the_extraction_call_as_a_statement(message):
    from app import chatflow
    assert chatflow.looks_like_view(message) is False
