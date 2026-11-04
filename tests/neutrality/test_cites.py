"""Citations in chat replies (backend/app/cites.py): marker parsing, plain pointers, unknown ids, no citations."""
import pytest

from app import cites
from conftest import PAPER

SPANS = PAPER + [
    {"id": "s6", "text": "stray", "page": 3, "bbox": [1, 1, 2, 2], "lines": None, "section": "3 Method", "kind": "loose"},
    {"id": "s7", "text": "added", "page": 3, "bbox": [1, 1, 2, 2], "lines": None, "section": "Added from PDF", "kind": "added"},
]
for s in SPANS:
    s.setdefault("bbox", [10, 20, 200, 40])


def go(reply):
    return cites.extract(reply, SPANS)


def test_a_marker_becomes_a_plain_section_pointer_and_the_id_is_gone():
    text, parts, got = go("Table 2 reports the accuracy [s4].")
    assert text == "Table 2 reports the accuracy (Section 4)."
    assert "s4" not in text and "[" not in text
    assert [c["id"] for c in got] == ["s4"]
    assert got[0]["page"] == 4 and got[0]["bbox"] == [10, 20, 200, 40] and got[0]["section"] == "4 Experiments"


def test_parts_join_to_the_text_and_only_the_pointer_is_marked():
    text, parts, _ = go("Table 2 reports the accuracy [s4]. It also lists CoLA.")
    assert "".join(p["text"] for p in parts) == text
    assert [p["text"] for p in parts if p["cite"]] == ["(Section 4)"]
    assert [p["cite"] for p in parts if p["cite"]] == [["s4"]]


def test_unknown_ids_are_dropped_with_no_trace():
    text, parts, got = go("They train it [s99] on parsed text [s3].")
    assert text == "They train it on parsed text (Section 3)." and [c["id"] for c in got] == ["s3"]
    assert "".join(p["text"] for p in parts) == text


def test_only_unknown_ids_means_no_citation_at_all():
    text, parts, got = go("They train it [s99] and test it [nonsense1].")
    assert text == "They train it and test it." and got == [] and parts is None


def test_no_markers_no_cites_no_parts():
    text, parts, got = go("Happy to look at that with you.")
    assert (text, parts, got) == ("Happy to look at that with you.", None, [])


@pytest.mark.parametrize("hidden", ["s5", "s6", "s7"])
def test_spans_the_prompt_never_showed_are_not_citable(hidden):
    """References, stray page text and spans added from a selection are not in the prompt, so an id for one is made up."""
    text, parts, got = go(f"See this [{hidden}].")
    assert got == [] and text == "See this."


def test_several_markers_in_a_row_are_one_pointer_and_one_order():
    text, parts, got = go("The setup and results [s3][s4] are here, [s3, s4] again.")
    assert text.count("(Sections 3, 4)") == 2
    assert [c["id"] for c in got] == ["s3", "s4"]                       # each once, in order of first mention
    assert "".join(p["text"] for p in parts) == text


def test_the_same_span_cited_twice_is_listed_once():
    _, _, got = go("It says so [s4], and again [s4].")
    assert [c["id"] for c in got] == ["s4"]


def test_a_section_without_a_number_is_named_plainly():
    text, _, got = go("It opens with the claim [s1].")
    assert text == "It opens with the claim (Abstract)." and got[0]["id"] == "s1"


def test_ordinary_brackets_are_left_alone():
    text, parts, got = go("Prior work [12] and [Table 2] and [see below] are not ids.")
    assert text == "Prior work [12] and [Table 2] and [see below] are not ids." and got == [] and parts is None


def test_a_marker_at_the_start_has_no_stray_space():
    text, parts, _ = go("[s2] lists the contributions.")
    assert text == "(Section 1) lists the contributions."
    assert "".join(p["text"] for p in parts) == text


def test_plain_removes_every_marker_and_puts_nothing_in_its_place():
    assert cites.plain("It is [s3]novel and [s99] well [s4] written.") == "It is novel and well written."


def test_reconcile_keeps_pointers_when_a_note_is_appended():
    text, parts, _ = go("Table 2 has it [s4].")
    longer = text + "\n\nA note."
    out = cites.reconcile(parts, longer)
    assert "".join(p["text"] for p in out) == longer and [p["text"] for p in out if p["cite"]] == ["(Section 4)"]


def test_reconcile_drops_parts_it_cannot_honour():
    _, parts, _ = go("Table 2 has it [s4].")
    assert cites.reconcile(parts, "something else entirely") is None
