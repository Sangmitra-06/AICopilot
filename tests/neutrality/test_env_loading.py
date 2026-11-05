"""The model credentials load from backend/.env by absolute path, from any working directory; live tests get them
explicitly (or skip with a clear message); mocked tests never reach the model and never hold the real key."""
import os
import pathlib
import subprocess
import sys

import pytest

import live_env
from app import llm

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_llm_loads_backend_env_by_absolute_path():
    assert llm.ENV_FILE.is_absolute() and llm.ENV_FILE == ROOT / "backend" / ".env"
    assert live_env.ENV_FILE == llm.ENV_FILE


@pytest.mark.skipif(not (ROOT / "backend" / ".env").exists(), reason="no backend/.env on this machine")
def test_backend_env_loads_from_another_working_directory(tmp_path):
    """Run from an unrelated folder with no key in the environment: llm.py still finds backend/.env."""
    from dotenv import dotenv_values
    want = dotenv_values(ROOT / "backend" / ".env").get("MODEL")
    if not want:
        pytest.skip("backend/.env has no MODEL")
    env = {k: v for k, v in os.environ.items() if k not in ("OPENROUTER_API_KEY", "MODEL", "COPILOT_FRESH")}
    code = ("import sys; sys.path.insert(0, %r); from app import llm; import os; "
            "print(llm.MODEL); print(bool(os.environ.get('OPENROUTER_API_KEY')))" % str(ROOT / "backend"))
    out = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-500:]
    assert out.stdout.split() == [want, "True"]                          # the key itself is never printed


def test_variables_already_in_the_environment_win(tmp_path):
    """load_dotenv never overrides: the dummy credentials of the mocked tests stay dummy."""
    assert os.environ["MODEL"] == (live_env.SHELL_MODEL or live_env.DUMMY_MODEL)


def test_a_mocked_test_fails_loudly_on_a_real_model_call():
    with pytest.raises(AssertionError, match="test tried to call the model"):
        llm._chat([{"role": "user", "content": "hi"}])


def test_a_mocked_test_never_holds_the_real_key_from_backend_env():
    from dotenv import dotenv_values
    real = dotenv_values(llm.ENV_FILE).get("OPENROUTER_API_KEY") if llm.ENV_FILE.exists() else None
    if live_env.SHELL_KEY:
        pytest.skip("the shell exported a key itself")
    assert llm.client.api_key == live_env.DUMMY_KEY and llm.client.api_key != real


@pytest.mark.parametrize("key,model,missing", [
    (None, "m", ["OPENROUTER_API_KEY"]), ("k", None, ["MODEL"]), (None, None, ["OPENROUTER_API_KEY", "MODEL"]),
])
def test_run_live_without_credentials_skips_with_a_clear_message(key, model, missing):
    reason = live_env.live_skip_reason(key, model)
    assert reason.startswith("RUN_LIVE=1 but") and all(m in reason for m in missing)
    assert str(live_env.ENV_FILE) in reason
    assert live_env.live_skip_reason("k", "m") is None


def test_live_credentials_prefer_the_shell_then_backend_env(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("OPENROUTER_API_KEY=file-key\nMODEL=file-model\n", encoding="utf-8")
    monkeypatch.setattr(live_env, "ENV_FILE", env)
    monkeypatch.setattr(live_env, "SHELL_KEY", None)
    monkeypatch.setattr(live_env, "SHELL_MODEL", live_env.DUMMY_MODEL)          # a dummy counts as not set
    assert live_env.live_credentials() == ("file-key", "file-model")
    monkeypatch.setattr(live_env, "SHELL_KEY", "shell-key")
    assert live_env.live_credentials() == ("shell-key", "file-model")
    monkeypatch.setattr(live_env, "ENV_FILE", tmp_path / "missing.env")
    monkeypatch.setattr(live_env, "SHELL_KEY", None)
    assert live_env.live_credentials() == (None, None)


def test_run_live_with_no_key_anywhere_skips_instead_of_a_401(tmp_path):
    """The whole path: RUN_LIVE=1, no key in the shell, and an .env without one: the live tests are skipped with the
    message, never sent to the provider."""
    env = {k: v for k, v in os.environ.items() if k not in ("OPENROUTER_API_KEY", "MODEL", "COPILOT_FRESH")}
    env["RUN_LIVE"] = "1"
    probe = ("import live_env, pathlib; live_env.ENV_FILE = pathlib.Path(%r); live_env.SHELL_KEY = None; "
             "print(live_env.live_skip_reason(*live_env.live_credentials()))" % str(tmp_path / "none.env"))
    out = subprocess.run([sys.executable, "-c", probe], cwd=ROOT / "tests", env=env, capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, out.stderr[-500:]
    assert out.stdout.startswith("RUN_LIVE=1 but OPENROUTER_API_KEY")
