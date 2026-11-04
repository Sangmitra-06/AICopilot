"""HTTP-level tests: FastAPI's TestClient against the real app, with a throwaway database.

The module-level connection in store.py is swapped for a file under pytest's tmp_path, so nothing here
touches copilot.db. Model calls are blocked by tests/conftest.py, which is what a down model looks like.
"""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import main, store

ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
FIELDS = ["reading_order", "workflow_mode", "summary_preference", "note_habit", "excellent_review_example",
          "bad_review_traits", "strength_criteria", "weakness_criteria", "over_under_penalize", "hardest_part",
          "experience_level"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = sqlite3.connect(tmp_path / "events.db", check_same_thread=False)
    db.execute("create table events(id integer primary key, ts real, paper text, type text, payload text)")
    db.commit()
    monkeypatch.setattr(store, "db", db)
    with TestClient(main.app) as c:  # the context manager runs the app's startup, as uvicorn would
        yield c
    db.close()


def rows():
    return store.db.execute("select count(*) from events").fetchone()[0]


def answer(client, rid, text):
    return client.post(f"/onboarding/{rid}/answer", json={"text": text})


def test_importing_the_app_in_tests_never_opens_the_real_copilot_db():
    path = store.db.execute("pragma database_list").fetchone()[2].replace("\\", "/")
    assert not path.endswith("/copilot.db") and "copilot-tests-" in path


def test_the_tests_use_a_temporary_database(client, tmp_path):
    path = store.db.execute("pragma database_list").fetchone()[2]
    assert path.replace("\\", "/").startswith(str(tmp_path).replace("\\", "/"))
    assert not path.endswith("copilot.db")


# ------------------------------------------------------------------ GET /onboarding/{rid}

def test_get_returns_the_first_question(client):
    r = client.get("/onboarding/rev1")
    assert r.status_code == 200
    body = r.json()
    assert body["done"] is False and body["field"] == "papers_reviewed" and body["kind"] == "question"
    assert "how many papers" in body["question"].lower() and body["turn"] == 0 and body["max_turns"] == 14
    assert body["profile"]["closed"] is None


def test_repeating_the_get_logs_nothing_new(client):
    first = client.get("/onboarding/rev1").json()
    n = rows()
    assert n >= 1
    for _ in range(3):
        again = client.get("/onboarding/rev1").json()
        assert again == first
    assert rows() == n


# ------------------------------------------------------------------ POST /onboarding/{rid}/answer

def test_post_with_valid_json_advances(client):
    client.get("/onboarding/rev1")
    r = answer(client, "rev1", "7 papers")
    assert r.status_code == 200
    body = r.json()
    assert body["field"] == "subarea_familiarity" and body["turn"] == 1
    assert body["profile"]["evidence"]["papers_reviewed"]["value"] == 7
    assert body["reflect"] == "7 papers"


def test_progress_survives_a_new_client_because_state_is_in_the_event_log(client):
    client.get("/onboarding/rev1")
    answer(client, "rev1", "7 papers")
    with TestClient(main.app) as other:
        assert other.get("/onboarding/rev1").json()["field"] == "subarea_familiarity"


@pytest.mark.parametrize("kwargs", [
    {"content": "{not json", "headers": {"content-type": "application/json"}},
    {"content": "", "headers": {"content-type": "application/json"}},
    {"content": "[]", "headers": {"content-type": "application/json"}},
    {"json": {}},
    {"json": {"answer": "7 papers"}},      # wrong field name: the field is "text"
    {"json": {"text": None}},
    {"json": {"text": 7}},
    {"content": "text=7", "headers": {"content-type": "application/x-www-form-urlencoded"}},
])
def test_bad_bodies_are_a_4xx_not_a_500_and_log_nothing(client, kwargs):
    client.get("/onboarding/rev1")
    n = rows()
    r = client.post("/onboarding/rev1/answer", **kwargs)
    assert 400 <= r.status_code < 500, (r.status_code, r.text)
    assert rows() == n


# ------------------------------------------------------------------ an answer before the first question

def test_an_answer_before_the_first_question_is_a_409_carrying_the_current_question(client):
    r = answer(client, "fresh", "7 papers")
    assert r.status_code == 409
    body = r.json()
    assert body["error"] == "no_question_pending" and "fetch" in body["message"].lower()
    assert body["done"] is False and body["field"] == "papers_reviewed" and body["kind"] == "question"
    assert "how many papers" in body["question"].lower() and body["turn"] == 0


def test_the_409_changes_nothing_and_the_answer_is_not_recorded(client):
    for _ in range(3):
        assert answer(client, "fresh", "7 papers").status_code == 409
    assert rows() == 0  # no question was logged, no answer was logged
    p = client.get("/profile/fresh").json()
    assert p["evidence"]["papers_reviewed"] is None and p["turn"] == 0


def test_the_question_in_the_409_is_the_one_a_get_then_returns(client):
    conflict = answer(client, "fresh", "7 papers").json()
    fetched = client.get("/onboarding/fresh")
    assert fetched.status_code == 200
    got = fetched.json()
    for k in ("done", "field", "kind", "question", "turn", "max_turns"):
        assert got[k] == conflict[k]


def test_after_the_409_a_fetch_then_an_answer_works_normally(client):
    assert answer(client, "fresh", "7 papers").status_code == 409
    client.get("/onboarding/fresh")
    r = answer(client, "fresh", "7 papers")
    assert r.status_code == 200 and r.json()["field"] == "subarea_familiarity"
    assert r.json()["profile"]["evidence"]["papers_reviewed"]["value"] == 7


def test_a_409_carries_cors_headers_for_the_frontend(client):
    r = client.post("/onboarding/fresh/answer", json={"text": "3"}, headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 409 and r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_a_malformed_body_is_still_a_422_before_any_question(client):
    assert client.post("/onboarding/fresh/answer", json={}).status_code == 422
    assert client.post("/onboarding/fresh/answer", content="{no", headers={"content-type": "application/json"}).status_code == 422
    assert rows() == 0


def test_a_bad_reviewer_id_is_a_400_not_a_409(client):
    assert answer(client, "a%20b", "3").status_code == 400


def test_one_reviewers_started_session_does_not_make_another_reviewers_answer_valid(client):
    client.get("/onboarding/started")
    assert answer(client, "started", "7 papers").status_code == 200
    assert answer(client, "never-fetched", "7 papers").status_code == 409


def test_an_answer_after_onboarding_closed_is_still_a_200_and_changes_nothing(client):
    body = client.get("/onboarding/done").json()
    while not body["done"]:
        body = answer(client, "done", "idk").json()
    n = rows()
    r = answer(client, "done", "7 papers")
    assert r.status_code == 200 and r.json()["done"] is True and rows() == n


@pytest.mark.parametrize("rid", ["a%20b", "x" * 65, "a%3Ab"])
def test_odd_reviewer_ids_are_a_400(client, rid):
    assert client.get(f"/onboarding/{rid}").status_code == 400
    assert answer(client, rid, "hi").status_code == 400
    assert client.get(f"/profile/{rid}").status_code == 400
    assert rows() == 0


def test_an_idk_to_everything_session_finishes_over_http(client):
    body = client.get("/onboarding/idk").json()
    for _ in range(30):
        if body["done"]:
            break
        r = answer(client, "idk", "idk")
        assert r.status_code == 200
        body = r.json()
    assert body["done"] and body["reason"] == "complete" and body["turn"] == 12
    assert client.get("/onboarding/idk").json()["done"] is True  # stays closed


def test_a_down_model_never_blocks_the_flow_over_http(client):
    body = client.get("/onboarding/m").json()
    while body["field"] != "hardest_part":
        body = answer(client, "m", "idk").json()
    # The rules accept this reply, so the on-topic check is consulted; the blocked model call raises.
    # The rules' verdict stands: the answer is kept and onboarding moves on.
    r = answer(client, "m", "deciding how much detail to put in")
    assert r.status_code == 200 and r.json()["field"] != "hardest_part"
    assert r.json()["profile"]["fields"]["hardest_part"]["value"] == "deciding how much detail to put in"
    # And what the rules reject stays rejected, with or without a model.
    r = answer(client, "m", "the weather is lovely")
    assert r.status_code == 200 and r.json()["kind"] == "followup"


# ------------------------------------------------------------------ GET /profile/{rid}

def test_profile_returns_the_eleven_fields(client):
    r = client.get("/profile/rev1")
    assert r.status_code == 200
    body = r.json()
    assert sorted(body["fields"]) == sorted(FIELDS) and len(body["fields"]) == 11
    assert all(v is None for v in body["fields"].values())  # nothing collected yet
    assert set(body["evidence"]) == {"papers_reviewed", "subarea_familiarity"}
    assert body["turn"] == 0 and body["closed"] is None


def test_profile_fills_in_as_the_reviewer_answers_and_is_per_reviewer(client):
    client.get("/onboarding/a")
    answer(client, "a", "40 papers")
    answer(client, "a", "this is my area")
    p = client.get("/profile/a").json()
    assert p["fields"]["experience_level"]["value"] == "high" and p["fields"]["experience_level"]["source"] == "inferred"
    assert client.get("/profile/b").json()["fields"]["experience_level"] is None


# ------------------------------------------------------------------ CORS

@pytest.mark.parametrize("origin", ORIGINS)
def test_cors_headers_are_present_for_the_frontend_origins(client, origin):
    for r in (client.get("/profile/rev1", headers={"Origin": origin}),
              client.get("/onboarding/rev1", headers={"Origin": origin}),
              client.post("/onboarding/rev1/answer", json={"text": "3"}, headers={"Origin": origin})):
        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize("origin", ORIGINS)
def test_cors_preflight_for_a_json_post_succeeds(client, origin):
    r = client.options("/onboarding/rev1/answer", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == origin
    assert "POST" in r.headers["access-control-allow-methods"]
    assert "content-type" in r.headers["access-control-allow-headers"].lower()
    assert rows() == 0  # a preflight is not a request


@pytest.mark.parametrize("origin", ["https://evil.example", "http://localhost.evil.example:5173", "http://192.168.1.5:5173"])
def test_other_origins_get_no_cors_headers(client, origin):
    r = client.get("/profile/rev1", headers={"Origin": origin})
    assert "access-control-allow-origin" not in r.headers
