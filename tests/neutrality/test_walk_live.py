"""Live-model checks for the guided walk (skipped unless RUN_LIVE=1; real model calls)."""
import re

import pytest

from app import chat_checks as cc, chatflow, llm, store
from conftest import make_reviewer


@pytest.mark.live
def test_live_opening_summary_is_descriptive_with_pointers_and_passes_the_checks(chat_env, monkeypatch):
    c, _ = chat_env
    monkeypatch.setattr(chatflow, "_chat", llm._chat)
    make_reviewer("rev", reading_order="I start with the introduction.", reading_order__value="intro_first",
                  summary_preference="Before I read it, please.", summary_preference__value="before_reading")
    body = c.post("/chat/p1/open", json={"reviewer_id": "rev"}).json()
    last = [e["payload"] for e in store.events("p1") if e["type"] == "chat_check"][-1]
    assert [m["kind"] for m in body["messages"]] == ["summary", "section"], (body, last)
    summary = body["messages"][0]
    assert summary["cites"] and re.search(r"\((?:Section|Abstract)", summary["reply"]), summary["reply"]
    assert not cc.banned_hits(summary["reply"], set()) and "[s" not in summary["reply"], summary["reply"]   # (technical terms such as "weak supervision" are not ratings)
    assert body["messages"][1]["reply"].startswith("You said you like to start with the introduction, here it is")


@pytest.mark.live
def test_live_an_ordinary_question_during_the_walk_leaves_the_pointer_alone(chat_env, monkeypatch):
    c, _ = chat_env
    monkeypatch.setattr(chatflow, "_chat", llm._chat)
    make_reviewer("rev", reading_order="intro then method", reading_order__value="intro_first")
    c.post("/chat/p1/open", json={"reviewer_id": "rev"})
    body = c.post("/chat/p1", json={"reviewer_id": "rev", "message": "what does F1 measure?"}).json()
    assert store.walk_state("p1")["pointer"] == 0 and not body["reply"].startswith("Moving to")
    assert body["checks"]["fallback"] is False, body["reply"]
    moved = c.post("/chat/p1", json={"reviewer_id": "rev", "message": "ok"}).json()
    assert moved["reply"].startswith("Moving to the method, as you said") and store.walk_state("p1")["pointer"] == 1
