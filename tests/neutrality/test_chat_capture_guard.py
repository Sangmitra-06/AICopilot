"""The assistant never claims a capture happened unless the backend recorded it, and when the reply carries no
structured fields an extraction call lets the app write the capture and confirm it in its own words.
Save-then-tell: a stated view is saved at once and the app's "Saved under X. Say 'move it' if that's wrong." is the only
line about it (these tests drove offer-then-yes before; what they guard is the same)."""
import json

import pytest

from app import capture, chat_checks as cc, store, synth
from conftest import make_reviewer
from test_nudges import SECTIONS

n2 = chr(10) * 2
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
    assert notes() == [] and body["capture"] is None


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


def test_a_real_save_is_told_in_the_apps_words_and_the_note_exists(env):
    c, set_model = env
    model_line = "Noted. Want me to add that to the Weaknesses section of your draft? Added to Weaknesses."
    set_model({"reply": model_line, "views": [{"text": VIEW, "section": "weaknesses"}]})
    assert post(c, MESSAGE)["reply"] == "Noted." + n2 + SAVED_LINE        # the app's wording, once
    assert [(n["text"], n["field"]) for n in notes()] == [(VIEW, "weaknesses")]


def test_a_later_model_claim_is_still_removed(env):
    c, set_model = env
    set_model({"reply": "Noted.", "views": [{"text": VIEW, "section": "weaknesses"}]},
              {"reply": "Okay. Added to Strengths anyway."})
    post(c, MESSAGE)
    body = post(c, "no")
    assert "Added" not in body["reply"] and [n["field"] for n in notes()] == ["weaknesses"]


def test_a_model_written_section_change_is_never_believed_only_the_apps_move_is(env):
    c, set_model = env
    set_model({"reply": "Noted.", "views": [{"text": VIEW, "section": "weaknesses"}]},
              {"reply": "Done. Added to Strengths.", "offer_response": "accept", "offer_section": "strengths"})
    post(c, MESSAGE)
    body = post(c, "yes, but put it under strengths")                       # the app moves it, with no model call
    assert body["reply"] == "Moved to Summary of strengths."
    assert notes()[0]["field"] == "strengths"


def test_sentences_about_the_paper_are_never_taken_for_claims(env):
    c, set_model = env
    reply = "The authors added a second encoder in Section 3. They noted in the summary that results vary by seed."
    set_model(reply)
    assert post(c, "what changed between the two versions of the model?")["reply"] == reply


# ------------------------------------------------------------------ prose replies: extraction, then save, then tell
# A view found in a prose reply is SAVED at once, exactly as for a JSON reply, and the app says where it went.

EXTRACT = f"VIEW | weaknesses | {VIEW}"
SAVED_LINE = "Saved under Summary of weaknesses. Say “move it” if that's wrong."


def sent_to_extraction(model):
    msgs = model.calls[1]
    return msgs[0]["content"], msgs[1]["content"]


def events_of(*kinds):
    return [e["type"] for e in store.events("p1") if e["type"] in kinds]


def test_a_view_in_a_prose_reply_is_saved_and_told_in_the_apps_words(env):
    c, set_model = env
    model = set_model(PROSE_WITH_CLAIM + " Want me to add that to your draft?", EXTRACT)
    body = post(c, MESSAGE)
    assert len(model.calls) == 2
    # the model's claim and its own offer are gone; the app says where it went, in its own words
    assert body["reply"] == ("You're saying five participants per region seems low. Table 2 has the per-region counts "
                             f"(Section 4).\n\n{SAVED_LINE}")
    assert [(n["text"], n["field"]) for n in notes()] == [(VIEW, "weaknesses")]
    assert body["draft_changed"] is True and body["capture"] is None
    assert body["added"]["section"] == "weaknesses" and body["added"]["note_id"] == notes()[0]["id"]
    assert events_of("view_stated", "capture_offered") == ["view_stated"]
    assert store.chat_state("p1")["views"]["v1"]["outcome"] == "accepted"


def test_the_saved_note_is_in_the_draft_items_exactly_as_for_a_json_reply(env):
    c, set_model = env
    set_model("You're saying the sample is small.", EXTRACT)
    post(c, MESSAGE)
    [n] = notes()
    assert (n["text"], n["field"]) == (VIEW, "weaknesses")
    assert any(i["text"] == VIEW for i in synth.items("p1"))


def test_dont_add_that_takes_it_out_and_a_later_claim_is_still_removed(env):
    c, set_model = env
    set_model("You're saying the sample is small.", EXTRACT, "Okay. Added to Summary of weaknesses anyway.")
    post(c, MESSAGE)
    assert post(c, "don't add that")["reply"] == "Undone: I removed it from Summary of weaknesses."
    body = post(c, "ok, what else?")
    assert notes() == [] and "Added" not in body["reply"]


def test_a_worded_correction_moves_the_section(env):
    c, set_model = env
    set_model("You're saying the sample is small.", EXTRACT)
    post(c, MESSAGE)
    post(c, "yes, but put it under strengths")
    assert notes()[0]["field"] == "strengths"


def test_a_correction_lasts_one_turn_like_any_other(env):
    c, set_model = env
    set_model("You're saying the sample is small.", EXTRACT, "Table 2 has the counts.", "Sure.")
    post(c, MESSAGE)
    post(c, "where are the counts?")                                              # moved on
    post(c, "No, I mean strengths")
    assert [n["field"] for n in notes()] == ["weaknesses"]


def test_a_saved_view_is_not_reported_as_uncaptured(env):
    c, set_model = env
    set_model("You're saying the sample is small.", EXTRACT, "Table 2 has the counts.")
    post(c, MESSAGE)
    post(c, "where are the counts?")
    assert post(c, "what's missing?")["gaps"]["uncaptured"] == []


def test_the_extraction_prompt_carries_neutrality_the_sections_and_only_the_reviewers_message(env):
    from app.prompts import NEUTRALITY, VIEW_SYS
    c, set_model = env
    model = set_model("You're saying the sample is small.", EXTRACT)
    post(c, MESSAGE)
    system, user = sent_to_extraction(model)
    assert system == VIEW_SYS and NEUTRALITY in VIEW_SYS
    assert "- weaknesses: Summary of weaknesses" in user and MESSAGE in user
    assert "The paper" not in user and "Table 2" not in user                    # no paper text, no profile: a short call


@pytest.mark.parametrize("raw", [
    f"VIEW | weaknesses | {VIEW}",
    f"- VIEW | weaknesses | {VIEW}",
    f"view | Weaknesses | “{VIEW}”",
    json.dumps({"views": [{"text": VIEW, "section": "weaknesses"}]}),
    "```json\n" + json.dumps({"views": [{"text": VIEW, "section": "weaknesses"}]}) + "\n```",
    "Here you go:\n" + f"VIEW | weaknesses | {VIEW}" + "\nHope that helps.",
])
def test_the_extraction_is_read_tolerantly_and_leads_to_a_save(env, raw):
    c, set_model = env
    set_model("Okay.", raw)
    body = post(c, MESSAGE)
    assert body["reply"].endswith(SAVED_LINE) and [n["text"] for n in notes()] == [VIEW]


@pytest.mark.parametrize("raw", ["NONE", "none.", "", "Sure! The reviewer seems to be saying the sample is small.",
                                 "I could not find a view in this message.", "{not json", '{"views": []}'])
def test_unreadable_or_empty_extraction_offers_nothing_and_says_nothing(env, raw):
    c, set_model = env
    set_model("You're saying the sample is small.", raw)
    body = post(c, MESSAGE)
    assert body["reply"] == "You're saying the sample is small." and body["capture"] is None
    assert events_of("view_stated", "capture_offered") == [] and notes() == []


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
    assert len(calls) == 2 and notes() == [] and body["capture"] is None
    assert not any(w in body["reply"].lower() for w in ("added", "saved", "draft", "captured", "want me"))


@pytest.mark.parametrize("invented", [
    "the sample is tiny", "five participants per region is too low", f"{VIEW} and the paper is not novel",
    "participants seem low per region five",
])
def test_words_the_reviewer_did_not_say_are_never_offered(env, invented):
    c, set_model = env
    set_model("Okay.", f"VIEW | weaknesses | {invented}")
    body = post(c, MESSAGE)
    assert body["capture"] is None and events_of("capture_offered") == [] and "Want me" not in body["reply"]


def test_what_is_written_is_a_span_of_the_reviewers_own_message(env):
    c, set_model = env
    message = "Honestly, I think five participants per region seems low, although the dataset itself is nice."
    set_model("Okay.", "VIEW | weaknesses | five participants per region seems low\nVIEW | strengths | the dataset itself is nice")
    body = post(c, message)
    assert sorted((n["field"], n["text"]) for n in notes()) == [
        ("strengths", "the dataset itself is nice"), ("weaknesses", "five participants per region seems low")]
    assert body["reply"].endswith("Saved under Summary of weaknesses and Summary of strengths. Say “move it” if that's wrong.")
    assert all(n["text"].lower() in message.lower() for n in notes())


def test_a_section_the_form_does_not_have_is_told_as_the_draft_and_lands_unplaced(env):
    c, set_model = env
    set_model("Okay.", f"VIEW | no_such_section | {VIEW}")
    body = post(c, MESSAGE)
    assert body["reply"].endswith("Saved under your draft. Say “move it” if that's wrong.")
    assert notes()[0]["field"] == ""


def test_a_section_named_by_its_label_is_understood(env):
    c, set_model = env
    set_model("Okay.", f"VIEW | Summary of strengths | {VIEW}")
    body = post(c, MESSAGE)
    assert body["reply"].endswith("Saved under Summary of strengths. Say “move it” if that's wrong.")
    assert notes()[0]["field"] == "strengths"


def test_at_most_three_views_are_saved_from_one_message(env):
    c, set_model = env
    message = "The baseline looks weak. The writing is hard to follow. The dataset is nice. The ablation is missing."
    lines = "\n".join(f"VIEW | comments | {s}" for s in
                      ["The baseline looks weak", "The writing is hard to follow", "The dataset is nice", "The ablation is missing"])
    set_model("Okay.", lines)
    body = post(c, message)
    assert len(store.chat_state("p1")["views"]) == 3 and len(notes()) == 3
    assert body["reply"].count("Saved under") == 1                         # one line for all of them


def test_a_view_already_in_the_draft_is_not_offered(env):
    c, set_model = env
    store.log("p1", "note_added", {"id": 5, "field": "weaknesses", "text": VIEW, "span_ids": [], "page": None, "rect": None,
                                   "sentence": "", "revisit": False, "question": ""})
    set_model("Okay.", EXTRACT)
    body = post(c, MESSAGE)
    assert len(notes()) == 1 and body["capture"] is None and "Want me" not in body["reply"]


def test_saying_the_same_thing_twice_is_saved_once(env):
    c, set_model = env
    set_model("Okay.", EXTRACT, "Okay again.", EXTRACT)
    post(c, MESSAGE)
    body = post(c, MESSAGE)
    assert len(notes()) == 1 and "Saved under" not in body["reply"]


def test_a_save_does_not_count_as_a_nudge_and_a_nudge_does_not_hide_it(env):
    c, set_model = env
    set_model("Your draft has nothing under Summary of weaknesses yet.", EXTRACT)
    body = post(c, MESSAGE)
    assert body["reply"].endswith(SAVED_LINE) and body["nudge"] is None


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
    model = set_model({"reply": "Noted.", "views": [{"text": VIEW, "section": "weaknesses"}]}, EXTRACT)
    post(c, MESSAGE)
    assert len(model.calls) == 1 and [n["text"] for n in notes()] == [VIEW]     # the model's views are saved; one call


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

def test_a_saved_note_can_be_edited_and_removed_like_any_other(env):
    c, set_model = env
    set_model("Okay.", EXTRACT)
    post(c, MESSAGE)
    nid = notes()[0]["id"]
    ev = lambda t, p: c.post("/events", json={"paper_id": "p1", "type": t, "payload": p}).status_code
    assert ev("note_text_edited", {"id": nid, "text": "five participants per region"}) == 200
    assert [n["text"] for n in c.get("/notes/p1").json()] == ["five participants per region"]
    assert ev("note_removed", {"id": nid}) == 200
    assert c.get("/notes/p1").json() == []


def test_the_saved_note_shows_in_the_next_prompt(env):
    c, set_model = env
    model = set_model("Okay.", EXTRACT, "Table 2 has it.")
    post(c, MESSAGE)
    post(c, "which datasets do they use?")
    assert VIEW in model.calls[-1][0]["content"].split("THE REVIEW DRAFT SO FAR")[1]
    assert post(c, "what's missing?")["gaps"]["uncaptured"] == []


def test_a_conflict_with_the_paper_is_noted_with_the_save_and_blocks_nothing(env, monkeypatch):
    from app import pointers
    c, set_model = env
    conflict = "Table 2 reports accuracy of 80 on SST-2"
    monkeypatch.setattr(pointers, "_chat", lambda msgs: json.dumps({"pointers": [{
        "kind": "contradicts", "reviewer_phrase": "accuracy of 80 on SST-2", "span_id": "s4",
        "paper_quote": "accuracy of 71.2 on SST-2", "explanation": "The paper gives 71.2."}]}))
    set_model("Okay.", f"VIEW | comments | {conflict}")
    body = post(c, conflict)
    assert len(body["conflicts"]) == 1 and [n["text"] for n in notes()] == [conflict]
    assert "Saved under Comments, suggestions and typos." in body["reply"]
    assert body["reply"].endswith("Want to check?")


def test_the_apps_offer_line_is_plain_and_asks_once():
    assert capture.offer_line("Summary of weaknesses") == "Want me to add that to Summary of weaknesses?"
    assert capture.offer_line("") == "Want me to add that to your draft?"
    assert capture.offer_line("Soundness", "the baseline is weak") == "Want me to add “the baseline is weak” to Soundness?"
    assert cc.reply_errors(capture.offer_line("Soundness", "the baseline is weak"), {"reviewer_text": "the baseline is weak"}) == []
