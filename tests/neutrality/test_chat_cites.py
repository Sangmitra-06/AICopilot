"""POST /chat/{pid} returns the spans a reply cites, with the markers turned into plain pointers.

The neutrality checks run on the reply after the markers are stripped (and on the marker-free text), so removing a
marker can never let a blocked sentence through. A reply that cites nothing, and every reply the app writes itself
(gap report, draft, fallback), returns no cites, so the PDF does not move.
"""
import json
import re

import pytest

from app import chat_checks as cc, chatflow, cites
from conftest import PAPER, make_reviewer

ASK = {"reviewer_id": "rev", "message": "where do they report accuracy?"}


@pytest.fixture
def env(chat_env):
    c, set_model = chat_env
    make_reviewer("rev")
    return c, set_model


def chat(c, message="where do they report accuracy?"):
    r = c.post("/chat/p1", json={"reviewer_id": "rev", "message": message})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_cited_span_comes_back_with_where_to_find_it_and_no_marker_in_the_text(env):
    c, set_model = env
    set_model({"reply": "Table 2 reports accuracy on SST-2 and CoLA [s4]."})
    body = chat(c)
    assert body["reply"] == "Table 2 reports accuracy on SST-2 and CoLA (Section 4)."
    assert [x["id"] for x in body["cites"]] == ["s4"]
    assert body["cites"][0]["page"] == 4 and body["cites"][0]["section"] == "4 Experiments"
    assert "[" not in body["reply"] and "s4" not in body["reply"]
    assert "".join(p["text"] for p in body["parts"]) == body["reply"]
    assert [p["cite"] for p in body["parts"] if p["cite"]] == [["s4"]]


def test_prose_replies_cite_too(env):
    c, set_model = env
    set_model("Training is described under the method [s3], and the numbers under experiments [s4].")
    body = chat(c)
    assert [x["id"] for x in body["cites"]] == ["s3", "s4"]
    assert body["reply"].endswith("experiments (Section 4).")


def test_unknown_ids_are_dropped_from_cites_and_from_the_text(env):
    c, set_model = env
    set_model({"reply": "Accuracy is in Table 2 [s4] and a made-up place [s77]."})
    body = chat(c)
    assert [x["id"] for x in body["cites"]] == ["s4"]
    assert "s77" not in body["reply"] and "[" not in body["reply"]


def test_only_unknown_ids_means_nothing_is_cited(env):
    c, set_model = env
    set_model({"reply": "Accuracy is somewhere [s77]."})
    body = chat(c)
    assert body["cites"] == [] and body["parts"] is None and body["reply"] == "Accuracy is somewhere."


@pytest.mark.parametrize("reply", ["Happy to look at that with you.", "A probe is a small classifier trained on frozen features."])
def test_a_reply_that_cites_nothing_returns_no_cites(env, reply):
    c, set_model = env
    set_model({"reply": reply})
    body = chat(c)
    assert body["cites"] == [] and body["parts"] is None and body["reply"] == reply


def test_the_references_are_not_citable(env):
    c, set_model = env
    set_model({"reply": "That is listed at the end [s5]."})
    assert chat(c)["cites"] == []


def test_a_gap_report_cites_nothing_even_if_the_model_put_a_marker_in_its_line(env):
    c, set_model = env
    set_model({"reply": "Here is what is left [s4].", "intent": "gap_report"})
    body = chat(c, "what is the review missing?")
    assert body["gaps"] is not None and body["cites"] == [] and body["parts"] is None
    assert "[" not in body["reply"] and "(Section" not in body["reply"]


def test_asking_for_the_gap_report_by_words_cites_nothing(env):
    c, set_model = env
    body = chat(c, "what's missing?")
    assert body["gaps"] is not None and body["cites"] == [] and body["parts"] is None


def test_a_draft_cites_nothing(env):
    c, set_model = env
    body = chat(c, "draft it")
    assert body["cites"] == [] and body["parts"] is None


def test_the_fallback_cites_nothing(env):
    c, set_model = env
    set_model({"reply": "This paper is clearly a strong submission [s4]."})   # blocked twice
    body = chat(c)
    assert body["checks"]["fallback"] is True and body["cites"] == [] and body["parts"] is None
    assert "[" not in body["reply"]


# ------------------------------------------------------------------ neutrality checks see the reply without markers

SPLIT = "The experiments [s4] are convincing."


def test_a_marker_cannot_split_a_blocked_phrase(env):
    """The text the reviewer would read, "The experiments (Section 4) are convincing.", and the marker-free text are both
    checked; the marker-free one reads "The experiments are convincing." and is blocked."""
    c, set_model = env
    model = set_model({"reply": SPLIT}, {"reply": "Table 2 has the numbers [s4]."})
    body = chat(c)
    assert body["checks"]["attempts"] == 2 and body["checks"]["fallback"] is False     # the first was refused, the retry passed
    assert "convincing" not in body["reply"] and [x["id"] for x in body["cites"]] == ["s4"]
    assert len(model.calls) == 2


def test_a_blocked_sentence_stays_blocked_with_or_without_the_marker():
    spans = PAPER
    with_marker = chatflow.checked_errors(SPLIT, {"reviewer_text": ""}, spans)
    without = cc.reply_errors("The experiments are convincing.", {"reviewer_text": ""})
    assert without and with_marker                                                      # both blocked
    shown = cites.extract(SPLIT, spans)[0]
    assert shown == "The experiments (Section 4) are convincing."
    assert set(without) <= set(with_marker)                                             # nothing the bare text trips is lost


@pytest.mark.parametrize("reply", [
    "The method is [s3]novel and [s99]well motivated.",
    "This is a novel [s2] contribution.",
    "These results [s4] are clearly strong.",
])
def test_blocked_replies_stay_blocked_whatever_markers_are_in_them(reply):
    assert chatflow.checked_errors(reply, {"reviewer_text": ""}, PAPER)
    bare = re.sub(r" ?\[[\w-]+\] ?", " ", reply)                                       # the same sentence, no markers at all
    assert cc.reply_errors(bare, {"reviewer_text": ""})


def test_a_clean_reply_with_markers_passes_the_checks():
    assert chatflow.checked_errors("Table 2 has the numbers [s4], training is under [s3].", {"reviewer_text": ""}, PAPER) == []


# ------------------------------------------------------------------ the prompt, the stored thread

def test_the_prompt_says_to_cite_only_what_the_reply_refers_to_and_never_to_support_an_evaluation(env):
    c, set_model = env
    model = set_model({"reply": "Okay."})
    chat(c)
    s = model.system
    assert "POINTING AT THE PAPER" in s and "[p3-s2]" in s
    assert "only when your reply refers to it" in s and "never to support an evaluation" in s
    assert "[s4]" in s                                                                  # the paper text carries the labels


def test_a_reload_gets_the_same_pointers_from_the_thread(env):
    c, set_model = env
    set_model({"reply": "Table 2 reports accuracy [s4]."})
    chat(c)
    last = c.get("/thread/p1").json()[-1]
    assert last["role"] == "assistant" and last["text"] == "Table 2 reports accuracy (Section 4)."
    assert last["meta"]["cites"] == ["s4"]
    assert "".join(p["text"] for p in last["meta"]["parts"]) == last["text"]
    assert "[s4]" not in json.dumps(last["text"])


def test_a_note_appended_to_a_reply_does_not_break_the_pointers(env, monkeypatch):
    c, set_model = env
    monkeypatch.setattr(chatflow, "conflict_notes", lambda text, spans: [{"text": "Note: the paper says otherwise."}])
    set_model({"reply": "Table 2 reports the accuracy [s4]. Noted; I can add that to your weaknesses.", "views": [
        {"text": "The accuracy is lower than I expected", "section": "weaknesses"}]})
    body = chat(c, "The accuracy is lower than I expected")
    if body["capture"]:                                                                  # the offer path appended the note
        assert body["reply"].endswith("Note: the paper says otherwise.")
        assert "".join(p["text"] for p in body["parts"]) == body["reply"]
