"""Every *_SYS prompt must include the shared NEUTRALITY block."""
import importlib
import pkgutil

import app
from app.prompts import NEUTRALITY

EXPECTED = 18  # CLAUDE.md: 16 prompts across 8 files, plus onboarding.TOPIC_SYS and prompts.CHAT_SYS


def all_sys_prompts():
    found = {}
    for m in pkgutil.iter_modules(app.__path__):
        mod = importlib.import_module(f"app.{m.name}")
        for name, val in vars(mod).items():
            if name.endswith("_SYS") and isinstance(val, str):
                found[f"{m.name}.{name}"] = val
    return found


def test_prompt_count_is_known():
    # A new *_SYS prompt must be added here deliberately, with the block.
    assert len(all_sys_prompts()) == EXPECTED


def test_every_prompt_includes_shared_neutrality_block():
    missing = [k for k, v in all_sys_prompts().items() if NEUTRALITY not in v]
    assert not missing, f"prompts without the shared NEUTRALITY block: {missing}"


def test_block_has_no_braces_so_templating_is_safe():
    assert "{" not in NEUTRALITY and "}" not in NEUTRALITY


def test_block_covers_claude_md_constraints():
    for phrase in ("quality, novelty, significance, soundness, or clarity",
                   "convincing or experiments adequate",
                   "accept/reject/score decision",
                   "reviewer's assessment of the paper is right or wrong",
                   "decline in one short sentence"):
        assert phrase in NEUTRALITY
