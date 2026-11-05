"""Item 7: the old guided flow stays, behind a toggle, unchanged."""
import pathlib
import subprocess

import pytest

from app import main
from conftest import make_reviewer

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Every endpoint of the old guided flow (and the shared ones it uses). None may disappear or change method.
OLD_FLOW = {
    ("POST", "/papers"), ("GET", "/papers/{pid}/pdf"), ("GET", "/papers/{pid}/spans"), ("GET", "/walk/{pid}"),
    ("POST", "/explain"), ("POST", "/ask"), ("GET", "/thread/{pid}"), ("POST", "/teachback"), ("POST", "/guide"),
    ("POST", "/pointers"), ("GET", "/facts/{pid}"), ("POST", "/verify"), ("POST", "/dispute"), ("POST", "/events"),
    ("GET", "/state/{pid}"), ("GET", "/notes/{pid}"), ("GET", "/draft/{pid}"), ("GET", "/history/{pid}"),
    ("POST", "/sort"), ("POST", "/draft"), ("GET", "/criteria"), ("GET", "/criteria/diagnose"),
    ("GET", "/criteria/status/{pid}"), ("GET", "/scores/{pid}"), ("POST", "/score"), ("POST", "/talk"),
    ("POST", "/skip"), ("GET", "/skips/{pid}"), ("POST", "/finish/{pid}"), ("GET", "/brief/{pid}"),
    ("POST", "/brief"), ("POST", "/select"), ("POST", "/explain_spans"), ("POST", "/ask_selection"),
    ("POST", "/intent"), ("POST", "/help/highlights"), ("POST", "/help/bear"), ("POST", "/help/plan"),
}
# Source files of the old flow. They are not edited by the chat-first work.
OLD_FLOW_FILES = ["chat.py", "criterion.py", "guide.py", "helper.py", "brief.py", "pointers.py", "factcheck.py",
                  "ingest.py", "criteria.py", "verify.py"]


def routes():
    return {(m, r.path) for r in main.app.routes for m in getattr(r, "methods", set()) if m not in ("HEAD", "OPTIONS")}


def test_every_old_flow_endpoint_is_still_registered_with_the_same_method():
    assert OLD_FLOW <= routes(), sorted(OLD_FLOW - routes())


def test_the_chat_endpoint_and_config_are_additions_not_replacements():
    assert {("POST", "/chat/{pid}"), ("GET", "/config")} <= routes()


def test_the_old_flows_source_files_are_unchanged_since_the_chat_first_work_began():
    base = "6c792ef"  # the CLAUDE.md commit this work started from
    out = subprocess.run(["git", "diff", "--stat", base, "--", *[f"backend/app/{f}" for f in OLD_FLOW_FILES]],
                         capture_output=True, text=True, cwd=ROOT)
    if out.returncode != 0:
        pytest.skip("git history not available")
    assert out.stdout.strip() == "", out.stdout


def test_the_default_flow_is_chat(chat_env, monkeypatch):
    c, set_model = chat_env
    monkeypatch.delenv("COPILOT_FLOW", raising=False)
    assert c.get("/config").json() == {"flow": "chat", "chat_enabled": True, "modes": ["chat", "guided"], "boot_id": None}
    set_model({"reply": "Hello."})
    make_reviewer("rev")
    assert c.post("/chat/p1", json={"reviewer_id": "rev", "message": "hi"}).status_code == 200


def test_the_toggle_turns_chat_off_and_leaves_the_old_flow_serving(chat_env, monkeypatch):
    c, set_model = chat_env
    model = set_model({"reply": "should not run"})
    make_reviewer("rev")
    monkeypatch.setenv("COPILOT_FLOW", "guided")
    assert c.get("/config").json() == {"flow": "guided", "chat_enabled": False, "modes": ["chat", "guided"], "boot_id": None}
    r = c.post("/chat/p1", json={"reviewer_id": "rev", "message": "hi"})
    assert r.status_code == 409 and r.json()["error"] == "chat_disabled" and not model.calls
    # the old flow's endpoints answer as before
    assert c.get("/criteria").status_code == 200
    assert c.get("/state/p1").json() == []
    assert c.post("/events", json={"paper_id": "p1", "type": "note_added",
                                   "payload": {"id": 1, "field": "weaknesses", "text": "x"}}).status_code == 200
    assert [n["text"] for n in c.get("/notes/p1").json()] == ["x"]
    assert c.post("/intent", json={"paper_id": "p1", "text": "idk", "criterion": "weaknesses", "last_q": "q",
                                   "stage": "ask"}).json()["intent"] == "dontknow"


def test_switching_back_turns_chat_on_again(chat_env, monkeypatch):
    c, set_model = chat_env
    set_model({"reply": "Back."})
    make_reviewer("rev")
    monkeypatch.setenv("COPILOT_FLOW", "guided")
    assert c.post("/chat/p1", json={"reviewer_id": "rev", "message": "hi"}).status_code == 409
    monkeypatch.setenv("COPILOT_FLOW", "chat")
    assert c.post("/chat/p1", json={"reviewer_id": "rev", "message": "hi"}).status_code == 200


def test_an_unknown_value_falls_back_to_chat_with_a_warning(chat_env, monkeypatch, caplog):
    c, _ = chat_env
    monkeypatch.setenv("COPILOT_FLOW", "banana")
    with caplog.at_level("WARNING", logger="copilot"):
        assert c.get("/config").json()["flow"] == "chat"
    assert any("COPILOT_FLOW" in r.getMessage() for r in caplog.records)


def test_the_old_flow_still_runs_end_to_end_without_the_chat_modules(chat_env):
    """The guided flow's own pieces work on their own: no chat state is needed or created."""
    c, _ = chat_env
    before = len(main.store.events("p1"))
    assert c.post("/intent", json={"paper_id": "p1", "text": "nothing else", "criterion": "weaknesses",
                                   "last_q": "q", "stage": "confirm"}).json()["intent"] == "done"
    types = {e["type"] for e in main.store.events("p1")[before:]}
    assert types == {"intent"}
