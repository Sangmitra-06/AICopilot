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

# The suite never depends on the caller's shell. Before any `app` import (below or in test modules):
# - COPILOT_DB and COPILOT_DATA_DIR always point at a throwaway folder (store.py opens the database at import), so the
#   suite never creates, reads or writes the real copilot.db or data/, whatever the shell has;
# - COPILOT_FRESH, COPILOT_FLOW, DEMO_PASSWORD and COPILOT_FRONTEND_DIST are dropped (tests that need them set them);
# - MAX_CHAT_CALLS_PER_DAY is set high, so the daily guard never trips across the suite (its own tests set it);
# - RUN_LIVE is remembered (live_env.RUN_LIVE) and dropped: live tests run only with RUN_LIVE=1 AND `-m live`.
_TMP = tempfile.mkdtemp(prefix="copilot-tests-")
_RUN_LIVE = os.environ.pop("RUN_LIVE", None)
for _name in ("COPILOT_FRESH", "COPILOT_FLOW", "DEMO_PASSWORD", "COPILOT_FRONTEND_DIST"):
    os.environ.pop(_name, None)
os.environ["COPILOT_DB"] = os.path.join(_TMP, "events.db")
os.environ["COPILOT_DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["MAX_CHAT_CALLS_PER_DAY"] = "1000000"
# Mocked tests run with dummy credentials (the real key never reaches them; the network is blocked below anyway).
# live_env keeps what the shell had for the tests marked `live` (imported before the dummies are set).
sys.path.insert(0, str(ROOT / "tests"))
import live_env  # noqa: E402
live_env.RUN_LIVE = _RUN_LIVE

os.environ.setdefault("OPENROUTER_API_KEY", live_env.DUMMY_KEY)
os.environ.setdefault("MODEL", live_env.DUMMY_MODEL)

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
