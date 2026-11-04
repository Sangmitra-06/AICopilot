"""Shared setup for the backend tests.

- Puts backend/ on sys.path so tests import `app.*` the way uvicorn does.
- Gives llm.py the env vars it reads at import time.
- Stubs pymupdf when it is not installed (no test here opens a PDF).
- Blocks real model calls: a test that reaches the network fails loudly.
"""
import os
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import tempfile

# store.py opens COPILOT_DB when it is imported. Point it at a throwaway file first so the suite never
# creates or writes the real copilot.db (set before any `app` import below or in test modules).
os.environ.setdefault("COPILOT_DB", os.path.join(tempfile.mkdtemp(prefix="copilot-tests-"), "events.db"))
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("MODEL", "test-model")

try:
    import pymupdf  # noqa: F401
except ImportError:
    sys.modules["pymupdf"] = types.ModuleType("pymupdf")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    from app import llm

    def boom(*a, **k):
        raise AssertionError("test tried to call the model; stub _chat instead")

    monkeypatch.setattr(llm.client.chat.completions, "create", boom)
