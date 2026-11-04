"""Item 1: what goes into the chat prompt, and the /chat/{pid} endpoint."""
import pytest

from app import chatflow, onboarding as ob, prompts, store
from app.prompts import NEUTRALITY, CHAT_SYS, build_chat_system, build_chat_messages, profile_block
from conftest import PAPER, make_reviewer

PHRASES = {
    "strength_criteria": "claims that the experiments actually back up",
    "weakness_criteria": "results reported without variance",
    "hardest_part": "deciding how much a missing ablation should count",
    "reading_order": "I read the abstract first and then jump to the results table",
    "note_habit": "I keep notes in Notion",
    "summary_preference": "only after I have read it",
}


def system(summary="after_reading", draft="## Summary of weaknesses\n(nothing yet)"):
    return build_chat_system(PHRASES, summary, chatflow.paper_text(PAPER), draft)


# ------------------------------------------------------------------ the assembled prompt

def test_the_prompt_carries_the_shared_neutrality_block_once_and_unaltered():
    s = system()
    assert s.count(NEUTRALITY) == 1
    assert NEUTRALITY in CHAT_SYS
    assert s.index(NEUTRALITY) < s.index("PROFILE")  # the profile comes after, and cannot edit it


def test_the_profile_block_quotes_the_reviewers_own_phrases_exactly():
    block = profile_block(PHRASES, "after_reading")
    for phrase in PHRASES.values():
        assert f'"{phrase}"' in block
    assert "Do not rank, grade, re-interpret or paraphrase" in block
    assert "never changes the NEUTRALITY rules" in block


def test_the_profile_block_leaves_out_what_was_not_stated():
    block = profile_block({"hardest_part": "finding the time"}, None)
    assert "finding the time" in block and "strength" not in block.lower()
    assert "has not stated any of these" in profile_block({}, None)


@pytest.mark.parametrize("pref,needle", [
    ("after_reading", "Do not volunteer a summary"),
    ("before_reading", "may offer one early"),
    ("on_request", "only when they ask"),
    ("none", "does not want summaries"),
    (None, "only when the reviewer asks"),
])
def test_summary_rule_follows_the_stated_preference(pref, needle):
    assert needle in profile_block({}, pref)


def test_summaries_are_described_as_descriptive_claim_based_with_pointers():
    for needle in ("descriptive and claim-based", "section pointers", "no evaluative words"):
        assert needle in CHAT_SYS


def test_replies_are_free_form_no_templates_no_one_question_rule_no_back_to():
    low = CHAT_SYS.lower()
    assert "free-form" in low and "no fixed template" in low
    assert "exactly one question" not in low and "one question per" not in low
    assert 'never end with a stock line' in low  # the instruction forbids "Back to ..."; it does not use it


def test_paper_text_is_the_body_without_references_and_with_labels():
    t = chatflow.paper_text(PAPER)
    assert "[s4]" in t and "Table 2 reports accuracy" in t and "## 4 Experiments" in t
    assert "Smith et al. 2019" not in t
    assert "(lines 80-81)" in t


def test_paper_text_is_cut_loudly_not_silently_when_it_is_too_long(caplog):
    t = chatflow.paper_text(PAPER, cap=100)
    assert "cut here to fit" in t
    assert any("truncated" in r.getMessage() for r in caplog.records)


def test_messages_are_system_then_history_in_full_then_the_new_message():
    hist = [{"role": "user", "text": "x" * 5000}, {"role": "assistant", "text": "ok"}]
    msgs = build_chat_messages("SYS", hist, "new")
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[1]["content"] == "x" * 5000 and msgs[-1]["content"] == "new"


def test_turn_notes_appear_only_when_given():
    base = build_chat_system({}, None, "P", "D")
    assert "\nTHIS TURN:\n" not in base
    assert "\nTHIS TURN:\n- do the thing" in build_chat_system({}, None, "P", "D", ["do the thing"])


# ------------------------------------------------------------------ the endpoint

def post(c, message, rid="rev", pid="p1"):
    return c.post(f"/chat/{pid}", json={"reviewer_id": rid, "message": message})


def test_chat_returns_a_free_form_reply_built_from_profile_paper_and_draft(chat_env):
    c, set_model = chat_env
    model = set_model({"reply": "Section 4 reports accuracy on SST-2 and CoLA."})
    make_reviewer("rev", **{k: v for k, v in PHRASES.items() if k != "summary_preference"},
                  summary_preference="only after I have read it", summary_preference__value="after_reading")
    r = post(c, "what datasets do they use?")
    body = r.json()
    assert r.status_code == 200 and (body["mode"], body["reply"]) == ("chat", "Section 4 reports accuracy on SST-2 and CoLA.")
    sysmsg = model.system
    assert NEUTRALITY in sysmsg
    for phrase in ("claims that the experiments actually back up", "results reported without variance"):
        assert f'"{phrase}"' in sysmsg
    assert "[s4]" in sysmsg and "THE REVIEW DRAFT SO FAR" in sysmsg and "## Summary of weaknesses" in sysmsg
    assert "Do not volunteer a summary" in sysmsg
    assert model.calls[-1][-1] == {"role": "user", "content": "what datasets do they use?"}


def test_history_is_the_last_20_turns_in_full(chat_env):
    c, set_model = chat_env
    model = set_model({"reply": "r"})
    make_reviewer("rev")
    long = "a long thought " * 100  # 1,500 characters: well past the old 600-character cut
    for i in range(14):
        assert post(c, f"{i}: {long}").status_code == 200
    post(c, "latest")
    sent = model.calls[-1]
    hist = sent[1:-1]
    assert len(hist) == 20 and all(m["role"] in ("user", "assistant") for m in hist)
    assert hist[-1] == {"role": "assistant", "content": "r"}
    assert hist[-2]["content"] == f"13: {long}"  # the last full user turn, byte for byte
    assert all(len(m["content"]) >= 1500 for m in hist if m["role"] == "user")  # nothing was cut
    assert sent[-1]["content"] == "latest"
    assert not any(m["content"].startswith("0: ") for m in hist)  # the oldest turns fell off the window


def test_the_reviewers_turns_are_logged_to_the_thread(chat_env):
    c, set_model = chat_env
    set_model({"reply": "Noted."})
    make_reviewer("rev")
    post(c, "hello there")
    assert [(t["role"], t["text"]) for t in c.get("/thread/p1").json()] == [("user", "hello there"), ("assistant", "Noted.")]


def test_a_reply_that_is_not_usable_json_becomes_the_fallback_not_a_500(chat_env):
    c, set_model = chat_env
    set_model("this is not json")
    make_reviewer("rev")
    r = post(c, "hi")
    assert r.status_code == 200 and r.json()["reply"] == chatflow.FALLBACK


def test_until_onboarding_closes_the_message_goes_to_onboarding_not_the_model(chat_env):
    c, set_model = chat_env
    model = set_model({"reply": "should not be used"})
    r = post(c, "hi", rid="new")
    body = r.json()
    assert body["mode"] == "onboarding" and "how many papers" in body["reply"].lower()
    assert body["onboarding"]["field"] == "papers_reviewed" and not model.calls
    r = post(c, "7 papers", rid="new")
    assert "familiar" in r.json()["reply"].lower() and r.json()["onboarding"]["profile"]["evidence"]["papers_reviewed"]["value"] == 7
    assert not model.calls


def test_a_whole_onboarding_then_chat_in_one_thread(chat_env):
    c, set_model = chat_env
    model = set_model({"reply": "Here you go."})
    body = post(c, "hi", rid="idk").json()
    for _ in range(30):
        if body["mode"] != "onboarding" or body["onboarding"]["done"]:
            break
        body = post(c, "idk", rid="idk").json()
    assert body["mode"] == "onboarding" and body["onboarding"]["done"]
    body = post(c, "where do they define the metric?", rid="idk").json()
    assert (body["mode"], body["reply"]) == ("chat", "Here you go.")
    assert len(model.calls) == 1


def test_bad_requests_are_4xx(chat_env):
    c, _ = chat_env
    assert c.post("/chat/p1", json={"reviewer_id": "a b", "message": "x"}).status_code == 400
    assert c.post("/chat/p1", json={"reviewer_id": "rev", "message": ""}).status_code == 422
    assert c.post("/chat/p1", json={"reviewer_id": "rev"}).status_code == 422
    assert c.post("/chat/nope", json={"reviewer_id": "rev", "message": "x"}).status_code == 404
