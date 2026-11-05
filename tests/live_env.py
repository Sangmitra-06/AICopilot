"""Credentials for the live-model tests.

Mocked tests run with dummy credentials (tests/conftest.py sets them before `app.llm` is imported, and blocks the
network). Tests marked `live` need the real key and model: from the shell if it set them, else from backend/.env, found
by absolute path so it works from any working directory. Imported by tests/conftest.py BEFORE the dummies are set, so
SHELL_* hold what the shell really had.
"""
import os
import pathlib

ENV_FILE = pathlib.Path(__file__).resolve().parents[1] / "backend" / ".env"
DUMMY_KEY, DUMMY_MODEL = "test-key", "test-model"
SHELL_KEY, SHELL_MODEL = os.environ.get("OPENROUTER_API_KEY"), os.environ.get("MODEL")


def live_credentials():
    """(key, model) for tests marked `live`; None for anything missing."""
    from dotenv import dotenv_values
    file = dotenv_values(ENV_FILE) if ENV_FILE.exists() else {}
    key = SHELL_KEY if SHELL_KEY and SHELL_KEY != DUMMY_KEY else (file.get("OPENROUTER_API_KEY") or None)
    model = SHELL_MODEL if SHELL_MODEL and SHELL_MODEL != DUMMY_MODEL else (file.get("MODEL") or None)
    return key, model


def live_skip_reason(key, model):
    """Why RUN_LIVE=1 cannot run, or None: a clear skip instead of a 401 from the provider."""
    missing = [n for n, v in (("OPENROUTER_API_KEY", key), ("MODEL", model)) if not v]
    if not missing:
        return None
    return (f"RUN_LIVE=1 but {' and '.join(missing)} {'is' if len(missing) == 1 else 'are'} not set: put "
            f"{'them' if len(missing) > 1 else 'it'} in the environment or in {ENV_FILE}")
