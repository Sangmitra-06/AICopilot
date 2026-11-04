"""Fix 4: "what's missing?" and "draft it" get their content from the app, never from the model: the list of open
review-form sections, and the assembled draft grouped by section, whatever the model wrote and however the
reviewer worded the request."""
import pytest

from app import synth, verify
from conftest import make_reviewer
from test_chat_capabilities import add_note, fake_drafter, post

LAZY_GAP = "Here's the list of sections still open in your draft."
LAZY_DRAFT = "Here's your draft, assembled from the notes you've added so far."
WEAK = "Five participants per region seems low"
STRONG = "The probing dataset is released with the paper"


@pytest.fixture
def env(chat_env, monkeypatch):
    c, set_model = chat_env
    make_reviewer("rev")
    fake_drafter(monkeypatch)
    return c, set_model


GAP_PHRASES = ["what's missing?", "What else do I have to add?", "what do I still need to write?", "what remains?",
               "which sections are still empty?", "what's left to cover", "what else should I add?",
               "anything else I need to fill in?"]


@pytest.mark.parametrize("message", GAP_PHRASES)
@pytest.mark.parametrize("model_says", [LAZY_GAP, {"reply": LAZY_GAP, "intent": "chat"}])
def test_a_gap_request_always_gets_the_list_whatever_the_model_wrote(env, message, model_says):
    c, set_model = env
    add_note(1, "weaknesses", WEAK)
    set_model(model_says)
    body = post(c, message)
    assert body["gaps"] is not None, body["reply"]
    for open_section in ("Paper summary", "Summary of strengths", "Soundness", "Overall assessment"):
        assert open_section in body["reply"]
    required = next(l for l in body["reply"].splitlines() if l.startswith("- Required"))
    assert "Summary of weaknesses" not in required                                            # it has a note


def test_empty_sections_and_notes_that_cite_nothing_are_both_listed(env):
    c, set_model = env
    add_note(1, "weaknesses", WEAK)                        # no section, table or figure of the paper in it
    set_model(LAZY_GAP)
    reply = post(c, "what's missing?")["reply"]
    assert "Required, nothing in it yet:" in reply and "Paper summary" in reply
    assert f"“{WEAK}” doesn't point to a section, table or figure of the paper" in reply


def test_the_gap_list_says_nothing_about_the_paper(env):
    c, set_model = env
    add_note(1, "weaknesses", WEAK)
    set_model(LAZY_GAP)
    reply = post(c, "what else do I have to add?")["reply"]
    assert not verify.BANNED.search(reply.replace(f"“{WEAK}”", ""))


DRAFT_PHRASES = ["draft it", "draft my review", "Can you draft it please?", "show me the draft", "write it up",
                 "put my review together", "ok draft the review now", "give me the draft"]


@pytest.mark.parametrize("message", DRAFT_PHRASES)
@pytest.mark.parametrize("model_says", [LAZY_DRAFT, {"reply": LAZY_DRAFT, "intent": "chat"}])
def test_a_draft_request_always_gets_the_draft_text_whatever_the_model_wrote(env, message, model_says):
    c, set_model = env
    add_note(1, "weaknesses", WEAK)
    add_note(2, "strengths", STRONG)
    set_model(model_says)
    body = post(c, message)
    assert body["drafted"] is not None, body["reply"]
    reply = body["reply"]
    assert WEAK in reply and STRONG in reply
    body_text = reply.split("\n\n", 1)[1]                  # after the one-line lead, which also names the sections
    assert (body_text.index("Summary of strengths") < body_text.index(STRONG)
            < body_text.index("Summary of weaknesses") < body_text.index(WEAK))
    assert body["draft_changed"] is True


def test_the_draft_text_is_the_panels_text_grouped_by_section(env):
    c, set_model = env
    add_note(1, "weaknesses", WEAK)
    add_note(2, "weaknesses", "The baselines are listed in Table 3")
    set_model(LAZY_DRAFT)
    reply = post(c, "draft it")["reply"]
    panel = [s["text"] for s in c.get("/draft/p1").json()["weaknesses"]["sentences"]]
    assert panel == [WEAK, "The baselines are listed in Table 3"]
    assert all(t in reply for t in panel)
    assert reply.index(panel[0]) < reply.index(panel[1])


def test_drafting_is_not_blocked_by_missing_sections_and_still_lists_what_is_open(env):
    c, set_model = env
    add_note(1, "comments", "Typo in the abstract")
    set_model(LAZY_DRAFT)
    reply = post(c, "draft it")["reply"]
    assert "Typo in the abstract" in reply and "Paper summary" in reply and "left those empty" in reply
    assert synth.missing_required("p1")


def test_an_empty_review_gets_the_plain_answer_and_the_open_sections(env):
    c, set_model = env
    set_model(LAZY_DRAFT)
    body = post(c, "draft it")
    assert "nothing in your review yet" in body["reply"] and "Paper summary" in body["reply"]


def test_a_note_not_placed_in_a_section_is_in_the_draft_text_too(env):
    c, set_model = env
    add_note(1, "", "Remember to check the licence")
    set_model(LAZY_DRAFT)
    assert "Remember to check the licence" in post(c, "draft it")["reply"]
