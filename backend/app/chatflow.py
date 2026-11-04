"""Chat-first turn handling: one endpoint, one prompt, free-form replies.

POST /chat/{pid} lands in turn(). Until onboarding has closed, the message is routed to the onboarding rules
(onboarding.py). After that it is a free conversation: the prompt is built from the shared NEUTRALITY block,
the reviewer's PROFILE, the paper, the review draft and the last 20 turns, in full (prompts.py).

Everything that changes the review is deterministic code over the event log, not model output:
  - capture: the model reports the reviewer's views as verbatim spans of their message; an accepted offer
    becomes an ordinary note_added event, so editing and removing it use the existing /events endpoint;
  - gap reports and drafts are built by the server from the review state;
  - paper-conflict notes come from pointers.check and a fixed, neutral template.
"""
import json
import logging
import re
import time

from . import store, onboarding, synth, criteria, chat, chat_checks, coverage, nudges, pointers, capture, cites
from .llm import _chat
from .prompts import build_chat_system, build_chat_messages
from . import prompts
from .verify import norm

log = logging.getLogger("copilot.chat")

HISTORY_TURNS = 20
PAPER_CHAR_CAP = 240_000  # about 60k tokens; References are always left out first
FALLBACK = chat_checks.FALLBACK

APOS = r"['’]?"
GAP_REQ = re.compile(
    r"\b(?:what" + APOS + r"s missing|what is missing|what am i missing|what did i (?:miss|forget|leave out)|any gaps|"
    r"gap report|what" + APOS + r"s (?:left|still open|open)|what haven" + APOS + r"t i (?:covered|done|addressed|written)|"
    r"am i missing anything|anything (?:i" + APOS + r"?m )?missing|what else (?:is|do i) (?:left|need))\b", re.I)
DRAFT_REQ = re.compile(
    r"\b(?:draft (?:it|this|that|my review|the review)|write (?:it|the review|my review) up|put (?:it|this) all "
    r"together|assemble (?:it|the review|my review)|generate (?:my |the )?(?:review|draft))\b", re.I)
OFFER_WORDS = re.compile(r"\b(?:add|put|capture|save|include|note|place|file|record|keep)\b", re.I)
OFFER_WHERE = re.compile(r"\b(?:draft|review|section|under|to your|in your)\b", re.I)
FACT_CUE = re.compile(r"\d|\b(?:paper|authors?|they|their|section|table|figure|dataset|baseline|model|report\w*|"
                      r"use[sd]?|train\w*|evaluat\w*|compar\w*|only|all|never|always)\b", re.I)


# ------------------------------------------------------------------ what goes into the prompt

def paper_text(spans, cap=PAPER_CHAR_CAP):
    """The paper as labeled spans grouped by section. References and stray page text are left out."""
    out, size, cur = [], 0, None
    for s in spans:
        if s.get("section") == "References":
            break
        if s.get("kind") in ("loose", "added"):
            continue
        if s["section"] != cur:
            cur = s["section"]
            out.append(f"\n## {cur}")
        where = f" (lines {s['lines'][0]}-{s['lines'][1]})" if s.get("lines") else ""
        line = f"[{s['id']}]{where} {s['text']}"
        size += len(line)
        if size > cap:
            out.append("[The paper text was cut here to fit; later sections are not shown.]")
            log.warning("paper text truncated at %d characters (section %r)", cap, cur)
            break
        out.append(line)
    return "\n".join(out).strip()


def draft_text(pid):
    """The review as the reviewer has it now: their notes by form section, plus any generated draft text."""
    names, its = synth.names(), synth.items(pid)
    blocks = []
    for fid, label in names.items():
        mine = [i["text"] for i in sorted(its, key=lambda i: i["order"]) if i["field"] == fid]
        blocks.append(f"## {label}\n" + ("\n".join(f"- {t}" for t in mine) if mine else "(nothing yet)"))
    loose = [i["text"] for i in its if not i["field"]]
    if loose:
        blocks.append("## Not yet placed in a section\n" + "\n".join(f"- {t}" for t in loose))
    gen = store.draft(pid)
    if gen:
        blocks.append("## Generated draft text\n" + "\n".join(
            f"{names.get(f, f)}: " + " ".join(s["text"] for s in d["sentences"]) for f, d in gen.items()))
    return "\n\n".join(blocks)


def history_turns(pid, n=HISTORY_TURNS):
    """The last n chat turns, complete (no truncation)."""
    turns = [t for t in store.thread(pid, limit=10_000) if t.get("kind") == "chat"]
    return turns[-n:]


def profile_phrases(view):
    """The reviewer's own words for each profile line, taken from what they actually said. Structured fields
    show the sentence they said it in (their words), never the label we map it to."""
    out = {}
    for field in ("strength_criteria", "weakness_criteria", "hardest_part", "reading_order", "note_habit",
                  "summary_preference"):
        e = (view["fields"] or {}).get(field)
        if not e or e.get("source") not in ("answer", "extracted"):
            continue
        if field not in onboarding.EXTRACT and str(e.get("value") or "").strip().lower() == onboarding.NONE_VALUE:
            continue  # an explicit "none" is not a phrase of theirs to reflect back
        raw = (e.get("raw") or "").strip()
        if field in onboarding.EXTRACT and e.get("source") == "extracted":
            raw = next((s.strip() for s in re.split(r"(?<=[.!?])\s+", raw)
                        if onboarding.EXTRACT[field](s, False) == e["value"]), raw)
        text = raw if field in onboarding.EXTRACT else (e.get("value") or raw)
        if text:
            out[field] = " ".join(text.split())[:300]
    return out


def summary_preference(view):
    e = (view["fields"] or {}).get("summary_preference")
    return e.get("value") if e else None


# ------------------------------------------------------------------ the review as it stands

def review_state(pid, spans):
    """The review's state for gap detection (see coverage.py). Reads the event log; judges nothing."""
    cov = synth.coverage(pid)
    cited = {f"n{n['id']}": n.get("span_ids") or [] for n in store.notes(pid)}
    cited.update({f"f{f['id']}": f.get("span_ids") or [] for f in store.state(pid)})
    titles = sorted({s["section"] for s in spans
                     if s.get("section") and s["section"] not in ("References", "Front matter", "Added from PDF")})
    st = store.chat_state(pid)
    return {
        "sections": [{"id": c["id"], "name": c["name"], "required": c["required"], "type": c["type"]}
                     for c in criteria.items()],
        "addressed": {cid: v["addressed"] for cid, v in cov.items()},
        "skipped": {cid: v["skipped"] for cid, v in cov.items()},
        "notes": [{"key": i["key"], "field": i["field"], "text": i["text"],
                   "cited": coverage.cites(i["text"], cited.get(i["key"], ()), titles)}
                  for i in synth.items(pid) if i["kind"] != "score"],
        "views": st["views"], "promised": st["promised"], "titles": titles}


def gap_reply(pid, spans, variant):
    report = coverage.gap_report(review_state(pid, spans))
    return coverage.gap_text(report, variant), report


def draft_reply(pid, spans, variant=0):
    """Draft every section that has content. Missing parts never block it (the gate in synth.make_draft is the
    old flow's and is left alone); empty sections are simply reported."""
    names = synth.names()
    try:
        synth.sort_items(pid)  # place any unsorted notes; if that fails, draft what is already placed
    except Exception as e:
        log.warning("sorting notes before drafting failed: %r", e)
    its = sorted(synth.items(pid), key=lambda i: i["order"])
    drafted, empty = [], []
    for fid, label in names.items():
        sel = [i for i in its if i["field"] == fid]
        if not sel:
            empty.append(label)
            continue
        res = synth.draft_field(fid, sel, "smooth")
        store.log(pid, "draft_generated", {"field": fid, "mode": "smooth", "fallback": res["fallback"],
                                           "sentences": res["sentences"]})
        drafted.append(label)
    unplaced = [i for i in its if not i["field"]]
    if not drafted:
        return ("There's nothing in your review yet to draft from. Tell me what you think about the paper and "
                "I'll add it to your draft as we go."), {"drafted": [], "empty": empty}
    lead = ["Drafted: ", "I've drafted: ", "The draft now has: "][variant % 3]
    text = lead + ", ".join(drafted) + ". Open the review draft to read, edit or copy it."
    if empty:
        text += " Nothing to draft yet for " + ", ".join(empty) + ", so I left those empty."
    if unplaced:
        text += f" {len(unplaced)} of your notes aren't in a section yet, so they aren't in the draft."
    return text, {"drafted": drafted, "empty": empty}


# ------------------------------------------------------------------ captures

def section_id(raw, names):
    """A review-form section id from what the model (or reviewer) called it, or "" if it is not one."""
    raw = (raw or "").strip()
    if raw in names:
        return raw
    return chat.lookup().get(raw.lower(), "") if raw else ""


def accept_capture(pid, vid, view, section=None):
    """Put a stated view in the draft: an ordinary note_added event, in the reviewer's own words."""
    field = section if section is not None else view["section"]
    nid = max([int(time.time() * 1000)] + [n["id"] + 1 for n in store.notes(pid) if isinstance(n["id"], int)])
    store.log(pid, "note_added", {"id": nid, "field": field, "text": view["text"], "span_ids": [], "page": None,
                                  "rect": None, "sentence": "", "revisit": False, "question": "",
                                  "by": "chat", "view": vid})
    store.log(pid, "capture_resolved", {"vid": vid, "outcome": "accepted", "note_id": nid})
    return nid


def reject_capture(pid, vid):
    store.log(pid, "capture_resolved", {"vid": vid, "outcome": "rejected"})


def open_offer(st):
    """The capture offered in the assistant's last turn, if the reviewer has not answered it yet."""
    last = st["last_assistant"] or {}
    vid = (last.get("meta") or {}).get("offer")
    v = st["views"].get(vid) if vid else None
    return (vid, v) if v and v["outcome"] is None else (None, None)


def resolve_by_rule(pid, st, message, names):
    """The reviewer's answer to the open offer, read by rule (capture.answer): a yes in any wording, a no, or a
    correction that names another section (the offer is re-targeted there and the note is written).
    Returns ("accepted"|"rejected", vid, view) or None."""
    vid, v = open_offer(st)
    if not v:
        return None
    msg = message.strip()
    if chat.YES.match(msg):
        res = ("accept", None)
    elif chat.NO.match(msg):
        res = ("reject", None)
    else:
        res = capture.answer(msg, [{"id": i, "name": n} for i, n in names.items()])
    if not res:
        return None
    if res[0] == "accept":
        accept_capture(pid, vid, v, res[1])
        return "accepted", vid, v
    reject_capture(pid, vid)
    return "rejected", vid, v


def tone_notes(hist):
    """Variety, enforced by looking at what was just said rather than by asking for it in general: do not open
    the way the last reply opened, and after two replies that ended in a question, end on a plain statement."""
    replies = [h["text"] for h in hist if h["role"] == "assistant" and not (h.get("meta") or {}).get("onboarding")]
    notes = []
    if replies:
        opening = " ".join(replies[-1].split()[:3])
        notes.append(f"Your last reply began “{opening}”. Begin this one differently.")
    if len(replies) >= 2 and all(r.rstrip().endswith("?") for r in replies[-2:]):
        notes.append("Your last two replies ended with a question. Unless a question is really needed, end this "
                     "reply with a plain statement.")
    return notes


def resolve_nudge(pid, st, message, sections):
    """What became of the nudge offered last turn: dismissed (an explicit "not now"/"no"), followed (they went
    there), or ignored. Two ignores count as a dismissal (see store.fold_chat)."""
    sid = ((st["last_assistant"] or {}).get("meta") or {}).get("nudge")
    if not sid or not st["nudges"].get(sid, {}).get("pending"):
        return None
    msg = message.strip()
    if nudges.NOT_NOW.search(msg) or chat.NO.match(msg):
        outcome = "dismissed"
    elif sid in nudges.mentions(msg, sections) or (chat.YES.match(msg) and not nudges.ACK_ONLY.match(msg)):
        outcome = "followed"      # they went there, or said yes. A bare "ok" only acknowledges: it is not following.
    else:
        outcome = "ignored"
    store.log(pid, "nudge_resolved", {"section": sid, "outcome": outcome})
    return outcome


def choose_nudge(pid, spans, view, phrases, st, message, ruled, wants_decline):
    """The nudge this turn may carry, or None. Never: right after a judgment decline, on a decline, twice in a row,
    or away from a natural pause. (Never during onboarding: that is a different code path.)"""
    last = (st["last_assistant"] or {}).get("meta") or {}
    if wants_decline or last.get("declined") or last.get("nudge"):
        return None
    if not nudges.natural_pause(message, just_answered_offer=bool(ruled)):
        return None
    reading = ((view["fields"] or {}).get("reading_order") or {}).get("value")
    return nudges.pick_nudge(review_state(pid, spans), reading, phrases.get("hardest_part"), st["nudges"])


def valid_views(j, message, existing, names):
    """Views the model reported that really are verbatim spans of the reviewer's message and are new."""
    out, seen = [], {norm(v["text"]) for v in existing.values()}
    for v in j.get("views") or []:
        if not isinstance(v, dict):
            continue
        text = " ".join(str(v.get("text", "")).split())
        if not text or len(text) > 600 or norm(text) not in norm(message) or norm(text) in seen:
            continue
        seen.add(norm(text))
        out.append({"text": text, "section": section_id(v.get("section"), names)})
    return out


def conflict_notes(text, spans):
    """Neutral notes where the paper's own words differ from a factual statement in the reviewer's note.
    Never says who is right; non-blocking: any failure just means no note."""
    if not FACT_CUE.search(text):
        return []
    try:
        found = pointers.check(text, spans)
    except Exception as e:
        log.warning("paper-conflict check failed: %r", e)
        return []
    by = {s["id"]: s for s in spans}
    out = []
    for p in found:
        s = by.get(p.get("span_id"))
        if p.get("kind") != "contradicts" or not s:
            continue
        sec = s["section"]
        where = f"Section {sec}" if re.match(r"^\d", sec) else f"The {sec} section"
        if p.get("lines"):
            lo, hi = p["lines"][0], p["lines"][1]
            where += f" (line {lo})" if lo == hi else f" (lines {lo}-{hi})"
        out.append({"span_id": s["id"], "section": sec, "paper_quote": p["paper_quote"],
                    "reviewer_phrase": p["reviewer_phrase"],
                    "text": f"{where} states “{p['paper_quote']}”; your note says "
                            f"“{p['reviewer_phrase']}”. Want to check?"})
        if len(out) == 2:
            break
    return out


# ------------------------------------------------------------------ the turn

def log_chat(pid, role, text, **meta):
    store.log(pid, "chat_turn", {"role": role, "kind": "chat", "text": text, "meta": meta})


def turn(pid, rid, message, spans):
    """One reviewer message in, one reply out. Returns a dict for the endpoint to send."""
    ob = store.onboarding(rid)
    if not ob["closed"]:
        return onboarding_turn(pid, rid, message, ob)
    view = onboarding.profile_view(ob)
    phrases, pref = profile_phrases(view), summary_preference(view)
    hist, names = history_turns(pid), synth.names()
    st = store.chat_state(pid)
    variant = sum(1 for h in hist if h["role"] == "assistant")
    out = {"mode": "chat", "capture": None, "resolved": None, "reword": None, "conflicts": [], "gaps": None,
           "drafted": None, "nudge": None, "cites": [], "parts": None, "added": None}
    meta = {}

    ruled = resolve_by_rule(pid, st, message, names)  # a bare "yes"/"no" to the capture offered last turn
    if ruled:
        out["resolved"] = {"outcome": ruled[0], "text": ruled[2]["text"]}
        out["_vid"] = ruled[1]
    sections = [{"id": c["id"], "name": c["name"]} for c in criteria.items()]
    previous = st["last_assistant"]                      # the turn before this message, for the nudge rules
    resolve_nudge(pid, st, message, sections)            # what became of the nudge offered last turn
    for sid in nudges.promises(message, sections):       # "I'll cover the ethics part later"
        if sid not in st["promised"]:
            store.log(pid, "section_promised", {"section": sid})
    st = dict(store.chat_state(pid), last_assistant=previous)

    if GAP_REQ.search(message):
        out["reply"], out["gaps"] = gap_reply(pid, spans, variant)
        out["reply"] = add_line(pid, out, names, out["reply"])
        out["checks"] = {"attempts": 0, "fallback": False}
        meta["intent"] = "gap_report"
    elif DRAFT_REQ.search(message):
        out["reply"], out["drafted"] = draft_reply(pid, spans, variant)
        out["reply"] = add_line(pid, out, names, out["reply"])
        out["checks"] = {"attempts": 0, "fallback": False}
        meta["intent"] = "draft"
    else:
        model_turn(pid, message, spans, view, phrases, pref, hist, st, names, ruled, variant, out, meta)

    out.pop("_vid", None)
    out["draft_changed"] = (out["resolved"] or {}).get("outcome") == "accepted" or bool((out["drafted"] or {}).get("drafted"))
    log_chat(pid, "user", message)
    if out["cites"]:                                      # kept with the reply so a reload can show the same pointers
        meta["cites"], meta["parts"] = [c["id"] for c in out["cites"]], out["parts"]
    log_chat(pid, "assistant", out["reply"], **meta)
    return out


def model_turn(pid, message, spans, view, phrases, pref, hist, st, names, ruled, variant, out, meta):
    wants_decline = chat_checks.asks_for_judgment(message)
    notes = [chat_checks.DECLINE_NOTE] if wants_decline else []
    vid, offered = open_offer(st)
    if ruled:
        did = "added it to their draft" if ruled[0] == "accepted" else "did not add it"
        notes.append(f"The reviewer just answered your offer to add “{ruled[2]['text']}”: the app {did}. "
                     "Confirm in a few words and do not offer it again.")
    elif offered:
        notes.append(f"Last turn you offered to add “{offered['text']}” under "
                     f"{names.get(offered['section'], 'their draft')}. If this message answers that offer, set "
                     "offer_response.")
    notes += tone_notes(hist)
    nudge = choose_nudge(pid, spans, view, phrases, st, message, ruled, wants_decline)
    if nudge:
        notes.append(nudges.nudge_note(nudge))
    system = build_chat_system(phrases, pref, paper_text(spans), draft_text(pid), notes,
                               sections=list(names.items()))
    reviewer_texts = [h["text"] for h in hist if h["role"] == "user"] + [message]
    ctx = {"reviewer_text": " ".join(reviewer_texts + list(phrases.values())), "wants_decline": wants_decline,
           "summary_pref": pref, "summary_requested": bool(chat_checks.SUMMARY_REQ.search(message)),
           "reword_pool": reviewer_texts + [i["text"] for i in synth.items(pid)]}
    reply, info, j = generate_checked(build_chat_messages(system, hist, message), ctx, phrases, spans)
    chat_checks.record(pid, store, info)
    out["checks"] = {"attempts": info["attempts"], "fallback": info["fallback"]}
    meta["declined"] = wants_decline or bool(chat_checks.DECLINE_MARK.search(reply[:200]))
    if info["fallback"]:
        out["reply"] = add_line(pid, out, names, reply)   # a confirmation the app already wrote is still told truthfully
        return

    intent = j.get("intent")
    shown, parts, found = cites.extract(reply, spans)    # markers out of the text; only real spans of this paper count
    if intent in ("gap_report", "draft"):
        found, parts = [], None                          # the app's own list or draft cites nothing: the PDF stays put
    if intent == "gap_report":
        reply, out["gaps"] = gap_reply(pid, spans, variant)
        meta["intent"] = "gap_report"
    elif intent == "draft":
        reply, out["drafted"] = draft_reply(pid, spans, variant)
        meta["intent"] = "draft"
    else:
        reply = shown
        if not ruled and offered and j.get("offer_response") in ("accept", "reject"):
            if j["offer_response"] == "accept":
                sec = section_id(j.get("offer_section"), names) or offered["section"]
                accept_capture(pid, vid, offered, sec)
                out["_vid"] = vid
                out["resolved"] = {"outcome": "accepted", "text": offered["text"]}
            else:
                reject_capture(pid, vid)
                out["resolved"] = {"outcome": "rejected", "text": offered["text"]}
        if isinstance(j.get("reword"), dict):
            out["reword"] = {"original": j["reword"]["original"], "text": j["reword"]["text"]}
        new = valid_views(j, message, store.chat_state(pid)["views"], names)
        have = [{"text": i["text"]} for i in synth.items(pid)]
        new = [v for v in new if not coverage.in_draft(v["text"], have)]   # already in their draft: nothing to offer
        made, several = None, False
        for v in new:
            n = len(store.chat_state(pid)["views"]) + 1
            v_id = f"v{n}"
            store.log(pid, "view_stated", {"vid": v_id, "text": v["text"], "section": v["section"]})
            if made is None and offers_in(reply, names):
                made = (v_id, v)
        if made:
            store.log(pid, "capture_offered", {"vid": made[0]})
            meta["offer"] = made[0]
            out["capture"] = {"id": made[0], "text": made[1]["text"], "section": made[1]["section"],
                              "label": names.get(made[1]["section"], "")}
            out["conflicts"] = conflict_notes(made[1]["text"], spans)   # appended after the offer, in keep_captures_honest
            several = len(new) > 1
        # Keep captures honest, and offer a view found in a prose reply. This runs before the nudge check so that a turn
        # carrying an offer is never also counted as a nudge.
        reply = keep_captures_honest(pid, message, reply, j, names, spans, out, meta, wants_decline, several)
        # A nudge counts as used when a directive was given this turn and the reply addresses that section. The model's
        # own nudge_used flag is optional (a prose reply has none); only an explicit false (it skipped the nudge) is
        # respected.
        if nudge and j.get("nudge_used") is not False and not out["capture"] and nudge_in(reply, nudge):
            store.log(pid, "nudge_offered", {"section": nudge["section"], "kind": nudge["kind"]})
            meta["nudge"] = nudge["section"]
            out["nudge"] = {"section": nudge["section"], "label": nudge["label"], "kind": nudge["kind"]}
    reply = add_line(pid, out, names, reply)
    out["reply"] = reply
    out["cites"], out["parts"] = found, cites.reconcile(parts, reply)   # a note appended above stays plain text


def offers_in(reply, names):
    """Did the model's reply offer to put something in the draft? (Its wording only tells us that it did: the offer
    the reviewer reads is the app's own line, see keep_captures_honest.)"""
    if OFFER_WORDS.search(reply) and OFFER_WHERE.search(reply):
        return True
    _, removed = capture.scrub(reply, [{"id": i, "name": n} for i, n in names.items()], claims_ok=True, offers_ok=False)
    return bool(removed)


def looks_like_view(message):
    """Is this message worth an extraction call: a statement of some length, not a question, a request or a pause?
    (The detector itself is the extraction call; this only avoids calling it for messages that cannot be views.)"""
    m = message.strip()
    if len(m.split()) < 4 or chat_checks.QUESTION_LIKE.search(m) or chat_checks.asks_for_judgment(m):
        return False
    if GAP_REQ.search(m) or DRAFT_REQ.search(m) or nudges.natural_pause(m):
        return False
    return not re.match(r"(?i)^\s*(?:please\s+)?(?:reword|rephrase|rewrite|tighten|soften|polish|make this)\b", m)


def extract_views(pid, message, names):
    """One short call for the reviewer's own words and a section id. Anything that goes wrong, or comes back that is
    not a verbatim span of the message, is no views: the turn carries on without mentioning captures."""
    sections = "\n".join(f"- {i}: {n}" for i, n in names.items())
    try:
        raw = _chat([{"role": "system", "content": prompts.VIEW_SYS},
                     {"role": "user", "content": f"Review-form sections:\n{sections}\n\nReviewer's message:\n{message}"}])
    except Exception as e:
        log.warning("view extraction failed: %r", e)
        return []
    views = capture.parse_views(raw)[:3]
    if not views:
        log.info("view extraction found none; raw[:%d] = %r", RAW_LOG_CHARS,
                 (raw if isinstance(raw, str) else repr(raw))[:RAW_LOG_CHARS])
    new = valid_views({"views": views}, message, store.chat_state(pid)["views"], names)
    have = [{"text": i["text"]} for i in synth.items(pid)]
    return [v for v in new if not coverage.in_draft(v["text"], have)]


def offer_views(pid, views, names):
    """Remember what the reviewer stated and offer the first view for capture, exactly as for a JSON reply: every view
    becomes a view_stated event, one gets a capture_offered event, and NOTHING is written to the draft. That happens
    only when the reviewer says yes (resolve_by_rule / offer_response)."""
    made = []
    for v in views:
        vid = f"v{len(store.chat_state(pid)['views']) + 1}"
        store.log(pid, "view_stated", {"vid": vid, "text": v["text"], "section": v["section"]})
        made.append((vid, v))
    if not made:
        return None
    vid, v = made[0]
    store.log(pid, "capture_offered", {"vid": vid})
    return {"id": vid, "text": v["text"], "section": v["section"], "label": names.get(v["section"], ""),
            "several": len(made) > 1}


def add_line(pid, out, names, reply):
    """The app's own "Added to X, in your own words." line, appended only when a capture was accepted this turn AND its
    note is in the store (not removed), under the section it names. The model never writes this sentence."""
    vid = out.pop("_vid", None)
    if not vid or (out["resolved"] or {}).get("outcome") != "accepted":
        return reply
    n = next((n for n in store.notes(pid) if n.get("view") == vid and not n["removed"]), None)
    if not n:
        return reply
    label = names.get(n["field"], "") if n.get("field") else ""
    out["added"] = {"note_id": n["id"], "section": n.get("field") or "", "label": label or "your draft"}
    return (reply + "\n\n" + capture.added_line(label)).strip()


def keep_captures_honest(pid, message, reply, j, names, spans, out, meta, wants_decline, several=False):
    """The reply may say something was added to the draft only if the backend recorded it this turn.
    - If the reply carried no structured fields and the message states a view, extract it and OFFER it in the app's
      own wording; nothing is written until the reviewer says yes.
    - Claims that something was added / saved / noted, and offers to do so that no offer stands behind, are removed.
    - When the app records an offer (from the model's views or from the extraction call), every offer sentence the
      model wrote is removed and the app's own line is the only offer in the reply."""
    accepted_now = (out["resolved"] or {}).get("outcome") == "accepted"
    structured = bool(j.get("views") or j.get("reword") or j.get("offer_response") or out["capture"] or out["resolved"])
    offer = None
    if not structured and not wants_decline and looks_like_view(message):
        offer = offer_views(pid, extract_views(pid, message, names), names)
    if offer:
        meta["offer"] = offer["id"]
        out["capture"] = {k: offer[k] for k in ("id", "text", "section", "label")}
        several = offer["several"]
        out["conflicts"] = conflict_notes(offer["text"], spans)
    sections = [{"id": i, "name": n} for i, n in names.items()]
    asked = bool(chat.YES.match(message.strip()) or re.search(r"(?i)\b(?:add|save|capture|keep|record)\b", message))
    recorded = bool(out["capture"])                      # an offer the app recorded this turn
    # Every model-written claim of a capture goes, even when a note was written this turn: the app says it itself
    # (add_line), after checking that the note exists.
    reply, removed = capture.scrub(reply, sections, claims_ok=False, offers_ok=False, empty_line="")
    if removed and not reply and not recorded and not accepted_now:
        reply = capture.NOT_ADDED if asked else capture.OK
    if recorded:
        cap = out["capture"]
        reply = (reply + "\n\n" + capture.offer_line(cap["label"], cap["text"] if several else None)).strip()
        if out["conflicts"]:
            reply += "\n\n" + "\n".join(c["text"] for c in out["conflicts"])
    return reply


def nudge_in(reply, nudge):
    """Did the reply actually carry the nudge (does it name the section)? Only then is it tracked as offered."""
    sec = {"id": nudge["section"], "name": nudge["label"]}
    low = reply.lower()
    return any(re.search(r"\b" + re.escape(w), low) for w in nudges.section_words(sec))


FENCE_OPEN = re.compile(r"^\s*```[A-Za-z0-9_-]*[ \t]*\n?")
FENCE_CLOSE = re.compile(r"\n?[ \t]*```\s*$")
RAW_LOG_CHARS = 500
BAD_FORMAT = ("Your last reply was empty or was not in the required format. Answer again as one JSON object with a "
              "non-empty \"reply\" (the other keys may be empty).")


def parse_reply(raw):
    """Read the model's output as (parsed dict, reply text, form). Tolerant, in this order:
      json      the whole output is a JSON object with a "reply"
      fenced    the same, inside a ``` code fence
      embedded  a JSON object with a "reply" somewhere in surrounding text (the first one wins)
      prose     plain text with no JSON at all: the text is the reply and every other field is empty
      empty     nothing usable (blank, a JSON object with no reply, or JSON-looking text that does not parse)
    Whatever the form, the reply still goes through the neutrality checks afterwards."""
    text = raw.strip() if isinstance(raw, str) else ""
    if not text:
        return {}, "", "empty"
    bare = FENCE_CLOSE.sub("", FENCE_OPEN.sub("", text, count=1), count=1).strip()
    for form, candidate in (("json", text), ("fenced", bare)):
        try:
            j = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(j, dict):
            reply = str(j.get("reply") or "").strip()
            return (j, reply, form) if reply else ({}, "", "empty")
        if isinstance(j, str) and j.strip():
            return {}, j.strip(), "prose"         # the model returned just a JSON string: that is the reply
    decoder = json.JSONDecoder()
    for m in re.finditer(r"\{", text):
        try:
            j, _ = decoder.raw_decode(text, m.start())
        except ValueError:
            continue
        if isinstance(j, dict) and str(j.get("reply") or "").strip():
            return j, str(j["reply"]).strip(), "embedded"
    if bare.startswith(("{", "[")) or '"reply"' in bare:
        return {}, "", "empty"          # looks like JSON but is not readable: never show it as if it were prose
    return {}, bare, "prose"


def call_model(msgs):
    """One model call -> (parsed dict, reply text, raw output, form). A reply that cannot be read is logged with the
    start of what came back, so the cause can be seen."""
    raw = _chat(msgs)
    j, reply, form = parse_reply(raw)
    if form != "json":
        log.warning("chat model reply was not plain JSON (read as %s); raw[:%d] = %r", form, RAW_LOG_CHARS,
                    (raw if isinstance(raw, str) else repr(raw))[:RAW_LOG_CHARS])
    return j, reply, raw, form


def checked_errors(reply, ctx, spans=()):
    """chat_checks.reply_errors on the reply as the reviewer will read it (citation markers turned into plain pointers)
    AND on the reply with every marker simply removed, so that a marker cannot split a phrase the checks would block."""
    shown = cites.extract(reply, spans)[0]
    errs = chat_checks.reply_errors(shown, ctx)
    bare = cites.plain(reply)
    if bare != shown:
        errs += [e for e in chat_checks.reply_errors(bare, ctx) if e not in errs]
    return errs


def generate_checked(msgs, ctx, phrases, spans=()):
    """Every reply passes chat_checks.reply_errors. On failure: regenerate once, then a short neutral fallback.
    An empty or unreadable reply is retried once with a short instruction to answer in the required format.
    Returns (reply, info, parsed json) where info feeds the chat_check log."""
    errs, raw, form = [], "", None
    for attempt in (1, 2):
        try:
            j, reply, raw, form = call_model(msgs)
            if form == "empty":
                errs, retry = ["the reply was empty or not in the required format"], BAD_FORMAT
            else:
                errs = checked_errors(reply, {**ctx, "reword": j.get("reword")}, spans)
                retry = chat_checks.correction(errs)
        except Exception as e:  # a down or garbling model is a failed attempt, never a 500
            log.warning("chat model call failed: %r", e)
            j, reply, form = {}, "", "error"
            errs, retry = ["the model call failed or returned unusable output"], BAD_FORMAT
        if not errs:
            return reply, {"attempts": attempt, "fallback": False, "errors": [], "form": form}, j
        msgs = msgs + [{"role": "assistant", "content": raw or "{}"}, {"role": "user", "content": retry}]
    fallback = chat_checks.decline_fallback(phrases) if ctx.get("wants_decline") else chat_checks.FALLBACK
    return fallback, {"attempts": 2, "fallback": True, "errors": errs, "form": form}, {}


# Brief acknowledgements for onboarding answers. They say "I heard you", never "that was a good answer": no
# praise, no judgment of the answer. Chosen by turn number so that consecutive acknowledgements differ.
ACKS = ["Got it.", "Okay, noted.", "Noted.", "Understood.", "Alright.", "Thanks."]
ACKS_QUOTING = ["Got it: “{w}”.", "Noted: “{w}”.", "So: “{w}”.", "Okay, “{w}”."]
ACKS_SKIPPED = ["No problem, we can leave that one.", "That's fine, I'll leave that open.", "Okay, moving on.",
                "Fine, we'll skip it."]
INTRO = ("Before we get into the paper, I'd like to ask a few quick questions about how you like to work, one at a "
         "time. You can skip any of them.")


def onboarding_ack(outcome, answer, free_text, turn):
    """A few words acknowledging the last onboarding answer, or "" when there is nothing to acknowledge
    (a first message, or a reply that was not an answer and is being followed up)."""
    if outcome == "answered":
        words = answer.split()
        if free_text and len(words) >= 4:  # the reviewer's own words, reflected back
            return ACKS_QUOTING[turn % len(ACKS_QUOTING)].format(w=" ".join(words[:12]))
        return ACKS[turn % len(ACKS)]
    if outcome in ("skipped", "defaulted"):
        return ACKS_SKIPPED[turn % len(ACKS_SKIPPED)]
    return ""


def onboarding_turn(pid, rid, message, st):
    """Onboarding runs inside the same thread: the message answers the pending question, and the reply is a short
    acknowledgement followed by the next question. A first message with no question pending gets an introduction
    and the first question."""
    key = store.reviewer_key(rid)
    ack, first = "", st["pending"] is None and st["turn"] == 0
    if st["pending"] is not None:
        answered = onboarding.process(st, message, onboarding.model_on_topic)
        for e in answered:
            store.log(key, e["type"], e["payload"])
        done = next((e["payload"] for e in answered if e["type"] == "onboarding_answered"), {})
        ack = onboarding_ack(done.get("outcome"), message.strip(), done.get("field") not in onboarding.STRUCTURED,
                             st["turn"])
        st = store.onboarding(rid)
    evs, step = onboarding.next_step(st, rid)
    for e in evs:
        store.log(key, e["type"], e["payload"])
    lead = INTRO if first and not step["done"] else ack
    reply = "\n\n".join(x for x in (lead, step_text(step)) if x)
    log_chat(pid, "user", message, onboarding=True)
    log_chat(pid, "assistant", reply, onboarding=True)
    view = onboarding.profile_view(store.onboarding(rid))
    return {"mode": "onboarding", "reply": reply, "onboarding": dict(step, profile=view)}


def step_text(step):
    """The onboarding step as chat text: the question, then the form walkthrough and criteria menu if given."""
    if step["done"]:
        return "That's all I need to get started. Tell me where you want to begin: the paper, or your review."
    parts = [step["question"]]
    if step.get("walkthrough"):
        parts.insert(0, step["walkthrough"]["text"])
    if step.get("menu"):
        parts.append("\n".join(f"{i}. {m['label']}" + (f" - {m['description']}" if m.get("description") else "")
                               for i, m in enumerate(step["menu"], 1)))
    return "\n\n".join(parts)
