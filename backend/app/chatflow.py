"""Chat-first turn handling: one endpoint, one prompt, free-form replies.

POST /chat/{pid} lands in turn(). Until onboarding has closed, the message is routed to the onboarding rules
(onboarding.py). After that it is a free conversation: the prompt is built from the shared NEUTRALITY block,
the reviewer's PROFILE, the paper, the review draft and the last 20 turns, in full (prompts.py).
"""
import json
import logging
import re

from . import store, onboarding, synth
from .llm import _chat
from .prompts import build_chat_system, build_chat_messages

log = logging.getLogger("copilot.chat")

HISTORY_TURNS = 20
PAPER_CHAR_CAP = 240_000  # about 60k tokens; References are always left out first
FALLBACK = ("I couldn't put together a reply I'm happy with just now. Tell me where you'd like to go next: "
            "a part of the paper, or a part of your review.")


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


# ------------------------------------------------------------------ the turn

def log_chat(pid, role, text, **meta):
    store.log(pid, "chat_turn", {"role": role, "kind": "chat", "text": text, "meta": meta})


def turn(pid, rid, message, spans):
    """One reviewer message in, one reply out. Returns a dict for the endpoint to send."""
    ob = store.onboarding(rid)
    if not ob["closed"]:
        return onboarding_turn(pid, rid, message, ob)
    view = onboarding.profile_view(ob)
    system = build_chat_system(profile_phrases(view), summary_preference(view),
                               paper_text(spans), draft_text(pid))
    msgs = build_chat_messages(system, history_turns(pid), message)
    reply = generate(msgs)
    log_chat(pid, "user", message)
    log_chat(pid, "assistant", reply)
    return {"mode": "chat", "reply": reply}


def generate(msgs):
    """One model call. A reply that is not usable JSON with a non-empty "reply" becomes the fallback."""
    try:
        reply = str(json.loads(_chat(msgs)).get("reply") or "").strip()
    except Exception as e:
        log.warning("chat model call failed: %r", e)
        reply = ""
    return reply or FALLBACK


def onboarding_turn(pid, rid, message, st):
    """Onboarding runs inside the same thread: the message answers the pending question, and the reply is
    the next question. A first message with no question pending just gets the first question."""
    key = store.reviewer_key(rid)
    if st["pending"] is not None:
        for e in onboarding.process(st, message, onboarding.model_on_topic):
            store.log(key, e["type"], e["payload"])
        st = store.onboarding(rid)
    evs, step = onboarding.next_step(st, rid)
    for e in evs:
        store.log(key, e["type"], e["payload"])
    reply = step_text(step)
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
