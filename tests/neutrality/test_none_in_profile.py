"""A "none" answer from onboarding is left out of the PROFILE block: it is not a phrase of the reviewer's to reflect back."""
import pytest

from app import chatflow, nudges, onboarding as ob, store
from app.prompts import build_chat_system
from conftest import make_reviewer


def view_with(**said):
    """The profile view of a reviewer who answered `said` (field -> their answer); every other field is a default."""
    evs = []
    for f in ob.FIELDS:
        v = said.get(f)
        payload = ({"field": f, "value": v, "source": "answer", "raw": v} if v is not None
                   else {"field": f, "value": ob.DEFAULTS[f], "source": "default", "raw": ""})
        evs.append({"type": "profile_field_set", "ts": 0, "payload": payload})
    return ob.profile_view(store.fold_onboarding(evs))


def test_a_none_is_omitted_from_the_phrases_not_quoted_back():
    phrases = chatflow.profile_phrases(view_with(hardest_part="none", weakness_criteria="results without variance"))
    assert "hardest_part" not in phrases
    assert phrases["weakness_criteria"] == "results without variance"


@pytest.mark.parametrize("none_said", ["none", "None", " none "])
def test_the_prompt_never_quotes_a_none(none_said):
    phrases = chatflow.profile_phrases(view_with(hardest_part=none_said, strength_criteria="claims backed by experiments"))
    system = build_chat_system(phrases, None, "P", "D")
    assert "hardest about reviewing" not in system and '"none"' not in system.lower()
    assert '"claims backed by experiments"' in system


def test_a_real_hardest_part_is_still_quoted_back():
    phrases = chatflow.profile_phrases(view_with(hardest_part="deciding how much an ablation should count"))
    assert phrases["hardest_part"] == "deciding how much an ablation should count"
    assert '"deciding how much an ablation should count"' in build_chat_system(phrases, None, "P", "D")


def test_an_answer_that_only_contains_the_word_none_is_a_real_phrase():
    phrases = chatflow.profile_phrases(view_with(hardest_part="none of the criteria feel clear to me"))
    assert phrases["hardest_part"] == "none of the criteria feel clear to me"


def test_a_skipped_field_is_omitted_as_before():
    assert "hardest_part" not in chatflow.profile_phrases(view_with())


def test_through_the_chat_endpoint_the_prompt_leaves_it_out(chat_env):
    c, set_model = chat_env
    make_reviewer("rev", hardest_part="none", weakness_criteria="results reported without variance")
    model = set_model({"reply": "Table 2 has the numbers (Section 4)."})
    c.post("/chat/p1", json={"reviewer_id": "rev", "message": "which datasets do they use?"})
    assert "hardest about reviewing" not in model.system and '"none"' not in model.system.lower()
    assert '"results reported without variance"' in model.system


def test_a_none_hardest_part_does_not_pull_a_nudge_toward_any_section():
    rs = {"sections": [{"id": "summary", "name": "Paper summary", "required": True, "type": "text"},
                       {"id": "weaknesses", "name": "Summary of weaknesses", "required": True, "type": "text"}],
          "addressed": {}, "skipped": {}, "notes": [], "views": {}, "promised": [], "titles": []}
    phrases = chatflow.profile_phrases(view_with(hardest_part="none"))
    assert phrases.get("hardest_part") is None
    assert nudges.pick_nudge(rs, "abstract_first", phrases.get("hardest_part"), {})["section"] == "summary"
