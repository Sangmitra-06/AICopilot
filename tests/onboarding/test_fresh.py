"""Item 5: COPILOT_FRESH=1 (dev only, off by default) wipes and recreates the database and the data folder at startup;
GET /config carries a boot id then; GET /papers/{pid}/pdf is a 404 (never a 500) when the file is missing."""
import os
import sqlite3
import subprocess
import sys
import pathlib

import pytest
from fastapi.testclient import TestClient

from app import fresh, main

BACKEND = str(pathlib.Path(__file__).resolve().parents[2] / "backend")


def make_state(tmp_path):
    db, data = tmp_path / "events.db", tmp_path / "data"
    data.mkdir()
    (data / "abc.pdf").write_bytes(b"%PDF-old")
    con = sqlite3.connect(db)
    con.execute("create table events(id integer primary key, ts real, paper text, type text, payload text)")
    con.execute("insert into events(ts,paper,type,payload) values(1,'abc','note_added','{}')")
    con.commit()
    con.close()
    return db, data


# ------------------------------------------------------------------ off by default

@pytest.mark.parametrize("env", [{}, {"COPILOT_FRESH": ""}, {"COPILOT_FRESH": "0"}, {"COPILOT_FRESH": "no"}])
def test_off_unless_set_to_1(tmp_path, env):
    db, data = make_state(tmp_path)
    assert fresh.apply({**env, "COPILOT_DB": str(db), "COPILOT_DATA_DIR": str(data)}) is False
    assert db.exists() and (data / "abc.pdf").exists()


def test_on_deletes_and_recreates_the_data_folder_and_removes_the_database(tmp_path):
    db, data = make_state(tmp_path)
    (tmp_path / "events.db-wal").write_bytes(b"x")
    assert fresh.apply({"COPILOT_FRESH": "1", "COPILOT_DB": str(db), "COPILOT_DATA_DIR": str(data)}) is True
    assert not db.exists() and not (tmp_path / "events.db-wal").exists()
    assert data.is_dir() and list(data.iterdir()) == []                      # recreated, and empty


def test_on_with_nothing_there_yet_still_creates_the_folder(tmp_path):
    data = tmp_path / "newdata"
    assert fresh.apply({"COPILOT_FRESH": "1", "COPILOT_DB": str(tmp_path / "e.db"), "COPILOT_DATA_DIR": str(data)})
    assert data.is_dir()


@pytest.mark.parametrize("where", [".", "", "/"])
def test_it_refuses_to_wipe_the_working_directory_or_a_root(tmp_path, monkeypatch, where):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "keep.txt").write_text("x")
    with pytest.raises(RuntimeError):
        fresh.apply({"COPILOT_FRESH": "1", "COPILOT_DB": str(tmp_path / "e.db"), "COPILOT_DATA_DIR": where})
    assert (tmp_path / "keep.txt").exists()


def run_import(db, data, **flags):
    code = ("import os; from app import store, main; "
            "print(len(store.events('abc')), os.path.exists(os.path.join(os.environ['COPILOT_DATA_DIR'], 'abc.pdf')))")
    env = {k: v for k, v in os.environ.items() if k != "COPILOT_FRESH"}
    env.update(COPILOT_DB=str(db), COPILOT_DATA_DIR=str(data), OPENROUTER_API_KEY="x", MODEL="x", **flags)
    out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout.split()[-2:]


def test_importing_the_store_with_the_flag_starts_from_an_empty_database(tmp_path):
    db, data = make_state(tmp_path)
    assert run_import(db, data, COPILOT_FRESH="1") == ["0", "False"]


def test_importing_the_store_without_the_flag_touches_nothing(tmp_path):
    db, data = make_state(tmp_path)
    assert run_import(db, data) == ["1", "True"]


# ------------------------------------------------------------------ the boot id

def test_config_has_no_boot_id_unless_fresh(monkeypatch):
    monkeypatch.setattr(fresh, "BOOT_ID", None)
    with TestClient(main.app) as c:
        body = c.get("/config").json()
    assert "boot_id" in body and body["boot_id"] is None
    assert body["flow"] == "chat"                                              # the rest of /config is unchanged


def test_config_returns_the_boot_id_when_fresh(monkeypatch):
    monkeypatch.setattr(fresh, "BOOT_ID", "boot-123")
    with TestClient(main.app) as c:
        assert c.get("/config").json()["boot_id"] == "boot-123"


def test_every_start_has_its_own_boot_id():
    ids = {fresh.new_boot_id() for _ in range(5)}
    assert len(ids) == 5 and all(len(i) >= 16 for i in ids)


# ------------------------------------------------------------------ a missing PDF is a 404

def test_a_missing_pdf_is_404_not_500(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATA_DIR", str(tmp_path))
    with TestClient(main.app, raise_server_exceptions=False) as c:
        r = c.get("/papers/nope/pdf")
    assert r.status_code == 404


def test_an_existing_pdf_is_still_served(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATA_DIR", str(tmp_path))
    (tmp_path / "abc.pdf").write_bytes(b"%PDF-1.4 hi")
    with TestClient(main.app) as c:
        r = c.get("/papers/abc/pdf")
    assert r.status_code == 200 and r.content == b"%PDF-1.4 hi"
