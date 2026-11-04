"""Item 6: the neutrality checks must not over-block. Ordinary neutral messages, answered the way a helpful
colleague would answer them, must get through on the first try: the fallback fires on none of them.

Each pair is (reviewer message, a plausible reply from the model). The replies are deliberately written in
ordinary colleague language: restating the reviewer's own words (including their evaluative ones), quoting the
paper, using a technical term that happens to contain an evaluative word, offering a capture, a reword, a
nudge, a summary of a section.
"""
import pytest

from conftest import make_reviewer

PAIRS = [
    ("What datasets do they evaluate on?",
     {"reply": "They report accuracy on SST-2 and CoLA (Section 4, Table 2)."}),
    ("Can you explain what probing means here?",
     {"reply": "Probing trains a small classifier on frozen representations to see what information they encode. "
               "Their setup is described in Section 3."}),
    ("I think five participants per region seems low.",
     {"reply": "Noted: five participants per region. Want me to add that to the Weaknesses section of your draft?",
      "views": [{"text": "five participants per region seems low", "section": "weaknesses"}]}),
    ("Where do they state their contributions?",
     {"reply": "Section 1 lists two: a new probing dataset and a layer-wise analysis (lines 10-11)."}),
    ("What does F1 measure?",
     {"reply": "F1 is the harmonic mean of precision and recall. Table 2 in this paper reports accuracy rather than F1."}),
    ("The baseline looks weak to me.",
     {"reply": "You find the baseline weak. Table 2 lists the baselines they compare against; want to note that under "
               "Weaknesses with a pointer to the table?"}),
    ("I'm not sure how they split the data.",
     {"reply": "I can't find a sentence about the split in the text I have. Section 4 mentions the test set "
               "(line 80); the PDF may say more."}),
    ("ok",
     {"reply": "Alright. Your draft has nothing under Paper summary yet. Want to start there?", "nudge_used": True}),
    ("reword this: The writing is unclear in section 3, I think.",
     {"reply": "Here's a version: I think the writing is unclear in Section 3.",
      "reword": {"original": "The writing is unclear in section 3, I think.",
                 "text": "I think the writing is unclear in Section 3."}}),
    ("What is weak supervision?",
     {"reply": "Weak supervision means training with labels that are noisy or produced automatically. The authors "
               "use it in Section 3, with automatically parsed sentences."}),
    ("Why did they remove outliers?",
     {"reply": "The authors say the outliers distorted the loss (Section 3, lines 30-31)."}),
    ("Is there a table with the ablation?",
     {"reply": "I don't see an ablation table in the spans I have. Table 2 is the only table with results."}),
    ("Summarize section 3.",
     {"reply": "Section 3 describes training with weak supervision from automatically parsed sentences "
               "(lines 30-31)."}),
    ("Thanks, that helps.",
     {"reply": "You're welcome. Tell me when you want to look at something else."}),
    ("I'll cover ethics later.",
     {"reply": "Okay, I'll keep that in mind. Anything in the paper you want to look at first?"}),
    ("Where is the related work?",
     {"reply": "I don't have a related-work section in the text I was given; the introduction cites prior work "
               "instead (Section 1)."}),
    ("How many layers do they probe?",
     {"reply": "Section 3 says they probe all 12 layers (line 31)."}),
    ("My main worry is that the evaluation uses only English.",
     {"reply": "Noted: the evaluation uses only English. Want me to add that to your Weaknesses section?",
      "views": [{"text": "the evaluation uses only English", "section": "weaknesses"}]}),
    ("Can you find where they define accuracy?",
     {"reply": "They define it in Section 4 as \"correct predictions divided by total examples\"."}),
    ("I wonder if the key claim is supported by Table 2.",
     {"reply": "You mention the key claim. In the abstract the authors write that they \"report accuracy on three "
               "datasets\"; Table 2 shows two of them. Want to look at the third together?"}),
]


@pytest.mark.parametrize("message,reply", PAIRS, ids=[f"{i:02d}" for i in range(len(PAIRS))])
def test_ordinary_messages_never_hit_the_fallback(chat_env, message, reply):
    c, set_model = chat_env
    make_reviewer("rev")
    model = set_model(reply)
    body = c.post("/chat/p1", json={"reviewer_id": "rev", "message": message}).json()
    assert body["checks"] == {"attempts": 1, "fallback": False}, (message, body["reply"], len(model.calls))
    assert body["reply"].startswith(reply["reply"][:20])


def test_twenty_ordinary_messages_in_one_conversation_never_hit_the_fallback(chat_env):
    """The same twenty, one after another, as a real session would run them (history, notes and nudge state
    building up between turns)."""
    c, set_model = chat_env
    make_reviewer("rev")
    assert len(PAIRS) == 20
    fallbacks = 0
    for message, reply in PAIRS:
        set_model(reply)
        body = c.post("/chat/p1", json={"reviewer_id": "rev", "message": message}).json()
        fallbacks += body["checks"]["fallback"]
    assert fallbacks == 0
    from app import store
    stats = store.chat_check_stats("p1")
    assert stats["fallbacks"] == 0 and stats["replies"] >= 18   # replies that went through the model


# ------------------------------------------------------------------ the check itself, on a wider set of phrases

from app import chat_checks as cc  # noqa: E402

CTX = {"reviewer_text": "the baseline looks weak and the sample is small. i think this is a good idea. is this novel",
       "wants_decline": False, "summary_pref": "after_reading", "summary_requested": False}

ORDINARY = [
    "Makes sense.", "Sounds good.", "Fair enough.", "Good question.", "Thanks, got it.", "No problem.",
    "Sure, one moment.", "Let's look at Section 4 together.", "I can pull up the exact sentence.",
    "That term is defined in Section 3 (lines 30-31).", "The authors use a pretrained encoder, as stated in Section 3.",
    "Table 2 has two columns: SST-2 and CoLA.", "I can't find that in the text I have.",
    "There is a limitations paragraph in Section 5.", "The paper reports results on three datasets.",
    "Do you want the numbers or the setup first?", "Which part should we look at first?",
    "You said the sample is small; Section 4 gives the counts per region.",
    "You think it's a good idea; I can find where they motivate it.", "Right, the F1 is computed per class (Section 4).",
    "Weak labels are labels produced automatically.", "The model is fine-tuned for three epochs (Section 3).",
    "The proof is in the appendix (Appendix A).", "Let me know if you want me to add that to your draft.",
    "Is that okay?", "Does that work for you?", "Section 5 is short: two paragraphs.",
    'The authors say "we significantly outperform prior work" in the abstract.',
    "The difference is statistically significant according to the authors (Table 2).",
    "The evaluation is on English only, per Section 4.", "Only two datasets are listed in Table 1.",
    "I'm not able to say whether it is novel; that is your call. Section 2 states what they compare against.",
    "Whether it is novel is a judgment call that stays with you. Section 2 lists what they compare against.",
]


@pytest.mark.parametrize("phrase", ORDINARY)
def test_ordinary_colleague_phrasing_passes_the_checks(phrase):
    assert cc.reply_errors(phrase, CTX) == [], phrase


# What is still blocked, so that narrowing stays narrow.
STILL_BLOCKED = [
    "Yes, it is novel.",                                   # the reviewer's word, but the assistant is asserting it
    "I can say it is novel, and the baseline is weak.",
    "It's important to note that the abstract mentions three datasets.",
    "A strong baseline is usually a recent published model; here they use BERT.",
    "Their dataset is novel in the sense that it is new; see Section 2.",
    "The comparison is fair.",
]


@pytest.mark.parametrize("phrase", STILL_BLOCKED)
def test_assertions_and_filler_are_still_blocked(phrase):
    assert cc.reply_errors(phrase, CTX), phrase


def test_a_decline_may_name_what_the_reviewer_asked_about():
    ctx = {**CTX, "wants_decline": True}
    ok = "I can't say whether it's novel, since that's your call. Section 2 lists what they compare against."
    assert cc.reply_errors(ok, ctx) == []
    assert cc.reply_errors("It's novel, and that's your call to weigh.", ctx)       # asserts it before declining


# ------------------------------------------------------------------ the licence for the reviewer's own words

ATTRIBUTED = [
    "You find the baseline weak, and Table 2 is where the baselines are listed.",
    "You said the baseline looks weak; Table 2 lists the baselines.",
    "Your concern about the weak baseline is noted. Table 2 lists them.",
    "The baseline looks weak to you; Table 2 lists the ones they compare against.",
    "To you the baseline looks weak. Want to put that under Weaknesses?",
    "You called it a good idea; I can find where they motivate it.",
]
ENDORSED_OR_ASSERTED = [
    "As you said, the baseline is weak.",
    "It's novel, and that's your call to weigh.",
    "Since the baseline is weak, you might note it under Weaknesses.",
    "The baseline is weak, as Table 2 shows, and you can say so.",
]


@pytest.mark.parametrize("phrase", ATTRIBUTED)
def test_the_reviewers_word_reported_as_theirs_is_allowed(phrase):
    assert cc.reply_errors(phrase, CTX) == [], phrase


@pytest.mark.parametrize("phrase", ENDORSED_OR_ASSERTED)
def test_the_reviewers_word_asserted_or_endorsed_by_the_assistant_is_not(phrase):
    assert cc.reply_errors(phrase, CTX), phrase
