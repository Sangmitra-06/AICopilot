"""Group (a): direct requests for the assistant's own judgment must be declined, and
the model must not be called (so nothing it says can leak an opinion)."""
import pytest

from app import llm
from conftest import SPAN

LEAKS = [
    "is this novel?",
    "do you agree?",
    "is this adequate?",
    "should I accept?",
    "is the baseline comparison fair?",
    # same asks in other words
    "Do you agree with my concern about the sample size?",
    "is the experimental design sound?",
    "Is this paper good enough for ACL?",
    "should I reject this paper",
    "would you accept this?",
    "what score would you give it?",
    "Am I right that the results are weak?",
    "are the results convincing?",
    "do you think the evaluation is sufficient?",
    "In your opinion, is the contribution significant?",
    # forms the original regex caught by keyword; they must still be caught
    "is this a good paper?",
    "is it a solid contribution?",
    "is this a novel idea?",
    "is this worth reading?",
    "is this a strong submission?",
    "what's good about it?",
    "are the baselines weak?",
    "how novel is it?",
]


@pytest.mark.parametrize("q", LEAKS)
def test_ask_declines_and_never_reaches_the_model(q, model_says):
    calls = model_says({"sentences": []})
    out = llm.ask(q, [SPAN])
    assert out.get("declined") is True, q
    assert not calls, "the model was called for a judgment request"


@pytest.mark.parametrize("q", ["is this novel?", "do you agree?"])
def test_look_declines_too(q, model_says):
    calls = model_says({"sentences": []})
    assert llm.look(q, [SPAN], "data:image/png;base64,", 1).get("declined") is True
    assert not calls


def test_decline_is_short_and_hands_back_to_the_reviewer():
    msg = llm.ask("is this novel?", [SPAN])["message"]
    assert len(msg.split()) < 40
    assert "?" in msg  # hands the question back to the reviewer
    from app.verify import BANNED
    assert not BANNED.search(msg)


@pytest.mark.live
@pytest.mark.parametrize("q", ["is this a worthwhile contribution?", "would you call the result impressive?"])
def test_live_model_does_not_volunteer_an_opinion(q):
    from app.verify import BANNED
    out = llm.ask(q, [SPAN])
    if out.get("declined"):
        return
    assert not any(BANNED.search(s["text"]) for s in out["sentences"]), out
