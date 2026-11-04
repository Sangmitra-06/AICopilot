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
