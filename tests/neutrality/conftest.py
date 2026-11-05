"""Helpers for the neutrality tests.

Offline tests mock the model through `model_says`. Tests marked `live` use the real
model; they are skipped unless RUN_LIVE=1 and are the only tests allowed past the
network block in tests/conftest.py.
"""
import json
import os
import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "loops"))  # ui_driver


def pytest_collection_modifyitems(config, items):
    if os.environ.get("RUN_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live-model test; set RUN_LIVE=1 to run")
    for it in items:
        if "live" in it.keywords:
            it.add_marker(skip)


@pytest.fixture(autouse=True)
def no_network(request, monkeypatch):
    """Same block as tests/conftest.py, lifted only for tests marked `live`."""
    if request.node.get_closest_marker("live"):
        return
    from app import llm

    def boom(*a, **k):
        raise AssertionError("test tried to call the model; stub _chat instead")
    monkeypatch.setattr(llm.client.chat.completions, "create", boom)


# One span of paper text, shaped like ingest.py output (locate() needs "segs").
TEXT = ("We report F1 on the held-out test set. We removed outliers before training because "
        "they distorted the loss. Our contributions are a new dataset and a probing method.")
SPAN = {"id": "s1", "text": TEXT, "page": 1, "lines": [10, 12], "section": "Introduction",
        "kind": "body", "segs": [(len(TEXT), 10)]}


def sentence(text, quote, kind="paper"):
    return {"text": text, "kind": kind, "source": "text", "span_ids": ["s1"], "quote": quote}


def background(text):
    """A textbook definition, not from the paper: no span, no quote."""
    return {"text": text, "kind": "background", "source": "text", "span_ids": [], "quote": None}


@pytest.fixture
def model_says(monkeypatch):
    """model_says(payload) -> list of calls. The model returns payload (a dict) as JSON."""
    from app import llm

    def install(payload):
        calls = []

        def fake(msgs):
            calls.append(msgs)
            return json.dumps(payload)
        monkeypatch.setattr(llm, "_chat", fake)
        return calls
    return install


# ---------------------------------------------------------------------------------------------------------
# Chat-first helpers: a throwaway database, a paper, reviewers with a finished profile, a scripted model.

PAPER = [
    {"id": "s1", "text": "We study probing of syntax in pretrained encoders and report accuracy on three datasets.",
     "page": 1, "lines": [1, 3], "section": "Abstract", "kind": "body", "segs": [(90, 1)]},
    {"id": "s2", "text": "Our contributions are a new probing dataset and a layer-wise analysis.",
     "page": 1, "lines": [10, 11], "section": "1 Introduction", "kind": "body", "segs": [(70, 10)]},
    {"id": "s3", "text": "We train with weak supervision from automatically parsed sentences.",
     "page": 2, "lines": [30, 31], "section": "3 Method", "kind": "body", "segs": [(70, 30)]},
    {"id": "s4", "text": "Table 2 reports accuracy of 71.2 on SST-2 and 64.0 on CoLA.",
     "page": 4, "lines": [80, 81], "section": "4 Experiments", "kind": "body", "segs": [(60, 80)]},
    {"id": "s5", "text": "Smith et al. 2019. A thing.", "page": 9, "lines": [200, 200], "section": "References",
     "kind": "body", "segs": [(30, 200)]},
]


def make_reviewer(rid, closed=True, **said):
    """Log a finished onboarding for `rid`. `said` maps profile fields to the reviewer's own words; anything
    not given is a default, as if they had skipped it."""
    import time
    from app import onboarding as ob, store
    key = store.reviewer_key(rid)
    for f in ob.FIELDS:
        val = said.get(f)
        if val is not None:
            store.log(key, "profile_field_set", {"field": f, "value": said.get(f + "__value", val),
                                                 "source": "answer", "raw": val})
        else:
            store.log(key, "profile_field_set", {"field": f, "value": ob.DEFAULTS[f], "source": "default", "raw": ""})
    if closed:
        store.log(key, "onboarding_closed", {"reason": "complete", "defaulted": []})


class Model:
    """A scripted model. Each call returns the next scripted reply (a dict, or a raw string); the last one
    repeats. `calls` keeps every message list it was sent."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies) or [{"reply": "Okay."}], []

    def __call__(self, msgs):
        self.calls.append(msgs)
        r = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        return r if isinstance(r, str) else json.dumps(r)

    @property
    def system(self):
        return self.calls[-1][0]["content"]


@pytest.fixture
def chat_env(tmp_path, monkeypatch):
    """(client, set_model) over the real app, with a temporary database and an in-memory paper 'p1'."""
    import sqlite3
    from fastapi.testclient import TestClient
    from app import main, store, chatflow
    db = sqlite3.connect(tmp_path / "events.db", check_same_thread=False)
    db.execute("create table events(id integer primary key, ts real, paper text, type text, payload text)")
    db.commit()
    monkeypatch.setattr(store, "db", db)
    monkeypatch.setitem(main.CACHE, "p1", PAPER)
    holder = {}

    def set_model(*replies):
        holder["m"] = Model(*replies)
        monkeypatch.setattr(chatflow, "_chat", holder["m"])
        return holder["m"]
    set_model()
    with TestClient(main.app) as c:
        yield c, set_model
    db.close()


def asked(model):
    """The scripted model's calls that are NOT the walk's section descriptions (summary, chat turns, ...)."""
    return [m for m in model.calls if not any("Describe the section" in x["content"] for x in m)]
