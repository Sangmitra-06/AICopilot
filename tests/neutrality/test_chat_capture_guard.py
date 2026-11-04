"""The assistant never claims a capture happened unless the backend recorded it, and when the reply carries no
structured fields an extraction call lets the app write the capture and confirm it in its own words."""
import json

import pytest

from app import capture, chat_checks as cc, store, synth
from conftest import make_reviewer
from test_nudges import SECTIONS

VIEW = "five participants per region seems low"
MESSAGE = f"I think {VIEW}"


# ------------------------------------------------------------------ what counts as a claim (the guard on its own)

CLAIMS = [
    "Added to Soundness, in your words.",
    "I've added that to your draft.",
    "I've saved it under Weaknesses.",
    "Noted in your draft.",
    "That's now in the Weaknesses section of your draft.",
    "It's in your draft now.",
    "Captured under Summary of weaknesses.",
    "I'll add that to your draft.",
    "I'm adding that to Soundness.",
    "That has been added to your review draft.",
    "Done, I've added that.",
    "I've recorded your point in your notes.",
    "Saved to your draft.",
    "Put under Strengths.",
    "I will save that under Weaknesses.",
    "Added it to the Comments section.",
    "No problem, added to your draft.",
    "Noted in your draft, no changes needed.",
]


@pytest.mark.parametrize("sentence", CLAIMS)
def test_a_claim_that_something_was_added_is_removed(sentence):
    text, removed = capture.scrub(f"You're saying the sample is small. {sentence} Table 2 has the counts.", SECTIONS)
    assert removed == [sentence]
    assert text == "You're saying the sample is small. Table 2 has the counts."


@pytest.mark.parametrize("sentence", CLAIMS)
def test_the_same_claims_are_fine_when_the_backend_recorded_a_capture(sentence):
    text, removed = capture.scrub(sentence, SECTIONS, claims_ok=True)
    assert text == sentence and removed == []


NOT_CLAIMS = [
    "Noted, you're saying five participants per region seems low.",
    "The authors added a second encoder in Section 3.",
    "They saved compute by using a smaller encoder.",
    "The dataset is kept in the supplementary material.",
    "The authors noted in the summary that results vary by seed.",       # a statement about the paper, not the draft
    "It's in Section 3.",
    "It's in the summary of the abstract.",
    "You said the baseline is weak.",
    "Your draft has nothing under Paper summary yet.",                   # a nudge
    "Section 4 reports the results; Soundness is not discussed there.",
    "I can pull up Section 4 if that helps.",
    "Table 2 was added to the paper after review.",
    "That's your call to make, not mine.",
    "Which section would you put that under?",
    "I haven't added anything to your draft.",                           # a negation is true, so it is not a claim
    "Nothing has been added to your draft yet.",
]


@pytest.mark.parametrize("sentence", NOT_CLAIMS)
def test_ordinary_sentences_are_left_exactly_as_written(sentence):
    text, removed = capture.scrub(sentence, SECTIONS)
    assert text == sentence and removed == []


OFFERS = [
    "Want me to add that to the Soundness section of your draft, in your own words?",
    "I can add that to your draft in your own words.",
    "Would you like me to note it under Weaknesses?",
    "Should I put that in your draft?",
    "If you'd like, I'll add that to your draft.",
]


@pytest.mark.parametrize("sentence", OFFERS)
def test_an_offer_with_nothing_behind_it_is_removed_and_kept_when_an_offer_stands(sentence):
    text, removed = capture.scrub(f"Table 2 has the counts. {sentence}", SECTIONS)
    assert (text, removed) == ("Table 2 has the counts.", [sentence])
    kept, none = capture.scrub(f"Table 2 has the counts. {sentence}", SECTIONS, offers_ok=True)
    assert kept == f"Table 2 has the counts. {sentence}" and none == []


@pytest.mark.parametrize("sentence", ["Want me to pull up Section 4?", "I can add more detail on the method if you like.",
                                      "Do you want the numbers or the setup first?"])
def test_offers_to_do_other_things_are_not_touched(sentence):
    assert capture.scrub(sentence, SECTIONS) == (sentence, [])


def test_paragraphs_survive_and_only_the_claim_goes():
    reply = "First paragraph here.\n\nAdded to Soundness. More after it.\n\nLast paragraph."
    text, removed = capture.scrub(reply, SECTIONS)
    assert removed == ["Added to Soundness."]
    assert text == "First paragraph here.\n\nMore after it.\n\nLast paragraph."


def test_a_reply_that_was_only_a_claim_gets_a_neutral_line():
    assert capture.scrub("Added to Soundness.", SECTIONS) == (capture.OK, ["Added to Soundness."])
    assert capture.scrub("Saved to your draft.", SECTIONS, empty_line=capture.NOT_ADDED)[0] == capture.NOT_ADDED


def test_the_neutral_lines_make_no_claim_and_pass_the_chat_checks():
    for line in (capture.OK, capture.NOT_ADDED):
        assert capture.scrub(line, SECTIONS) == (line, [])
        assert cc.reply_errors(line, {"reviewer_text": ""}) == []


# ------------------------------------------------------------------ through the endpoint

def post(c, message, rid="rev"):
    r = c.post("/chat/p1", json={"reviewer_id": rid, "message": message})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def env(chat_env):
    c, set_model = chat_env
    make_reviewer("rev")
    return c, set_model


def notes():
    return store.notes("p1")


PROSE_WITH_CLAIM = ("You're saying five participants per region seems low. Added to Soundness, in your words. "
                    "Table 2 has the per-region counts (Section 4).")


def test_a_prose_reply_claiming_a_capture_that_never_happened_loses_that_sentence(env):
    c, set_model = env
    set_model(PROSE_WITH_CLAIM, "NONE")                         # the extraction finds nothing to write
    body = post(c, MESSAGE)
    assert body["reply"] == "You're saying five participants per region seems low. Table 2 has the per-region counts (Section 4)."
    assert notes() == [] and body["captured"] == []


def test_the_same_when_the_reply_is_json_without_any_views(env):
    c, set_model = env
    set_model({"reply": PROSE_WITH_CLAIM}, "NONE")
    assert "Added" not in post(c, MESSAGE)["reply"] and notes() == []


def test_if_extraction_fails_nothing_about_capturing_is_said(env, monkeypatch):
    c, set_model = env
    from app import chatflow
    calls = []

    def fake(msgs):
        calls.append(msgs)
        if len(calls) == 1:
            return PROSE_WITH_CLAIM
        raise RuntimeError("model down")
    monkeypatch.setattr(chatflow, "_chat", fake)
    body = post(c, MESSAGE)
    assert len(calls) == 2 and notes() == []
    assert not any(w in body["reply"].lower() for w in ("added", "saved", "draft", "captured"))


def test_a_reply_that_was_only_a_false_claim_is_replaced_not_left_empty(env):
    c, set_model = env
    set_model("Added to Soundness, in your words.", "NONE")
    assert post(c, MESSAGE)["reply"] == capture.OK
    set_model("Added to Soundness, in your words.")
    assert post(c, "yes please add it")["reply"] == capture.NOT_ADDED        # asked to save; nothing was


def test_an_unbacked_offer_in_prose_is_removed_so_a_later_yes_is_not_a_dead_end(env):
    c, set_model = env
    set_model("Noted. Want me to add that to the Soundness section of your draft?", "NONE")
    body = post(c, MESSAGE)
    assert body["reply"] == "Noted." and store.chat_state("p1")["views"] == {}


def test_a_real_offer_stays_and_the_yes_then_makes_the_claim_true(env):
    c, set_model = env
    offer = "Noted. Want me to add that to the Weaknesses section of your draft?"
    set_model({"reply": offer, "views": [{"text": VIEW, "section": "weaknesses"}]},
              {"reply": "Added to Weaknesses."})
    assert post(c, MESSAGE)["reply"] == offer                          # backed by a registered offer
    body = post(c, "yes")
    assert body["reply"] == "Added to Weaknesses."                     # the capture was written this turn
    assert [n["text"] for n in notes()] == [VIEW]


def test_a_no_does_not_make_an_added_claim_true(env):
    c, set_model = env
    set_model({"reply": "Noted. Want me to add that to the Weaknesses section?", "views": [{"text": VIEW, "section": "weaknesses"}]},
              {"reply": "Okay. Added to Weaknesses anyway."})
    post(c, MESSAGE)
    body = post(c, "no")
    assert "Added" not in body["reply"] and notes() == []


def test_a_model_driven_accept_keeps_the_claim(env):
    c, set_model = env
    set_model({"reply": "Noted. Want me to add that to the Weaknesses section?", "views": [{"text": VIEW, "section": "weaknesses"}]},
              {"reply": "Done. Added to Strengths.", "offer_response": "accept", "offer_section": "strengths"})
    post(c, MESSAGE)
    body = post(c, "yes, but put it under strengths")
    assert body["reply"] == "Done. Added to Strengths." and notes()[0]["field"] == "strengths"


def test_sentences_about_the_paper_are_never_taken_for_claims(env):
    c, set_model = env
    reply = "The authors added a second encoder in Section 3. They noted in the summary that results vary by seed."
    set_model(reply)
    assert post(c, "what changed between the two versions of the model?")["reply"] == reply


# ------------------------------------------------------------------ part 2 of the same change: extraction

EXTRACT = f"VIEW | weaknesses | {VIEW}"


def sent_to_extraction(model):
    msgs = model.calls[1]
    return msgs[0]["content"], msgs[1]["content"]


def test_a_view_in_a_prose_reply_is_extracted_written_and_confirmed_by_the_app(env):
    c, set_model = env
    model = set_model(PROSE_WITH_CLAIM + " Want me to add that to your draft?", EXTRACT)
    body = post(c, MESSAGE)
    assert len(model.calls) == 2
    # the model's claim and offer are gone; the app says what it did, in its own words
    assert body["reply"] == ("You're saying five participants per region seems low. Table 2 has the per-region counts "
                             "(Section 4).\n\nAdded to Summary of weaknesses: “five participants per region seems low”.")
    [n] = notes()
    assert (n["text"], n["field"]) == (VIEW, "weaknesses")
    assert body["draft_changed"] is True and body["captured"][0]["text"] == VIEW and body["captured"][0]["label"] == "Summary of weaknesses"
    types = [e["type"] for e in store.events("p1")]
    assert types.count("note_added") == 1 and "view_stated" in types and "capture_resolved" in types
    assert store.chat_state("p1")["views"]["v1"]["outcome"] == "accepted"
    assert any(i["text"] == VIEW for i in synth.items("p1"))


def test_the_extraction_prompt_carries_neutrality_the_sections_and_only_the_reviewers_message(env):
    from app.prompts import NEUTRALITY, VIEW_SYS
    c, set_model = env
    model = set_model("You're saying the sample is small.", EXTRACT)
    post(c, MESSAGE)
    system, user = sent_to_extraction(model)
    assert system == VIEW_SYS and NEUTRALITY in VIEW_SYS
    assert "- weaknesses: Summary of weaknesses" in user and MESSAGE in user
    assert "The paper" not in user and "Table 2" not in user              # no paper text, no profile: a short call


@pytest.mark.parametrize("raw", [
    f"VIEW | weaknesses | {VIEW}",
    f"- VIEW | weaknesses | {VIEW}",
    f"view | Weaknesses | “{VIEW}”",
    json.dumps({"views": [{"text": VIEW, "section": "weaknesses"}]}),
    "```json\n" + json.dumps({"views": [{"text": VIEW, "section": "weaknesses"}]}) + "\n```",
    "Here you go:\n" + f"VIEW | weaknesses | {VIEW}" + "\nHope that helps.",
])
def test_the_extraction_is_read_tolerantly(env, raw):
    c, set_model = env
    set_model("Okay.", raw)
    body = post(c, MESSAGE)
    assert [n["text"] for n in notes()] == [VIEW] and body["captured"][0]["section"] == "weaknesses"


@pytest.mark.parametrize("raw", ["NONE", "none.", "", "Sure! The reviewer seems to be saying the sample is small.",
                                 "I could not find a view in this message.", "{not json", '{"views": []}'])
def test_unreadable_or_empty_extraction_writes_nothing_and_says_nothing(env, raw):
    c, set_model = env
    set_model("You're saying the sample is small.", raw)
    body = post(c, MESSAGE)
    assert notes() == [] and body["reply"] == "You're saying the sample is small." and body["captured"] == []


@pytest.mark.parametrize("invented", [
    "the sample is tiny", "five participants per region is too low", f"{VIEW} and the paper is not novel",
    "participants seem low per region five",
])
def test_words_the_reviewer_did_not_say_are_never_written(env, invented):
    c, set_model = env
    set_model("Okay.", f"VIEW | weaknesses | {invented}")
    body = post(c, MESSAGE)
    assert notes() == [] and body["captured"] == [] and "Added" not in body["reply"]


def test_what_is_written_is_always_a_span_of_the_reviewers_own_message(env):
    c, set_model = env
    message = "Honestly, I think five participants per region seems low, although the dataset itself is nice."
    set_model("Okay.", "VIEW | weaknesses | five participants per region seems low\nVIEW | strengths | the dataset itself is nice")
    post(c, message)
    texts = [n["text"] for n in notes()]
    assert texts == ["five participants per region seems low", "the dataset itself is nice"]
    assert all(t.lower() in message.lower() for t in texts)


def test_a_section_the_form_does_not_have_leaves_the_note_unplaced_and_says_so(env):
    c, set_model = env
    set_model("Okay.", f"VIEW | no_such_section | {VIEW}")
    body = post(c, MESSAGE)
    assert notes()[0]["field"] == ""
    assert body["reply"].endswith(f"Added to your draft, not placed in a section yet: “{VIEW}”.")


def test_a_section_named_by_its_label_is_understood(env):
    c, set_model = env
    set_model("Okay.", f"VIEW | Summary of strengths | {VIEW}")
    post(c, MESSAGE)
    assert notes()[0]["field"] == "strengths"


def test_at_most_three_views_per_message(env):
    c, set_model = env
    message = "The baseline looks weak. The writing is hard to follow. The dataset is nice. The ablation is missing."
    set_model("Okay.", "\n".join(f"VIEW | comments | {s}." for s in message.split(". ") if s) .replace("..", "."))
    post(c, message)
    assert len(notes()) == 3


def test_a_view_already_in_the_draft_is_not_written_twice(env):
    c, set_model = env
    store.log("p1", "note_added", {"id": 5, "field": "weaknesses", "text": VIEW, "span_ids": [], "page": None, "rect": None,
                                   "sentence": "", "revisit": False, "question": ""})
    set_model("Okay.", EXTRACT)
    body = post(c, MESSAGE)
    assert len(notes()) == 1 and body["captured"] == [] and "Added" not in body["reply"]


def test_saying_the_same_thing_twice_captures_it_once(env):
    c, set_model = env
    set_model("Okay.", EXTRACT, "Okay again.", EXTRACT)
    post(c, MESSAGE)
    body = post(c, MESSAGE)
    assert len(notes()) == 1 and body["captured"] == []


# the extraction is only for statements: no extra call for anything else
NOT_STATEMENTS = [
    "which datasets do they use?", "ok", "thanks", "is this novel?", "do you agree?", "what's missing?", "draft it",
    "reword this: The baseline is weak and the writing is sloppy, I think.", "why did they remove outliers",
    "sure thing", "Can you explain what probing means here",
]


@pytest.mark.parametrize("message", NOT_STATEMENTS)
def test_no_extraction_call_for_questions_requests_or_pauses(env, message):
    c, set_model = env
    model = set_model("Okay.", EXTRACT)
    post(c, message)
    extraction_calls = [m for m in model.calls if m[0]["content"].startswith("You pick out what a peer reviewer stated")]
    assert extraction_calls == [] and notes() == []


def test_no_extraction_when_the_reply_already_carries_structured_fields(env):
    c, set_model = env
    model = set_model({"reply": "Noted. Want me to add that to Weaknesses?", "views": [{"text": VIEW, "section": "weaknesses"}]}, EXTRACT)
    post(c, MESSAGE)
    assert len(model.calls) == 1 and notes() == []                         # an offer was made, nothing written yet


def test_no_extraction_after_a_fallback(env):
    c, set_model = env
    model = set_model("This paper is novel.", "This paper is novel.", EXTRACT)       # the checks reject both attempts
    body = post(c, MESSAGE)
    assert body["checks"]["fallback"] is True and len(model.calls) == 2 and notes() == []


def test_no_extraction_during_onboarding(chat_env):
    c, set_model = chat_env
    model = set_model(EXTRACT)
    c.post("/chat/p1", json={"reviewer_id": "newbie", "message": MESSAGE})
    assert model.calls == []


# ------------------------------------------------------------------ the written note is an ordinary note

def test_an_app_written_capture_can_be_edited_and_removed_like_any_other_note(env):
    c, set_model = env
    set_model("Okay.", EXTRACT)
    post(c, MESSAGE)
    nid = notes()[0]["id"]
    ev = lambda t, p: c.post("/events", json={"paper_id": "p1", "type": t, "payload": p}).status_code
    assert ev("note_text_edited", {"id": nid, "text": "five participants per region"}) == 200
    assert [n["text"] for n in c.get("/notes/p1").json()] == ["five participants per region"]
    assert ev("note_removed", {"id": nid}) == 200
    assert c.get("/notes/p1").json() == []


def test_the_capture_shows_in_the_next_prompt_and_in_gap_reports(env):
    c, set_model = env
    model = set_model("Okay.", EXTRACT)
    post(c, MESSAGE)
    post(c, "which datasets do they use?")
    assert VIEW in model.calls[-1][0]["content"].split("THE REVIEW DRAFT SO FAR")[1]
    assert post(c, "what's missing?")["gaps"]["uncaptured"] == []


def test_the_apps_confirmation_is_neutral_and_passes_the_chat_checks():
    text = capture.confirmation([{"text": "the baseline is weak", "label": "Summary of weaknesses"}])
    assert text == "Added to Summary of weaknesses: “the baseline is weak”."
    assert cc.reply_errors(text, {"reviewer_text": "the baseline is weak"}) == []        # quoted words are the reviewer's
