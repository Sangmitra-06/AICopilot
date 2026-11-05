"""Item 1: the opening turn. When onboarding is closed and a paper is attached for the first time, the app speaks
first. With summary_preference before_reading the first message is a descriptive, claim-based summary with section
pointers, produced through the normal neutrality checks. After reading / none / unset: no summary. Once per paper.
"""
import pytest

from app import chat_checks as cc, store
from app.verify import BANNED
from conftest import asked, make_reviewer

SUMMARY = ("The authors say they study probing of syntax in pretrained encoders [s1]. They list a new probing dataset "
           "and a layer-wise analysis as contributions [s2]. They report accuracy of 71.2 on SST-2 [s4].")


def open_(c, rid="rev", pid="p1"):
    r = c.post(f"/chat/{pid}/open", json={"reviewer_id": rid})
    assert r.status_code == 200, r.text
    return r.json()


def before(rid="rev"):
    make_reviewer(rid, summary_preference="Before I read it, a short one please.",
                  summary_preference__value="before_reading")


def assistant_turns(pid="p1"):
    return [t for t in store.thread(pid) if t.get("kind") == "chat" and t["role"] == "assistant"]


def test_before_reading_opens_with_a_descriptive_summary_with_pointers(chat_env):
    c, set_model = chat_env
    before()
    model = set_model({"reply": SUMMARY})
    body = open_(c)
    assert body["opened"] is True
    first = body["messages"][0]
    assert first["kind"] == "summary" and "[s" not in first["reply"]          # no raw ids
    assert "(Abstract)" in first["reply"] and "(Section 1)" in first["reply"] and "(Section 4)" in first["reply"]
    assert {x["id"] for x in first["cites"]} == {"s1", "s2", "s4"}
    assert not BANNED.search(first["reply"])
    assert len(asked(model)) == 1
    assert "short summary before they read" in asked(model)[-1][0]["content"]                    # the opening directive reached the model


def test_the_summary_goes_through_the_normal_neutrality_checks(chat_env):
    c, set_model = chat_env
    before()
    model = set_model({"reply": "This is a novel and strong paper [s1]."}, {"reply": SUMMARY})
    body = open_(c)
    assert len(asked(model)) == 2                                                # rejected once, regenerated
    assert "novel" not in body["messages"][0]["reply"]
    assert any("evaluative" in str(m.get("content", "")) for m in asked(model)[1])


def test_a_summary_without_pointers_is_not_accepted(chat_env):
    c, set_model = chat_env
    before()
    model = set_model({"reply": "The authors say they study probing of syntax in pretrained encoders."},
                      {"reply": SUMMARY})
    body = open_(c)
    assert len(asked(model)) == 2 and "(Section 4)" in body["messages"][0]["reply"]


@pytest.mark.parametrize("bad", ["Yes, it is novel and well executed [s1].", "Great paper, I would accept it [s1]."])
def test_a_model_that_only_judges_never_reaches_the_reviewer(chat_env, bad):
    c, set_model = chat_env
    before()
    set_model({"reply": bad})
    body = open_(c)
    shown = " ".join(m["reply"] for m in body["messages"])
    assert not BANNED.search(shown) and cc.FALLBACK not in shown                # no summary, and no fallback apology
    assert [m["kind"] for m in body["messages"]] == ["section"]                # (the walk's first section still comes)
    assert open_(c)["opened"] is False                                         # and it is not retried forever


def test_a_down_model_is_no_summary_not_a_500(chat_env, monkeypatch):
    c, set_model = chat_env
    before()

    def boom(msgs):
        raise RuntimeError("model down")
    from app import chatflow
    monkeypatch.setattr(chatflow, "_chat", boom)
    body = open_(c)
    assert [m["kind"] for m in body["messages"]] == ["section"]


@pytest.mark.parametrize("said", [
    {"summary_preference": "After I have read it.", "summary_preference__value": "after_reading"},
    {"summary_preference": "No summaries for me.", "summary_preference__value": "none"},
    {"summary_preference": "Only if I ask.", "summary_preference__value": "on_request"},
    {},                                                                         # skipped: the stored default
])
def test_after_reading_none_or_unset_skips_the_summary(chat_env, said):
    c, set_model = chat_env
    make_reviewer("rev", **said)
    model = set_model({"reply": SUMMARY})
    body = open_(c)
    assert asked(model) == []                                                    # not even asked
    assert [m["kind"] for m in body["messages"]] == ["section"]                 # no summary: only the first section
    assert [t["meta"]["opening"] for t in assistant_turns()] == ["section"]


def test_the_opening_is_made_once_per_paper_even_after_a_reload(chat_env):
    c, set_model = chat_env
    before()
    model = set_model({"reply": SUMMARY})
    assert open_(c)["opened"] is True
    again = open_(c)                                                            # a reload asks again
    assert again["opened"] is False and again["messages"] == [] and again["reason"] == "already"
    assert len(asked(model)) == 1
    assert len(assistant_turns()) == 2                                          # the summary and the first section
    assert [e["type"] for e in store.events("p1") if e["type"] == "opening_made"] == ["opening_made"]


def test_the_opening_is_logged_without_a_user_turn_and_survives_a_reload(chat_env):
    c, set_model = chat_env
    before()
    set_model({"reply": SUMMARY})
    open_(c)
    turns = [t for t in store.thread("p1") if t.get("kind") == "chat"]
    assert [t["role"] for t in turns] == ["assistant", "assistant"]
    assert turns[0]["meta"]["cites"] == ["s1", "s2", "s4"] and turns[0]["meta"]["parts"]
    shown = c.get("/thread/p1").json()
    assert [x["text"] for x in shown[-2:]] == [x["text"] for x in turns]


def test_no_opening_while_onboarding_is_open_and_it_happens_when_it_closes(chat_env):
    c, set_model = chat_env
    make_reviewer("rev", closed=False, summary_preference="Before, please.", summary_preference__value="before_reading")
    model = set_model({"reply": SUMMARY})
    body = open_(c)
    assert body == {"opened": False, "messages": [], "reason": "onboarding"} and asked(model) == []
    store.log(store.reviewer_key("rev"), "onboarding_closed", {"reason": "complete", "defaulted": []})
    assert open_(c)["opened"] is True


def test_unknown_paper_and_bad_reviewer_id(chat_env):
    c, _ = chat_env
    assert c.post("/chat/nope/open", json={"reviewer_id": "rev"}).status_code == 404
    assert c.post("/chat/p1/open", json={"reviewer_id": "bad id!"}).status_code == 400


def test_chat_check_require_pointer_is_off_by_default():
    assert cc.reply_errors("Hello there.", {}) == []
    assert any("pointer" in e for e in cc.reply_errors("Hello there.", {"require_pointer": True}))
    assert cc.reply_errors("The authors report X (Section 3).", {"require_pointer": True}) == []
