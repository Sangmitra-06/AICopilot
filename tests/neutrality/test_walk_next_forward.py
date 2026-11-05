""""next" jumped back to the Abstract (real session).

Reading order "introduction, then the methods", opening summary on. The walk went intro, then methods (Section 3); after a
few messages inside the methods the assistant said "Say next for Section 3.4", the reviewer said "next", and the walk went
to the Abstract.

Cause: parse_reading_order puts the sections the reviewer named first and then EVERY other section in plain paper order,
and walk.next_index took the first one not yet shown after the pointer. After the last named section that is the
Abstract (and then 2 Related Work), both earlier in the paper. The walk also never looked at what the assistant had just
offered.

Fix: "next" never goes to a section the reviewer did not name that is earlier in the paper than the current one or the last
one they named; after the named ones it continues in paper order from there, skipping anything already shown. When the
assistant's last reply offered a specific next piece ("Say next for Section 3.4"), "next" goes exactly there.
"""
import pytest

from app import main, store
from conftest import make_reviewer

LAYOUT = [  # (section, top-level section) as ingest labels the spans; 3 and 4 have no text of their own
    ("Abstract", None), ("1 Introduction", "1 Introduction"), ("2 Related Work", "2 Related Work"),
    ("3.1 Probe Design", "3 Methods"), ("3.2 Training Details", "3 Methods"),
    ("3.3 Control Tasks", "3 Methods"), ("3.4 Layer Selection", "3 Methods"),
    ("4.1 Layer-wise Accuracy", "4 Results"), ("4.2 Probe Capacity", "4 Results"),
    ("5 Discussion", "5 Discussion"), ("6 Conclusion", "6 Conclusion"),
]
PAPER_ORDER = ["Abstract", "1 Introduction", "2 Related Work", "3 Methods", "4 Results", "5 Discussion", "6 Conclusion"]


def spans():
    out = []
    for k, (sec, top) in enumerate(LAYOUT):
        for i in range(2):
            out.append({"id": f"p{k + 1}-s{i + 1}", "text": f"text of {sec} {i}", "page": k + 1, "lines": [i, i],
                        "section": sec, "top": top, "kind": "body", "bbox": [10, 10 * i, 100, 10 * i + 8],
                        "segs": [(20, i)]})
    return out + [{"id": "ref", "text": "A. Author. 2020.", "page": 20, "lines": [1, 1], "section": "References",
                   "kind": "body", "bbox": [1, 1, 2, 2], "segs": [(10, 1)]}]


SUMMARY = ("The authors say they study probing of syntax [p1-s1]. They describe a probe and control tasks [p4-s1]. "
           "They report layer-wise accuracy [p8-s1].")


@pytest.fixture
def env(chat_env, monkeypatch):
    c, set_model = chat_env
    monkeypatch.setitem(main.CACHE, "p1", spans())
    return c, set_model


def say(c, message):
    r = c.post("/chat/p1", json={"reviewer_id": "rev", "message": message})
    assert r.status_code == 200, r.text
    return r.json()


def cited(body):
    return {x["section"] for x in body["cites"]}


def units(body):
    tops = {s["section"]: s["top"] or s["section"] for s in spans() if s["section"] != "References"}
    return {tops[s] for s in cited(body)}


def session(c, set_model, last_reply="Section 3.2 sets out how the probe is trained (Section 3.2)."):
    """Opening summary, intro, "next" (methods), a few messages inside the methods."""
    make_reviewer("rev", reading_order="introduction, then the methods", reading_order__value="intro_first",
                  summary_preference="Before I read it, please.", summary_preference__value="before_reading")
    set_model({"reply": SUMMARY})
    opened = c.post("/chat/p1/open", json={"reviewer_id": "rev"}).json()
    assert [m["kind"] for m in opened["messages"]] == ["summary", "section"]
    assert units(opened["messages"][1]) == {"1 Introduction"}
    assert store.walk_state("p1")["summarized"] is True
    body = say(c, "next")
    assert units(body) == {"3 Methods"}
    set_model({"reply": "Section 3.1 describes the probe design."})
    say(c, "What is in 3.1?")
    set_model({"reply": last_reply})
    say(c, "And 3.2?")
    assert store.walk_state("p1")["covered"] == ["1 Introduction", "3 Methods"]


def test_next_after_the_methods_never_goes_back_to_the_abstract(env):
    c, set_model = env
    session(c, set_model)
    body = say(c, "next")
    assert "Abstract" not in cited(body) and "2 Related Work" not in units(body)
    assert units(body) == {"4 Results"}                     # paper order, from after the last named section
    assert body["reply"].startswith("Moving to the results")


def test_after_the_named_sections_the_walk_goes_forward_in_paper_order_to_the_end(env):
    c, set_model = env
    session(c, set_model)
    seen = []
    for _ in range(3):
        seen.append(next(iter(units(say(c, "next")))))
    assert seen == ["4 Results", "5 Discussion", "6 Conclusion"]
    assert say(c, "next")["reply"].startswith("That was the last section in your order.")
    covered = store.walk_state("p1")["covered"]
    assert "Abstract" not in covered and "2 Related Work" not in covered


def test_next_never_goes_to_a_section_earlier_than_the_current_one(env):
    c, set_model = env
    session(c, set_model)
    say(c, "go to the discussion")
    body = say(c, "next")
    assert units(body) == {"6 Conclusion"}                  # not 4 Results, which comes before the discussion


@pytest.mark.parametrize("offer", ["Say next for Section 3.4.", "Say “next” for Section 3.4 (Section 3).",
                                   "Say next to go to Section 3.4."])
def test_next_goes_exactly_to_the_piece_the_assistant_just_offered(env, offer):
    c, set_model = env
    session(c, set_model, last_reply="Section 3.2 sets out how the probe is trained. " + offer)
    body = say(c, "next")
    assert cited(body) == {"3.4 Layer Selection"}
    assert "Abstract" not in cited(body)
    after = say(c, "next")                                  # and on from there, forward
    assert units(after) == {"4 Results"}
