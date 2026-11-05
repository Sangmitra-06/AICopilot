"""Wrong section in the guided walk (fix item 4).

The real session: reading_order "I start with intro then I like to get into methods and results", and "next" after the
intro went to a results subsection (4.6) instead of Section 3 (Methods).

Cause: the paper's top-level headings "3 Methods" and "4 Results" are followed directly by "3.1 ..." / "4.1 ..." with no
text in between, so no span carries them and the walk never saw them. "methods" then fell through to its second tier
(model|architecture|...), which matched the word "architecture" in the title of 4.6; "results" matched nothing at
all.

Fix: every span gets its top-level section (`top`, from the headings ingest found; ingest.py itself is old-flow code and is
not changed), the walk goes by top-level sections, the method words
(method/methods/methodology/approach/setup/experimental setup) mean the same thing, and "methods" never lands on a
results, discussion or conclusion section.
"""
import os

import pymupdf
import pytest

from app import walk

# STAND-IN titles with the same layout as the session's paper (that paper is under review: none of its text is kept
# here). As ingest labels the spans: (section, top-level section); 3 and 4 have no text of their own.
SESSION_LAYOUT = [
    ("Abstract", None), ("1 Introduction", "1 Introduction"), ("2 Related Work", "2 Related Work"),
    ("3.1 Probe Design", "3 Methods"), ("3.2 Training Details", "3 Methods"),
    ("3.3 Control Tasks", "3 Methods"), ("3.4 Layer Selection", "3 Methods"),
    ("4.1 Layer-wise Accuracy", "4 Results"),
    ("4.2 Probe Capacity", "4 Results"),
    ("4.3 Effect of Model Size", "4 Results"), ("4.4 Selectivity", "4 Results"),
    ("4.5 Error Analysis", "4 Results"), ("4.6 Transfer to Other Architectures", "4 Results"),
    ("5 Discussion", "5 Discussion"), ("6 Conclusion", "6 Conclusion"), ("Limitations", None),
]
SESSION_READING = "I start with intro then I like to get into methods and results"


def spans_for(layout, with_top=True):
    out = []
    for k, (sec, top) in enumerate(layout):
        for i in range(2):
            s = {"id": f"p{k + 1}-s{i + 1}", "text": f"text of {sec} {i}", "page": 1 + k // 3, "lines": [k * 10 + i] * 2,
                 "section": sec, "kind": "body", "bbox": [10, 10, 100, 20], "segs": [(20, k * 10 + i)]}
            if with_top:
                s["top"] = top
            out.append(s)
    return out + [{"id": "ref", "text": "A. Author. 2020.", "page": 9, "lines": [900, 900], "section": "References",
                   "kind": "body", "bbox": [10, 10, 100, 20], "segs": [(10, 900)]}]


def said(text, spans):
    return [(e["section"], e["said"]) for e in walk.parse_reading_order(text, walk.real_sections(spans)) if e["said"]]


# ------------------------------------------------------------------ the session's paper

def test_the_session_paper_intro_then_methods_goes_to_section_3_not_4_6():
    spans = spans_for(SESSION_LAYOUT)
    assert walk.real_sections(spans) == ["Abstract", "1 Introduction", "2 Related Work", "3 Methods", "4 Results",
                                         "5 Discussion", "6 Conclusion", "Limitations"]
    assert said(SESSION_READING, spans) == [("1 Introduction", "intro"), ("3 Methods", "methods"),
                                            ("4 Results", "results")]


def test_the_session_paper_walks_section_3_with_all_its_subsections():
    spans = spans_for(SESSION_LAYOUT)
    own = {s["section"] for s in walk.section_spans(spans, "3 Methods", n=99)}
    assert own == {"3.1 Probe Design", "3.2 Training Details", "3.3 Control Tasks",
                   "3.4 Layer Selection"}
    assert walk.section_spans(spans, "3 Methods")[0]["section"] == "3.1 Probe Design"   # the PDF goes to the start of 3


def test_without_the_parent_heading_methods_still_never_lands_on_a_results_subsection():
    spans = spans_for(SESSION_LAYOUT, with_top=False)             # an older ingest: no `top`
    hits = [s for s, w in said(SESSION_READING, spans) if w == "methods"]
    assert "4.6 Transfer to Other Architectures" not in hits
    assert not any(t.startswith(("4", "5", "6")) for t in hits)


def test_section_3_and_section_3_2_jump_to_the_top_level_section():
    secs = walk.real_sections(spans_for(SESSION_LAYOUT))
    assert walk.jump_target("lets go to section 3", secs) == {"section": "3 Methods", "said": "section 3"}
    assert walk.jump_target("take me to section 3.2", secs)["section"] == "3 Methods"
    assert walk.jump_target("go to methods", secs)["section"] == "3 Methods"
    assert walk.jump_target("go to the results", secs)["section"] == "4 Results"


# ------------------------------------------------------------------ ingest records the top-level section

def make_pdf(path):
    """Same layout as the session's paper: "3 Methods" directly followed by "3.1 Probe Design", bookmarks present."""
    doc = pymupdf.open()
    page, y = doc.new_page(), 72
    body = "We describe this part of the work in some detail here, so that there is body text under the heading."

    def put(text, size):
        nonlocal y
        page.insert_text((72, y), text, fontsize=size)
        y += size + 8

    toc = []
    for head, level, text in [("1 Introduction", 1, True), ("2 Related Work", 1, True), ("3 Methods", 1, False),
                              ("3.1 Probe Design", 2, True), ("3.2 Training Details", 2, True),
                              ("4 Results", 1, False), ("4.1 Layer-wise Accuracy", 2, True),
                              ("4.2 Transfer to Other Architectures", 2, True), ("5 Conclusion", 1, True)]:
        put(head, 13)
        toc.append([level, head.split(" ", 1)[1], 1])
        if text:
            put(body, 10)
            put(body, 10)
    doc.set_toc(toc)
    doc.save(path)


def loaded(monkeypatch, folder, pid):
    """The spans exactly as the app loads them (main.spans_of: ingest, then the top-level sections)."""
    from app import main
    monkeypatch.setattr(main, "DATA_DIR", str(folder))
    monkeypatch.setattr(main, "CACHE", {})
    return main.spans_of(pid)


def test_every_loaded_span_has_its_top_level_section(tmp_path, monkeypatch):
    make_pdf(str(tmp_path / "paper.pdf"))
    spans = loaded(monkeypatch, tmp_path, "paper")
    tops = {s["section"]: s.get("top") for s in spans if s["section"] not in ("Front matter",)}
    assert tops["3.1 Probe Design"] == "3 Methods" and tops["3.2 Training Details"] == "3 Methods"
    assert tops["4.2 Transfer to Other Architectures"] == "4 Results"
    assert tops["1 Introduction"] == "1 Introduction" and tops["5 Conclusion"] == "5 Conclusion"
    assert said(SESSION_READING, spans) == [("1 Introduction", "intro"), ("3 Methods", "methods"),
                                            ("4 Results", "results")]


REAL_PDF = os.environ.get("WALK_REAL_PDF", "")       # a local paper with this layout, never committed


@pytest.mark.skipif(not (REAL_PDF and os.path.exists(REAL_PDF)), reason="set WALK_REAL_PDF to a local PDF to run this")
def test_a_real_pdf_with_this_layout(monkeypatch):
    folder, name = os.path.split(os.path.abspath(REAL_PDF))
    spans = loaded(monkeypatch, folder, name[:-4])
    assert said(SESSION_READING, spans) == [("1 Introduction", "intro"), ("3 Methods", "methods"),
                                            ("4 Results", "results")]


# ------------------------------------------------------------------ other common layouts

def flat(*titles):
    """Top-level sections only, each with its own text (spans carry no `top`, as test papers elsewhere)."""
    return spans_for([(t, None) for t in titles], with_top=False)


def nested(*pairs):
    return spans_for(list(pairs))


@pytest.mark.parametrize("word", ["methods", "method", "methodology", "approach", "setup", "set-up", "experimental setup"])
def test_the_method_words_mean_the_same_thing(word):
    spans = flat("1 Introduction", "2 Related Work", "3 Our Approach", "4 Results", "5 Conclusion")
    assert said(f"intro, then {word}", spans) == [("1 Introduction", "intro"), ("3 Our Approach", word)]


@pytest.mark.parametrize("spans,expected", [
    (flat("Introduction", "Methods", "Results", "Discussion"), ["Methods"]),
    (flat("1 Introduction", "2 Method", "3 Experiments", "4 Results", "5 Conclusion"), ["2 Method"]),
    (flat("1 Introduction", "2 Background", "3 Proposed Model", "4 Evaluation", "5 Conclusion"), ["3 Proposed Model"]),
    (flat("1 Introduction", "2 Framework", "3 Results and Analysis", "4 Conclusion"), ["2 Framework"]),
    (flat("1 Introduction", "2 Approach", "3 Experimental Setup", "4 Results", "5 Conclusion"),
     ["2 Approach", "3 Experimental Setup"]),
    (nested(("1 Introduction", "1 Introduction"), ("3 Method", "3 Method"), ("3.1 Model Architecture", "3 Method"),
            ("4 Experiments", "4 Experiments"), ("4.1 Setup", "4 Experiments"), ("5 Results", "5 Results")),
     ["3 Method"]),
])
def test_methods_in_common_layouts(spans, expected):
    assert [s for s, w in said("intro then methods", spans) if w == "methods"] == expected


@pytest.mark.parametrize("spans", [
    flat("1 Introduction", "2 Related Work", "3 Results on Architectures", "4 Conclusion"),
    flat("1 Introduction", "2 Data", "3 Architecture Results", "4 Discussion of the Model", "5 Conclusion"),
    spans_for([("1 Introduction", "1 Introduction"), ("2.1 Transfer to Other Architectures", "2 Results"),
               ("3 Conclusion", "3 Conclusion")]),
    spans_for([("1 Introduction", None), ("4.6 Transfer to Other Architectures", None), ("6 Conclusion", None)],
              with_top=False),
])
def test_methods_never_picks_a_results_discussion_or_conclusion_section(spans):
    hits = [s for s, w in said("intro then methods", spans) if w == "methods"]
    assert not any(walk.NOT_METHODS.search(h) for h in hits), hits
    assert not any("Architecture" in h for h in hits), hits


def test_a_top_level_section_is_preferred_to_a_subsection_with_the_same_word():
    spans = flat("1 Introduction", "2 Method", "2.3 Method Details", "3 Results")
    assert [s for s, w in said("methods", spans)] == ["2 Method"]


def test_results_still_means_the_results_section():
    spans = spans_for(SESSION_LAYOUT)
    assert said("results first", spans) == [("4 Results", "results")]


@pytest.mark.parametrize("text", ["intro then the model", "intro then the architecture"])
def test_model_words_never_land_on_a_results_subsection_either(text):
    spans = spans_for(SESSION_LAYOUT, with_top=False)
    assert not any("Architecture" in s for s, w in said(text, spans) if w != "intro")


def test_the_paper_text_shows_a_top_level_heading_that_has_no_text_of_its_own():
    from app import chatflow
    text = chatflow.paper_text(spans_for(SESSION_LAYOUT))
    assert text.index("## 3 Methods") < text.index("## 3.1 Probe Design") < text.index("## 4 Results")
    assert text.count("## 1 Introduction") == 1                     # a top-level section with text is not doubled
