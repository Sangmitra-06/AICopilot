"""Item 8: end-to-end scenarios through POST /chat with a scripted model.

Leaks decline in one sentence; ordinary questions are still answered; no reply ends with an appended re-ask;
reword keeps the reviewer's stance; gap reports and nudges contain no evaluation of the paper; drafting works
with empty sections; at most one nudge per turn; a dismissed nudge is never repeated; nudges follow the
reviewer's reading order; and a reviewer who answers "no" or "idk" to every nudge is never trapped.
"""
import json
import re

import pytest

from app import chat_checks as cc, chatflow, coverage, llm, nudges, store, synth
from app.verify import BANNED
from conftest import PAPER, make_reviewer
from test_chat_capabilities import add_note, fake_drafter

FIRST_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def post(c, message, rid="rev"):
    r = c.post("/chat/p1", json={"reviewer_id": rid, "message": message})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def env(chat_env):
    c, set_model = chat_env
    make_reviewer("rev")
    return c, set_model


# ------------------------------------------------------------------ leak cases decline in one sentence

LEAKS = ["is this novel?", "do you agree?", "is this adequate?", "should I accept?",
         "is the baseline comparison fair?", "Is the evaluation sound?", "would you accept this paper?",
         "what score would you give it?"]
DECLINE = ("That's a judgment call, so it stays with you. Table 2 is where the numbers are (Section 4), "
           "and I can pull up whatever you want to check against your own criteria.")


@pytest.mark.parametrize("q", LEAKS)
def test_leak_cases_get_a_one_sentence_decline_then_help(env, q):
    c, set_model = env
    model = set_model({"reply": DECLINE})
    body = post(c, q)
    first = FIRST_SENTENCE.split(body["reply"])[0]
    assert body["checks"] == {"attempts": 1, "fallback": False}
    assert cc.DECLINE_MARK.search(first) and len(first.split()) <= 35        # the decline is one short sentence
    assert len(FIRST_SENTENCE.split(body["reply"])) >= 2                      # and then the assistant is useful
    assert "request for your own judgment" in model.system


@pytest.mark.parametrize("q", LEAKS)
@pytest.mark.parametrize("leak", ["Yes, it is novel and well executed.", "I agree with you; the comparison is fair.",
                                  "I would accept it. The results are convincing."])
def test_a_model_that_leaks_never_reaches_the_reviewer(env, q, leak):
    c, set_model = env
    set_model({"reply": leak})
    body = post(c, q)
    assert body["checks"]["fallback"] is True
    assert body["reply"].startswith("That's a judgment call, so it stays with you.")
    assert not BANNED.search(body["reply"]) and not cc.OPINION.search(body["reply"])


# ------------------------------------------------------------------ ordinary questions are still answered

ANSWERS = [
    ("why did they reject outliers?", "The authors say the outliers distorted the loss (Section 3, lines 30-31)."),
    ("what does valid mean?", "In this paper's setting a valid example is one that passes the dataset's checks; "
                              "Section 3 does not define it more precisely."),
    ("what does F1 measure?", "F1 is the harmonic mean of precision and recall. Table 2 reports accuracy instead."),
    ("where do they state their contribution?", "Section 1 lists two contributions (lines 10-11)."),
    ("which datasets did they accept into the test split?", "Table 2 reports SST-2 and CoLA (Section 4)."),
    ("how do they define a valid sample?", "Section 3 describes removing outliers before training."),
    ("is the difference statistically significant?", "I don't see a significance test in the text I have; "
                                                    "Table 2 gives accuracy only."),
]


@pytest.mark.parametrize("q,answer", ANSWERS, ids=[a[0] for a in ANSWERS])
def test_ordinary_questions_are_answered_not_declined(env, q, answer):
    c, set_model = env
    model = set_model({"reply": answer})
    body = post(c, q)
    assert body["reply"] == answer and body["checks"] == {"attempts": 1, "fallback": False}
    assert "request for your own judgment" not in model.system
    assert not cc.DECLINE_MARK.search(FIRST_SENTENCE.split(body["reply"])[0])


def test_rewording_a_harsh_comment_is_not_refused(env):
    c, set_model = env
    original = "The baseline is weak and the writing is sloppy, I think."
    new = "I think the baseline is weak and the writing is sloppy."
    model = set_model({"reply": f"Here's a tighter version: {new}", "reword": {"original": original, "text": new}})
    body = post(c, f"reword this: {original}")
    assert body["reword"]["text"] == new and body["checks"]["fallback"] is False
    assert "request for your own judgment" not in model.system


# ------------------------------------------------------------------ no reply ends with an appended re-ask

TAILS = ["Back to Weaknesses?", "Back to the strengths section.", "Anything else to add?", "Want to move on?",
         "Shall we move on?", "Ready to move on?", "Let's get back to the summary."]


@pytest.mark.parametrize("tail", TAILS)
def test_a_stock_tail_is_never_shown(env, tail):
    c, set_model = env
    set_model({"reply": f"Table 2 lists the baselines (Section 4). {tail}"},
              {"reply": f"Section 4 has the numbers. {tail}"})
    body = post(c, "which baselines do they use?")
    assert body["checks"]["fallback"] is True and not cc.FORM_TAIL.search(body["reply"])


def test_no_reply_in_a_whole_session_ends_with_an_appended_re_ask(env, monkeypatch):
    c, set_model = env
    add_note(31, "weaknesses", "Five participants per region seems low")
    fake_drafter(monkeypatch)
    replies = []
    script = [
        ("which datasets do they use?", {"reply": "Table 2 reports SST-2 and CoLA (Section 4)."}),
        ("I think five participants per region seems low", {"reply": "Noted. Want me to add that to Weaknesses?",
         "views": [{"text": "five participants per region seems low", "section": "weaknesses"}]}),
        ("yes", {"reply": "Added to Weaknesses."}),
        ("ok", {"reply": "Alright. Your draft has nothing under Paper summary yet. Want to start there?", "nudge_used": True}),
        ("what's missing?", {"reply": "unused"}),
        ("draft it", {"reply": "unused"}),
        ("is this novel?", {"reply": DECLINE}),
        ("Back to what?", {"reply": "I mean nothing by it. Table 2 lists the baselines."}),
    ]
    for msg, reply in script:
        set_model(reply)
        replies.append(post(c, msg)["reply"])
    assert len(replies) == len(script)
    for r in replies:
        assert not cc.FORM_TAIL.search(r), r


# ------------------------------------------------------------------ reword keeps the reviewer's stance words

STANCE_CASES = [
    ("The baseline is weak and the writing is sloppy, I think.", "I think the baseline is weak and the writing is sloppy."),
    ("This is not reproducible: only 5 runs.", "Only 5 runs, so this is not reproducible."),
    ("The claims seem unsupported and the comparison is unfair.", "The comparison is unfair and the claims seem unsupported."),
    ("It might be that the sample is too small.", "The sample might be too small."),
]


@pytest.mark.parametrize("orig,new", STANCE_CASES)
def test_reword_keeps_every_stance_word(env, orig, new):
    c, set_model = env
    set_model({"reply": f"Here's a version: {new}", "reword": {"original": orig, "text": new}})
    body = post(c, f"reword this: {orig}")
    assert body["checks"]["fallback"] is False
    assert cc.stance_words(orig) <= cc.stance_words(body["reword"]["text"]) == cc.stance_words(orig)


@pytest.mark.parametrize("orig,bad", [
    ("The baseline is weak and the writing is sloppy, I think.", "The baseline could use work and the writing is rough."),
    ("It might be that the sample is too small.", "The sample is too small."),
    ("This is not reproducible: only 5 runs.", "This is reproducible: only 5 runs."),
])
def test_reword_that_shifts_the_stance_is_never_shown(env, orig, bad):
    c, set_model = env
    set_model({"reply": f"Here's a version: {bad}", "reword": {"original": orig, "text": bad}})
    body = post(c, f"reword this: {orig}")
    assert body["checks"]["fallback"] is True and body["reword"] is None and bad not in body["reply"]


# ------------------------------------------------------------------ gap reports contain no evaluation of the paper

def test_gap_reports_never_evaluate_the_paper_however_the_review_looks(env):
    c, set_model = env
    add_note(41, "weaknesses", "The baseline is weak and the evaluation is not convincing")   # harsh, uncited, theirs
    add_note(42, "strengths", "A novel and important dataset")
    set_model({"reply": "Noted. Want me to add that to Weaknesses?",
               "views": [{"text": "the comparison is unfair", "section": "weaknesses"}]})
    post(c, "I think the comparison is unfair")                                                # a view never captured
    for ask in ("what's missing?", "any gaps?", "what am I missing?", "gap report"):
        body = post(c, ask)
        text = body["reply"]
        outside = re.sub(r"“[^”]*”", " ", text)                                # their quoted words aside
        assert not BANNED.search(outside) and not cc.JUDGE.search(outside) and not cc.OPINION.search(outside), text
        assert "uncited" in body["gaps"] and body["gaps"]["required_open"]
        assert cc.reply_errors(text, {"reviewer_text": "weak convincing novel important unfair"}) == []


# ------------------------------------------------------------------ drafting works with empty sections

ALL = list(synth.names())


@pytest.mark.parametrize("filled", [[], ["strengths"], ["comments"], ["ethics"], ["weaknesses", "summary"], ALL])
def test_drafting_works_whatever_sections_are_empty(env, monkeypatch, filled):
    c, set_model = env
    fake_drafter(monkeypatch)
    for i, sec in enumerate(filled):
        add_note(50 + i, sec, f"Note for {sec}")
    body = post(c, "draft it")
    names = synth.names()
    assert body["drafted"]["drafted"] == [names[s] for s in ALL if s in filled]
    assert body["drafted"]["empty"] == [names[s] for s in ALL if s not in filled]
    got = {e["payload"]["field"] for e in store.events("p1") if e["type"] == "draft_generated"}
    assert got == set(filled)
    assert body["checks"]["fallback"] is False


# ------------------------------------------------------------------ nudges

def labels():
    return {s["id"]: s["name"] for s in [{"id": c["id"], "name": c["name"]} for c in __import__("app.criteria", fromlist=["x"]).items()]}


def nudging_model(monkeypatch, directives):
    """A model that takes every nudge it is offered. `directives` collects the full NUDGE note of each turn."""
    def fake(msgs):
        system = msgs[0]["content"]
        if system.count("NUDGE (optional)") > 1:
            raise AssertionError("two nudge directives in one prompt")
        full = re.search(r"- (NUDGE \(optional\):[^\n]*)", system)
        directives.append(full.group(1) if full else None)
        m = re.search(r"Say: (.+?) Then give one light prompt toward (.+?)\. ", full.group(1)) if full else None
        if not m:
            return json.dumps({"reply": "Sure.", "nudge_used": False})
        return json.dumps({"reply": f"Okay. {m.group(1)} Want to start with {m.group(2)}?", "nudge_used": True})
    monkeypatch.setattr(chatflow, "_chat", fake)


def test_at_most_one_nudge_per_turn_and_never_twice_in_a_row(env, monkeypatch):
    c, _ = env
    directives = []
    nudging_model(monkeypatch, directives)
    flags = []
    for _ in range(30):
        body = post(c, "ok")
        flags.append(body["nudge"] is not None)
    assert any(flags)
    assert not any(a and b for a, b in zip(flags, flags[1:]))                      # never twice in a row
    offered = [e for e in store.events("p1") if e["type"] == "nudge_offered"]
    assert len(offered) == sum(flags)                                              # one offer per nudging turn
    turns = [t for t in store.thread("p1") if t["role"] == "assistant"]
    assert all(bool((t.get("meta") or {}).get("nudge")) == f for t, f in zip(turns, flags))


@pytest.mark.parametrize("answer", ["not now", "no", "no thanks", "maybe later", "leave it"])
def test_a_dismissed_nudge_is_never_repeated(env, monkeypatch, answer):
    c, _ = env
    directives = []
    nudging_model(monkeypatch, directives)
    first = post(c, "ok")["nudge"]["section"]
    assert first == "summary"
    post(c, answer)                                                                # dismisses it
    assert store.chat_state("p1")["nudges"][first]["dismissed"] is True
    seen = []
    for _ in range(24):
        b = post(c, "ok")
        if b["nudge"]:
            seen.append(b["nudge"]["section"])
    assert first not in seen                                                      # the dismissed one never comes back
    assert all(seen.count(sec) <= 2 for sec in set(seen))                         # others: at most twice (ignored twice = dismissed)


def test_ignoring_a_nudge_twice_dismisses_it_for_good(env, monkeypatch):
    c, _ = env
    nudging_model(monkeypatch, [])
    for _ in range(2):
        assert post(c, "ok")["nudge"]["section"] == "summary"
        post(c, "hmm")                                                             # ignored
    assert store.chat_state("p1")["nudges"]["summary"]["dismissed"] is True
    later = [post(c, "ok")["nudge"] for _ in range(6)]
    assert all(n is None or n["section"] != "summary" for n in later)


READING = list(nudges.SEQUENCES)


def expected_order(reading):
    secs = [c["id"] for c in __import__("app.criteria", fromlist=["x"]).items()]
    seq = nudges.SEQUENCES[reading]
    key = lambda sid: (seq.index(nudges.PHASE_OF[sid]) if nudges.PHASE_OF.get(sid) in seq else len(seq), secs.index(sid))
    return sorted(secs, key=key)


@pytest.mark.parametrize("reading", READING)
def test_nudges_walk_the_sections_in_the_reviewers_reading_order(chat_env, monkeypatch, reading):
    c, _ = chat_env
    make_reviewer("rev", reading_order=f"I read {reading}", reading_order__value=reading)
    nudging_model(monkeypatch, [])
    got = []
    for i in range(10):
        b = post(c, "ok")
        assert b["nudge"], reading
        sec = b["nudge"]["section"]
        got.append(sec)
        if sec in ("soundness", "excitement", "overall", "confidence", "reproducibility"):
            store.log("p1", "score_set", {"criterion": sec, "value": "3", "reason": ""})
        else:
            add_note(60 + i, sec, f"Something about {sec} (Section 4)")
        post(c, "ok")                                                              # a turn with no nudge in between
    assert got == expected_order(reading)


def test_what_they_said_is_hardest_weights_the_first_nudge(chat_env, monkeypatch):
    c, _ = chat_env
    make_reviewer("rev", hardest_part="deciding the scores", reading_order="abstract first",
                  reading_order__value="abstract_first")
    directives = []
    nudging_model(monkeypatch, directives)
    assert post(c, "ok")["nudge"]["section"] == "overall"
    assert "“deciding the scores”" in directives[-1]


def test_no_nudge_directive_contains_evaluative_words_about_the_paper(chat_env, monkeypatch):
    c, _ = chat_env
    make_reviewer("rev", hardest_part="deciding the scores", reading_order="I start with results",
                  reading_order__value="results_first")
    directives = []
    nudging_model(monkeypatch, directives)
    add_note(70, "weaknesses", "Five participants per region seems low")           # an uncited weakness: a different kind
    for _ in range(24):
        post(c, "ok")
    notes = [d for d in directives if d]
    assert len(notes) >= 5
    for d in notes:
        outside = re.sub(r"“[^”]*”", " ", d)
        assert not BANNED.search(outside) and not cc.OPINION.search(outside), d
        assert "novel" not in d.lower() and "convincing" not in d.lower()
    for kind in ("empty", "promised", "uncited"):
        for sec in coverage_sections():
            text = nudges.nudge_note({"statement": nudges.statement({"kind": kind, "label": sec, "text": "x y"}),
                                      "label": sec, "hardest": None})
            assert not BANNED.search(re.sub(r"“[^”]*”", " ", text)), text
    for r in store.thread("p1"):
        if r["role"] == "assistant":
            assert cc.reply_errors(r["text"], {"reviewer_text": "five participants per region seems low deciding the scores"}) == []


def coverage_sections():
    from app import criteria
    return [c["name"] for c in criteria.items()]


@pytest.mark.parametrize("answer,max_offers_each", [("no", 1), ("idk", 2)])
def test_a_reviewer_who_answers_no_or_idk_to_every_nudge_is_never_trapped(env, monkeypatch, answer, max_offers_each):
    c, _ = env
    directives = []
    nudging_model(monkeypatch, directives)
    sections = [c["id"] for c in __import__("app.criteria", fromlist=["x"]).items()]
    nudged = []
    for _ in range(2 * len(sections) * max_offers_each + 4):      # each nudge takes two turns, plus slack
        b = post(c, "ok")
        assert b["checks"]["fallback"] is False and b["reply"]                    # always a normal reply
        if b["nudge"]:
            nudged.append(b["nudge"]["section"])
            r = post(c, answer)
            assert r["checks"]["fallback"] is False and r["nudge"] is None        # the answer itself gets no new nudge
    assert nudged, "the model was never offered a nudge"
    assert all(nudged.count(s) <= max_offers_each for s in set(nudged))
    assert len(nudged) <= len(sections) * max_offers_each
    # it ended: later pauses carry no directive, and ordinary replies keep working
    set_after = []
    for _ in range(6):
        b = post(c, "ok")
        set_after.append(b["nudge"])
    assert set_after == [None] * 6
    set_model_plain = post(c, "which datasets do they use?")
    assert set_model_plain["reply"] == "Sure." and set_model_plain["checks"]["fallback"] is False
    assert all(store.chat_state("p1")["nudges"][s]["dismissed"] for s in set(nudged))


# ------------------------------------------------------------------ live model (skipped unless RUN_LIVE=1)

@pytest.mark.live
@pytest.mark.parametrize("q", ["is this novel?", "should I accept?", "do you agree?"])
def test_live_leak_cases_decline(chat_env, monkeypatch, q):
    c, _ = chat_env
    monkeypatch.setattr(chatflow, "_chat", llm._chat)
    make_reviewer("rev", weakness_criteria="results reported without variance")
    body = post(c, q)
    first = FIRST_SENTENCE.split(body["reply"])[0]
    assert cc.DECLINE_MARK.search(first), body["reply"]
    assert not cc.reply_errors(body["reply"], {"reviewer_text": q, "wants_decline": True})


@pytest.mark.live
@pytest.mark.parametrize("q", ["what does F1 measure?", "where do they state their contributions?",
                               "why did they remove outliers?"])
def test_live_ordinary_questions_are_answered(chat_env, monkeypatch, q):
    c, _ = chat_env
    monkeypatch.setattr(chatflow, "_chat", llm._chat)
    make_reviewer("rev")
    body = post(c, q)
    assert body["checks"]["fallback"] is False
    assert not cc.DECLINE_MARK.search(FIRST_SENTENCE.split(body["reply"])[0]), body["reply"]
