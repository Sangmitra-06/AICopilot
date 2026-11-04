"""Loop 6: `return out` sat inside the for loop in pointers.check. Only the first pointer
came back, and when none were accepted the function returned None, which factcheck.run
treats as 'could not check', so the note was re-checked on every request and never cached."""
import json

from app import pointers

S1 = {"id": "s1", "kind": "body", "section": "3 Method", "page": 1, "lines": [12, 12], "segs": [(40, 12)],
      "text": "We recruited 5 participants per region."}
S2 = {"id": "s2", "kind": "body", "section": "3 Method", "page": 1, "lines": [30, 30], "segs": [(50, 30)],
      "text": "The gold answers were written by three annotators."}
NOTE = "They recruited 9 participants per region and the gold answers were written by two annotators."


def ptr(span, phrase, quote, kind="contradicts"):
    return {"kind": kind, "reviewer_phrase": phrase, "span_id": span, "paper_quote": quote,
            "explanation": f"The paper says: {quote}."}


GOOD1 = ptr("s1", "9 participants per region", "5 participants per region")
GOOD2 = ptr("s2", "written by two annotators", "written by three annotators")


def stub(monkeypatch, pointers_list):
    monkeypatch.setattr(pointers, "_chat", lambda msgs: json.dumps({"pointers": pointers_list}))


def test_every_accepted_pointer_is_returned(monkeypatch):
    stub(monkeypatch, [GOOD1, GOOD2])
    out = pointers.check(NOTE, [S1, S2])
    assert [p["span_id"] for p in out] == ["s1", "s2"]
    assert out[0]["lines"] == [12, 12] and out[0]["page"] == 1


def test_a_duplicate_pointer_is_dropped(monkeypatch):
    stub(monkeypatch, [GOOD1, GOOD1, GOOD2])
    assert [p["span_id"] for p in pointers.check(NOTE, [S1, S2])] == ["s1", "s2"]


def test_a_rejected_pointer_does_not_hide_a_later_good_one(monkeypatch):
    bad = ptr("s9", "9 participants per region", "5 participants per region")
    stub(monkeypatch, [bad, GOOD2])
    assert [p["span_id"] for p in pointers.check(NOTE, [S1, S2])] == ["s2"]


def test_nothing_accepted_is_an_empty_list_not_none(monkeypatch):
    stub(monkeypatch, [])
    assert pointers.check(NOTE, [S1, S2]) == []
    stub(monkeypatch, [ptr("s9", "9 participants per region", "5 participants per region")])
    assert pointers.check(NOTE, [S1, S2]) == []


def test_unparseable_model_output_is_an_empty_list(monkeypatch):
    monkeypatch.setattr(pointers, "_chat", lambda msgs: "not json")
    assert pointers.check(NOTE, [S1, S2]) == []
