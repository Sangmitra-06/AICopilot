"""Packaging the app for a tester behind a tunnel (see DEMO.md): one process serves the API and the built frontend, an
optional password gate (DEMO_PASSWORD), a daily chat-call guard (MAX_CHAT_CALLS_PER_DAY), a paper id per reviewer AND
per paper (so the same PDF used by a second person still gets the opening), and a suite that does not depend on the
caller's shell."""
import base64
import logging
import os
import pathlib
import subprocess
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import demo, main, store
from conftest import PAPER, make_reviewer

ROOT = pathlib.Path(__file__).resolve().parents[2]
SUMMARY = ("The authors say they study probing of syntax in pretrained encoders [s1]. They list a new probing dataset "
           "and a layer-wise analysis as contributions [s2]. They report accuracy of 71.2 on SST-2 [s4].")


def basic(pw, user="tester"):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}


# ------------------------------------------------------------------ access gate

def test_without_demo_password_nothing_is_gated(chat_env):
    c, _ = chat_env
    assert c.get("/config").status_code == 200


def test_with_demo_password_every_request_needs_it(chat_env, monkeypatch):
    c, _ = chat_env
    monkeypatch.setenv("DEMO_PASSWORD", "s3cret-pass")
    for path in ("/config", "/onboarding/rev", "/papers/p1/spans", "/"):
        r = c.get(path)
        assert r.status_code == 401, path
        assert r.headers["www-authenticate"].startswith("Basic ")
        assert "s3cret-pass" not in r.text
    assert c.get("/config", headers=basic("wrong")).status_code == 401
    assert c.post("/chat/p1", json={"reviewer_id": "rev", "message": "hi"}).status_code == 401
    assert c.get("/config", headers=basic("s3cret-pass")).status_code == 200
    assert c.get("/config", headers=basic("s3cret-pass", user="")).status_code == 200      # any user name


def test_malformed_authorization_headers_are_refused_not_a_500(chat_env, monkeypatch):
    c, _ = chat_env
    monkeypatch.setenv("DEMO_PASSWORD", "pw")
    for h in ("Basic", "Basic !!!", "Bearer pw", "Basic " + base64.b64encode(b"no-colon").decode(),
              "Basic " + base64.b64encode(b"\xff\xfe:pw").decode()):
        assert c.get("/config", headers={"Authorization": h}).status_code == 401, h


def test_the_password_is_never_logged(chat_env, monkeypatch, caplog):
    c, _ = chat_env
    monkeypatch.setenv("DEMO_PASSWORD", "never-log-me")
    caplog.set_level(logging.DEBUG)
    c.get("/config")
    c.get("/config", headers=basic("wrong"))
    c.get("/config", headers=basic("never-log-me"))
    assert "never-log-me" not in caplog.text


# ------------------------------------------------------------------ spend guard

def test_the_daily_limit_defaults_to_500_and_reads_the_env():
    assert demo.limit({}) == 500 and demo.limit({"MAX_CHAT_CALLS_PER_DAY": ""}) == 500
    assert demo.limit({"MAX_CHAT_CALLS_PER_DAY": "3"}) == 3
    assert demo.limit({"MAX_CHAT_CALLS_PER_DAY": "lots"}) == 500


def test_chat_calls_stop_with_a_plain_message_once_the_limit_is_reached(chat_env, monkeypatch):
    c, set_model = chat_env
    make_reviewer("rev")
    monkeypatch.setenv("MAX_CHAT_CALLS_PER_DAY", "2")
    model = set_model({"reply": "Section 4 reports the results."})
    for _ in range(2):
        assert not c.post("/chat/p1", json={"reviewer_id": "rev", "message": "what does section 4 say?"}).json().get("limited")
    calls, turns = len(model.calls), len(store.thread("p1"))
    r = c.post("/chat/p1", json={"reviewer_id": "rev", "message": "and section 5?"})
    assert r.status_code == 200
    body = r.json()
    assert body["limited"] is True and body["reply"] == demo.LIMIT_MESSAGE and body["mode"] == "chat"
    assert len(model.calls) == calls                       # no model call
    assert len(store.thread("p1")) == turns                # nothing logged to the thread
    assert demo.used() == 2


def test_an_opening_counts_once_and_is_refused_politely_at_the_limit(chat_env, monkeypatch):
    c, set_model = chat_env
    make_reviewer("rev", summary_preference="Before I read it.", summary_preference__value="before_reading")
    set_model({"reply": SUMMARY})
    monkeypatch.setenv("MAX_CHAT_CALLS_PER_DAY", "0")
    body = c.post("/chat/p1/open", json={"reviewer_id": "rev"}).json()
    assert body["reason"] == "limit" and body["messages"][0]["reply"] == demo.LIMIT_MESSAGE
    assert not store.walk_state("p1")["opened"]            # tried again once the limit allows it
    monkeypatch.setenv("MAX_CHAT_CALLS_PER_DAY", "1")
    assert c.post("/chat/p1/open", json={"reviewer_id": "rev"}).json()["opened"] is True
    assert c.post("/chat/p1/open", json={"reviewer_id": "rev"}).json()["reason"] == "already"   # a reload: not counted
    assert demo.used() == 1


def test_an_opening_while_onboarding_is_open_is_not_counted(chat_env):
    c, _ = chat_env
    make_reviewer("rev", closed=False)
    assert c.post("/chat/p1/open", json={"reviewer_id": "rev"}).json()["reason"] == "onboarding"
    assert demo.used() == 0


# ------------------------------------------------------------------ per reviewer and per paper

@pytest.fixture
def uploads(chat_env, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(main, "spans_of", lambda pid: PAPER)
    c, set_model = chat_env

    def up(rid=None, data=b"%PDF-1.4 the same public paper"):
        url = "/papers" + (f"?reviewer_id={rid}" if rid else "")
        r = c.post(url, files={"file": ("paper.pdf", data, "application/pdf")})
        assert r.status_code == 200, r.text
        return r.json()["paper_id"]
    return c, set_model, up


def test_the_paper_id_is_per_reviewer_and_per_paper(uploads):
    _, _, up = uploads
    a, b = up("alice"), up("bob")
    assert a != b
    assert up("alice") == a                                # the same person, the same file: the same id
    assert up("alice", b"%PDF another paper") != a
    assert up() == main.paper_id(b"%PDF-1.4 the same public paper")   # no reviewer id: the file hash, as before


def test_a_bad_reviewer_id_on_upload_is_a_400(uploads):
    c, _, _ = uploads
    r = c.post("/papers?reviewer_id=../x", files={"file": ("p.pdf", b"%PDF", "application/pdf")})
    assert r.status_code == 400


def test_the_same_pdf_used_by_a_second_person_still_gets_the_opening_summary(uploads):
    c, set_model, up = uploads
    for rid in ("alice", "bob"):
        make_reviewer(rid, summary_preference="Before I read it, a short one please.",
                      summary_preference__value="before_reading")
    set_model({"reply": SUMMARY})
    first = c.post(f"/chat/{up('alice')}/open", json={"reviewer_id": "alice"}).json()
    second = c.post(f"/chat/{up('bob')}/open", json={"reviewer_id": "bob"}).json()
    assert first["opened"] and second["opened"]
    assert first["messages"][0]["kind"] == "summary" and second["messages"][0]["kind"] == "summary"
    # and each has their own thread: nothing of alice's shows up for bob
    assert len([t for t in c.get(f"/thread/{up('bob')}").json() if t["role"] == "assistant"]) == len(second["messages"])


# ------------------------------------------------------------------ the built frontend on the same origin

def test_the_built_frontend_is_served_after_the_api_routes(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>copilot</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    app = FastAPI()
    app.get("/config")(lambda: {"flow": "chat"})
    assert main.mount_frontend(app, dist) is True
    c = TestClient(app)
    assert "<title>copilot</title>" in c.get("/").text
    assert c.get("/assets/app.js").text == "console.log(1)"
    assert c.get("/config").json() == {"flow": "chat"}     # the API still wins


def test_no_build_means_no_mount(tmp_path):
    assert main.mount_frontend(FastAPI(), tmp_path / "missing") is False


def test_the_frontend_mount_is_the_last_route_of_the_real_app():
    if main.FRONTEND_SERVED:
        assert main.app.routes[-1].name == "frontend"


def test_the_chat_frontend_has_no_hard_coded_backend_host():
    src = (ROOT / "frontend" / "src" / "chat" / "api.js").read_text(encoding="utf-8")
    assert "127.0.0.1" not in src and "localhost" not in src


# ------------------------------------------------------------------ the suite ignores the caller's shell

def test_the_suite_does_not_depend_on_the_callers_shell(tmp_path):
    """A shell with COPILOT_FRESH=1, RUN_LIVE=1, DEMO_PASSWORD and COPILOT_DB/COPILOT_DATA_DIR pointing somewhere real:
    the tests still pass, the live tests are still skipped, and nothing is created at those paths."""
    shell_db, shell_data = tmp_path / "shell.db", tmp_path / "shell-data"
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    env.update(COPILOT_FRESH="1", RUN_LIVE="1", DEMO_PASSWORD="x", COPILOT_FLOW="guided", MAX_CHAT_CALLS_PER_DAY="0",
               COPILOT_DB=str(shell_db), COPILOT_DATA_DIR=str(shell_data))
    files = ["tests/neutrality/test_flow_toggle.py", "tests/neutrality/test_walk_live.py",
             "tests/neutrality/test_walk_opening.py"]
    out = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *files], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stdout[-2000:] + out.stderr[-2000:]
    assert " skipped" in out.stdout.splitlines()[-1]       # the live tests: skipped without -m live
    assert not shell_db.exists() and not shell_data.exists()


@pytest.mark.parametrize("run_live,markexpr,want", [
    ("1", "live", True), ("1", "", False), ("1", "not live", False), (None, "live", False), ("0", "live", False)])
def test_live_tests_need_both_run_live_and_dash_m_live(run_live, markexpr, want):
    import live_env
    assert live_env.live_requested(markexpr, run_live=run_live or "") is want
