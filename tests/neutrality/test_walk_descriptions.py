"""Item 3: the opening and every walk step show a short DESCRIPTIVE paragraph about the section, not just a pointer.

  * before_reading: a summary of at most three sentences, then "You said you like to start with the intro, then the methods, so here's the intro."
    plus a description of the intro.
  * "next" (intro, then methods): "You said you like to read the intro first and then the methods, so let's go to the methods now." plus a description of the methods; the cites are
    that section's passages, so the PDF moves there every time.
  * one pointer per sentence; a pointer that would repeat the previous sentence's is not shown twice.
  * the description goes through the normal neutrality checks; if none can be made the app's plain pointer line is shown
    (never the generic fallback).
"""
import re

import pytest

from app import chat_checks as cc, store, walk
from app.verify import BANNED
from test_walk_advance import env, rich, say, start, sections_cited, pointer   # noqa: F401

INTRO = ("This section introduces the task and states the contributions [p2-s1]. It says the authors build a probing "
         "dataset [p2-s2].")
METHOD = ("The authors describe training with weak supervision [p4-s1]. They define the probe and its layers [p4-s2] "
          "and the loss [p4-s1].")


def pointers(text):
    return re.findall(r"\((?:Sections? [\d., ]+|[A-Z][\w ;.-]*)\)", text)


def sentence_list(text):
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def test_the_opening_names_the_reviewers_word_and_describes_the_section(env):
    c, set_model = env
    set_model({"reply": INTRO})
    make = start(c)
    msg = make["messages"][-1]
    assert msg["kind"] == "section"
    first, _, rest = msg["reply"].partition("\n\n")
    assert first == "You said you like to start with the intro, then the methods, so here's the intro."   # no pointer on the app's line
    assert "(Section 1)" in rest and "[p" not in msg["reply"]
    assert "introduces the task" in rest
    assert {x["section"] for x in msg["cites"]} == {"1 Introduction"}
    assert walk.GUIDE_HINT in msg["reply"]


def test_next_shows_a_description_of_the_next_section_and_moves_the_pdf(env):
    c, set_model = env
    set_model({"reply": INTRO})
    start(c)
    model = set_model({"reply": METHOD})
    body = say(c, "next")
    lead, _, desc = body["reply"].partition("\n\n")
    assert lead == "You said you like to read the intro first and then the methods, so let's go to the methods now."
    assert "weak supervision" in desc and "(Section 3)" in desc
    assert sections_cited(body) == {"3 Method"} and body["cites"][0]["page"] == 4
    assert body["parts"] and any(p["cite"] for p in body["parts"])
    assert len(model.calls) == 1 and pointer() == 1


def test_every_next_moves_to_the_new_section_never_the_old_one(env):
    c, set_model = env
    set_model({"reply": INTRO})
    start(c)
    seen = []
    for sec_ids in ({"3 Method": METHOD}, {"4 Experiments": "The authors report their experiments [p5-s1]."}):
        (title, reply), = sec_ids.items()
        set_model({"reply": reply})
        body = say(c, "next")
        assert sections_cited(body) == {title}
        seen.append(title)
    assert seen == ["3 Method", "4 Experiments"]


def test_one_pointer_per_sentence_and_no_doubled_pointers(env):
    c, set_model = env
    set_model({"reply": "The authors build a dataset [p2-s1] [p2-s2] and say why [p2-s1]. They list aims [p2-s2]. "
                        "Then they state the setup [p2-s1]."})
    msg = start(c)["messages"][-1]
    desc = msg["reply"].split("\n\n")[1]
    for s in sentence_list(desc):
        assert len(pointers(s)) <= 1, s
    assert "(Section 1)(Section 1)" not in msg["reply"].replace(" ", "")
    assert len(pointers(desc)) == 1                                                  # the same pointer is not repeated
    assert {x["id"] for x in msg["cites"]} == {"p2-s1", "p2-s2"}                     # but the spans are all still marked


def test_at_most_three_sentences_in_a_description(env):
    c, set_model = env
    set_model({"reply": "One [p2-s1]. Two [p2-s2]. Three [p2-s1]. Four [p2-s2]. Five [p2-s1]."})
    desc = start(c)["messages"][-1]["reply"].split("\n\n")[1]
    assert len(sentence_list(desc)) == 3


def test_passages_of_other_sections_are_not_cited(env):
    c, set_model = env
    set_model({"reply": "The authors describe a probe [p4-s1]. They report numbers [p5-s1]."})
    msg = start(c)["messages"][-1]
    assert all(x["section"] == "1 Introduction" for x in msg["cites"])


def test_a_description_that_judges_is_rejected_and_the_plain_pointer_line_is_shown(env):
    c, set_model = env
    model = set_model({"reply": "This is a novel and strong introduction [p2-s1]."})
    msg = start(c)["messages"][-1]
    assert len(model.calls) == 2                                                     # regenerated once
    assert not BANNED.search(msg["reply"]) and cc.FALLBACK not in msg["reply"]
    assert msg["reply"].startswith("You said you like to start with the intro, then the methods, so here's the intro (Section 1).")
    assert {x["section"] for x in msg["cites"]} == {"1 Introduction"}


def test_a_down_model_leaves_the_plain_pointer_line_for_a_step(env, monkeypatch):
    c, set_model = env
    set_model({"reply": INTRO})
    start(c)
    from app import chatflow

    def boom(msgs):
        raise RuntimeError("model down")
    monkeypatch.setattr(chatflow, "_chat", boom)
    body = say(c, "next")
    assert body["reply"].startswith("You said you like to read the intro first and then the methods, so let's go to the methods now (Section 3).")
    assert sections_cited(body) == {"3 Method"}


def test_the_summary_is_at_most_three_sentences_with_one_pointer_each(env):
    from test_walk_opening import before
    c, set_model = env
    before()
    set_model({"reply": "The authors study probing [p1-s1]. They add a dataset [p2-s1]. They report scores [p5-s1]. "
                        "They add more [p2-s2]. And more [p2-s1]."}, {"reply": INTRO})
    body = c.post("/chat/p1/open", json={"reviewer_id": "rev"}).json()
    summary = body["messages"][0]
    descriptive = summary["reply"].split("\n\n")[1]            # between the app's friendly lead-in and close
    assert summary["kind"] == "summary" and len(sentence_list(descriptive)) <= 3
    for s in sentence_list(summary["reply"]):
        assert len(pointers(s)) <= 1
