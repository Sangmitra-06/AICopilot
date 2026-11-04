"""Item 2: the reviewer's free-text reading_order becomes an ordered list of the paper's real sections, matched loosely
from the span section metadata; unparseable text falls back to paper order. After the opening the first section in that
order is offered in the reviewer's own words, and its spans are cited so the PDF scrolls there.
"""
import pytest

from app import chat_checks as cc, store, walk
from app.verify import BANNED
from conftest import PAPER, make_reviewer
from test_walk_opening import SUMMARY, open_, before, assistant_turns


def sp(section, i, page=1):
    return {"id": f"{section[:3]}{i}", "text": f"text of {section} {i}", "page": page, "lines": [i, i], "section": section,
            "kind": "body", "bbox": [10, 10 * i, 100, 10 * i + 8], "segs": [(20, i)]}


def paper(*sections, spans_per=2):
    out = [sp(s, i) for s in sections for i in range(1, spans_per + 1)]
    return out + [dict(sp("References", 1), kind="body")]


FULL = paper("Abstract", "1 Introduction", "2 Related Work", "3 Method", "4 Experiments", "5 Results", "6 Conclusion")
TITLES = ["Abstract", "1 Introduction", "2 Related Work", "3 Method", "4 Experiments", "5 Results", "6 Conclusion"]


def order(text, spans=FULL):
    return walk.parse_reading_order(text, walk.real_sections(spans))


def names(text, spans=FULL):
    return [(e["section"], e["said"]) for e in order(text, spans) if e["said"]]


def titles(text, spans=FULL):
    return [e["section"] for e in order(text, spans)]


def test_real_sections_are_the_papers_own_in_paper_order():
    junk = [dict(sp("Front matter", 1)), dict(sp("Added from PDF", 1), kind="added"), dict(sp("Stray", 1), kind="loose")]
    assert walk.real_sections(junk + FULL + [sp("Appendix A", 1)]) == TITLES      # nothing after References, no stray text


# ------------------------------------------------------------------ several phrasings

def test_intro_then_methods():
    assert names("I start with the intro and then go to methods") == [("1 Introduction", "intro"), ("3 Method", "methods")]


def test_the_rest_of_the_paper_follows_in_paper_order_but_is_not_the_reviewers_words():
    t = titles("I start with the intro and then go to methods")
    assert t[:2] == ["1 Introduction", "3 Method"]
    assert t[2:] == ["Abstract", "2 Related Work", "4 Experiments", "5 Results", "6 Conclusion"]
    assert sorted(t) == sorted(TITLES)                                           # every section exactly once


@pytest.mark.parametrize("text,expected", [
    ("Abstract first, then the experiments, then the conclusion",
     ["Abstract", "4 Experiments", "6 Conclusion"]),
    ("I like to read the abstract, skim the introduction, then jump to results", ["Abstract", "1 Introduction", "5 Results"]),
    ("INTRO -> APPROACH -> EVALUATION", ["1 Introduction", "3 Method", "4 Experiments"]),
    ("related work first, then the setup, then conclusions", ["2 Related Work", "3 Method", "6 Conclusion"]),
    ("Start with Section 3 and then Section 5", ["3 Method", "5 Results"]),
    ("results then method", ["5 Results", "3 Method"]),
    ("Usually the conclusion, because it tells me what they think matters, and then the methodology",
     ["6 Conclusion", "3 Method"]),
], ids=lambda x: x if isinstance(x, str) else "")
def test_loose_matching_of_words_to_the_papers_sections(text, expected):
    assert [t for t, _ in names(text)] == expected


def test_the_reviewers_own_word_is_kept_for_each_section():
    assert names("start with the Introduction, then Methods, and finally Experiments") == [
        ("1 Introduction", "introduction"), ("3 Method", "methods"), ("4 Experiments", "experiments")]


def test_results_prefer_a_results_section_and_experiments_prefer_an_experiments_section():
    assert [t for t, _ in names("results")] == ["5 Results"]
    assert [t for t, _ in names("experiments")] == ["4 Experiments"]
    only_exp = paper("Abstract", "1 Introduction", "4 Experiments")
    assert [t for t, _ in names("I go to the results first", only_exp)] == ["4 Experiments"]


def test_a_part_the_reviewer_says_they_skip_is_not_in_their_order():
    n = [t for t, _ in names("I skip related work and go straight to methods")]
    assert n == ["3 Method"]
    assert titles("I skip related work and go straight to methods")[0] == "3 Method"


def test_a_section_the_paper_does_not_have_is_dropped_not_invented():
    assert [t for t, _ in names("limitations, then the intro, then ethics")] == ["1 Introduction"]


# ------------------------------------------------------------------ unparseable: the paper's own order

@pytest.mark.parametrize("text", [
    "", "idk", "not sure", "it depends", "I read straight through from the beginning", "top to bottom",
    "I look at the figures and tables first", "whatever feels right", "in order", None,
])
def test_unparseable_or_linear_answers_fall_back_to_paper_order(text):
    o = order(text)
    assert [e["section"] for e in o] == TITLES
    assert all(e["said"] is None for e in o)                                     # nothing is claimed as their words


def test_a_paper_with_no_real_sections_has_no_order():
    assert walk.parse_reading_order("intro first", []) == []


def test_reading_text_comes_from_what_the_reviewer_said_not_from_the_default():
    v = lambda **f: {"fields": {"reading_order": f}}
    assert walk.reading_text(v(value="intro_first", source="answer", raw="I start with the intro.")) == "I start with the intro."
    assert walk.reading_text(v(value="paper_order", source="default", raw="idk")) == ""
    assert walk.reading_text({"fields": {}}) == ""
    ext = v(value="results_first", source="extracted",
            raw="I review a lot. I always read the results first. The weather was fine.")
    assert walk.reading_text(ext) == "I always read the results first."


# ------------------------------------------------------------------ the first section is offered, with a pointer

def test_the_opening_offers_the_first_section_in_their_words_and_cites_its_spans(chat_env):
    c, set_model = chat_env
    make_reviewer("rev", reading_order="I start with the intro and then go to methods.", reading_order__value="intro_first")
    model = set_model({"reply": SUMMARY})
    body = open_(c)
    assert model.calls == []                                                     # no summary asked for: no model call
    assert body["opened"] is True and [m["kind"] for m in body["messages"]] == ["section"]
    m = body["messages"][0]
    assert m["reply"].startswith("Starting with the intro, as you said you like to (Section 1).")
    assert [x["id"] for x in m["cites"]] == ["s2"]                              # its spans: the PDF scrolls there
    assert m["parts"] and any(p["cite"] == ["s2"] for p in m["parts"])
    assert not BANNED.search(m["reply"])
    w = store.walk_state("p1")
    assert w["pointer"] == 0 and w["covered"] == ["1 Introduction"] and w["order"][0]["section"] == "1 Introduction"


def test_with_a_summary_the_section_comes_second_as_its_own_message(chat_env):
    c, set_model = chat_env
    make_reviewer("rev", reading_order="Abstract, then method.", reading_order__value="abstract_first",
                  summary_preference="Before.", summary_preference__value="before_reading")
    set_model({"reply": SUMMARY})
    body = open_(c)
    assert [m["kind"] for m in body["messages"]] == ["summary", "section"]
    assert body["messages"][1]["reply"].startswith("Starting with the abstract, as you said you like to (Abstract).")
    assert [t["meta"]["opening"] for t in assistant_turns()] == ["summary", "section"]   # both survive a reload


def test_without_a_stated_order_it_starts_at_the_beginning_without_claiming_they_said_so(chat_env):
    c, set_model = chat_env
    make_reviewer("rev")
    body = open_(c)
    r = body["messages"][0]["reply"]
    assert r.startswith("Let's begin at the start of the paper, with the abstract (Abstract).")
    assert "as you said" not in r


def test_the_offer_is_one_light_prompt_and_says_nothing_about_the_paper(chat_env):
    c, _ = chat_env
    make_reviewer("rev", reading_order="intro first", reading_order__value="intro_first")
    r = open_(c)["messages"][0]["reply"]
    assert r.count("?") <= 1 and not cc.reply_errors(r, {}) and not BANNED.search(r)
    assert "stop guiding" in r                                                   # how to leave the walk is said once


def test_a_paper_with_no_sections_opens_without_a_walk(chat_env, monkeypatch):
    from app import main
    c, _ = chat_env
    make_reviewer("rev")
    monkeypatch.setitem(main.CACHE, "p1", [dict(PAPER[0], section="Front matter")])
    body = open_(c)
    assert body["opened"] is False and store.walk_state("p1")["opened"] is True and store.walk_state("p1")["order"] == []
