"""Group (b): factual, conceptual, locating, and rewording requests must be answered
(not declined), even when they contain words like reject, valid, fair or accept."""
import pytest

from app import llm, synth
from conftest import SPAN, background, sentence

Q = "We removed outliers before training"
F1 = "We report F1 on the held-out test set"
CONTRIB = "Our contributions are a new dataset and a probing method"

ANSWERABLE = [
    ("why did they reject outliers?", [sentence("The authors say they removed outliers because they distorted the loss.",
                                                 "removed outliers before training because they distorted the loss", kind="authors_claim")]),
    ("what does valid mean?", [background("Valid here is a term for a sample that passes the dataset's checks.")]),
    ("what does 'valid' mean in this paper?", [background("The paper does not define valid in this span.")]),
    ("what is F1?", [background("F1 is the harmonic mean of precision and recall.")]),
    ("explain the F1 metric", [sentence("The paper reports F1 on the held-out test set.", F1)]),
    ("where do the authors state their contribution?", [sentence("The authors list their contributions in the introduction.", CONTRIB, kind="authors_claim")]),
    ("which datasets did they accept into the test split?", [sentence("The paper reports a held-out test set.", F1)]),
    ("how do they define a valid sample?", [sentence("The paper describes removing outliers before training.", Q)]),
    ("what is the strong baseline they compare against?", [sentence("The paper reports F1 on the held-out test set.", F1)]),
    ("is the difference statistically significant?", [sentence("The paper reports F1 on the held-out test set.", F1)]),
    ("should I look at the appendix for the F1 numbers?", [sentence("The paper reports F1 on the held-out test set.", F1)]),
    ("what did they do about unfair label noise?", [sentence("The authors removed outliers before training.", Q)]),
]


@pytest.mark.parametrize("q,sents", ANSWERABLE, ids=[a[0] for a in ANSWERABLE])
def test_factual_and_conceptual_questions_are_answered(q, sents, model_says):
    calls = model_says({"sentences": sents})
    out = llm.ask(q, [SPAN])
    assert not out.get("declined"), f"over-refused: {q}"
    assert out["sentences"], q
    assert calls, "the model should have been asked"


# Reword a harsh comment: the draft path keeps the reviewer's own wording, including
# harsh words they chose, and does not block them as the assistant's opinion.
HARSH = {"n1": "The baseline is weak and the writing is flawed, honestly sloppy."}


def draft(monkeypatch, sentences):
    import json
    answers = iter([json.dumps({"sentences": sentences}), json.dumps({"results": []})])
    monkeypatch.setattr(synth, "_chat", lambda msgs: next(answers, json.dumps({"results": []})))
    its = [{"key": k, "text": t} for k, t in HARSH.items()]
    return synth.draft_field("weaknesses", its, "smooth")


def test_rewording_keeps_the_reviewers_own_harsh_words(monkeypatch):
    monkeypatch.setattr(synth, "names", lambda: {"weaknesses": "Weaknesses"})
    out = draft(monkeypatch, [{"text": "I find the baseline weak and the writing flawed, honestly sloppy.", "src": ["n1"]}])
    assert out["fallback"] is False, "reviewer's own harsh wording was rejected"


def test_rewording_may_not_add_the_assistants_own_harsh_word(monkeypatch):
    monkeypatch.setattr(synth, "names", lambda: {"weaknesses": "Weaknesses"})
    out = draft(monkeypatch, [{"text": "The baseline is weak and the paper is not convincing.", "src": ["n1"]}])
    assert out["fallback"] is True  # rejected; the reviewer's own note is used instead
    assert out["sentences"][0]["text"] == HARSH["n1"]
