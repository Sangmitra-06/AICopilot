import hashlib, json, os, re
from . import criteria, guide
from .llm import _chat

OPEN_CACHE = {}

FALLBACK = {
    "summary": "In your own words, what is this paper about?",
    "strengths": "What, in your own words, are the reasons you would give for this paper?",
    "weaknesses": "What concerns, in your own words, would you want to raise?",
    "comments": "What would you want to tell the authors that is not a main concern?",
}
NUDGE_FALLBACK = {"describe": ["What more would you say about that?", "What else comes to mind about that?"],
                  "judge": ["What led you to that?", "What else would you say about that?"]}
ANGLE_FALLBACK = ["What else, in your own words, would you say about {name}?", "What else comes to mind for {name}?"]
OPEN_FALLBACK = ["In your own words, what would you put under {name}?", "What would you want to write under {tab}?"]

# Words that carry no topic, so two questions are compared on what they are about.
QSTOP = set("what how where which who why do does did you your would could should the a an of to in on is are it its "
            "this that these those about and for with be been can as at by from".split())


def _words(q):
    return {w for w in re.findall(r"[a-z0-9]+", q.lower()) if w not in QSTOP}


def is_repeat(q, earlier):
    """True when q is the same as, or a near-duplicate of, any earlier question."""
    a = _words(q)
    for e in earlier:
        if not e:
            continue
        b = _words(e)
        if q.strip().lower() == e.strip().lower():
            return True
        if a and b and len(a & b) / min(len(a), len(b)) >= 0.8:
            return True
    return False


def fallback_for(c, kind, earlier):
    """A canned question that has not been asked yet, or None when they are all used."""
    if kind == "open":
        pool = [FALLBACK[c["id"]]] if c["id"] in FALLBACK else []
        pool += [q.format(name=c["name"], tab=c["tab"]) for q in OPEN_FALLBACK]
    elif kind == "angle":
        pool = [q.format(name=c["tab"]) for q in ANGLE_FALLBACK]
    else:
        pool = NUDGE_FALLBACK.get(c.get("style", "judge"), NUDGE_FALLBACK["judge"])
    return next((q for q in pool if not is_repeat(q, earlier)), None)


def exhausted(why):
    return {"done": True, "question": "", "source": "exhausted", "why": why}

PROMPT_SYS = """You help a paper reviewer think about one part of the review form by asking ONE short question.
The question comes from the venue's own definition of that part (given below) and from what the reviewer has already said. You never judge the paper, never say whether anything is good or bad, and never steer the reviewer toward a conclusion.
Rules for the question:
- It starts with What, How, Where, or Which.
- It is one sentence, under 25 words, and ends with a question mark.
- It does not contain the word "or" and offers no choices.
- Ask exactly one thing. Never join two questions with "and". Do not introduce ideas such as "claims", "baselines", or "comparisons" unless the reviewer or the definition used them.
- Opening question: ask what the reviewer thinks or would say about this part, using the definition's own wording. Examples of the shape: "What do you make of how the paper handles ethics?" or "What reasons would you give for this paper?" If the reviewer already wrote notes, build on them.
- Follow-up: the reviewer just gave an answer. If the style of this part is "judge", ask what led them to their view, for example "What led you to that?". If their answer already gives a reason, ask instead what they mean by one of their own phrases, quoting that phrase. Never ask them to look something up, to reinterpret their remark, or to add a new concern. Never say or imply whether the answer is enough or good.
- Different angle: ask about an aspect of this part that the earlier questions did not cover, still in the definition's own wording. Do not repeat or reword an earlier question.
- Never repeat an earlier question.
Return JSON {"question": str}."""

JUDGE_SYS = """You audit a question an assistant wants to ask a paper reviewer about one part of a review form.
Return JSON {"leading": bool, "new_topic": bool, "reason": str}.
leading: the question presupposes a specific verdict or problem about THIS paper (for example "why is the baseline weak?"), nudges toward a particular answer, or asks the reviewer to reinterpret their own earlier remark as a strength, weakness, or concern. A question that simply asks what the reviewer thinks about the part, or what led them to a view, using the venue's own wording, is NOT leading.
new_topic: the question raises a concern, comparison, or fact about the paper that appears in neither the venue's definition nor the reviewer's words, or it introduces a concept the reviewer did not use (for example "how does it bear on the paper's claims")."""

EXPLAIN_SYS = """You explain, in plain words, what one part of a paper-review form is asking the reviewer to provide. Use only the venue's definition given below.
Rules: two or three short sentences. Say what the form asks for. Do not mention or judge any particular paper, do not give examples about one, do not say what a good answer would be, and never suggest a score, a verdict, or a point to make.
Return JSON {"text": str}."""


def prompt_errors(q, notes_text, d, name, earlier=()):
    errs = guide.rule_errors(q, notes_text, d)
    if re.search(r"\b(and|also)\s+(how|what|why|where|which|whether)\b", q, re.I):
        errs.append("asks two things; ask exactly one")
    if is_repeat(q, earlier):
        errs.append("repeats an earlier question; ask about something different")
    if errs:
        return errs
    raw = _chat([{"role": "system", "content": JUDGE_SYS},
                 {"role": "user", "content": f"Part of the form: {name}\nThe venue's definition: {d}\n"
                                              f"Reviewer's words: {notes_text or '(none)'}\nQuestion: {q}"}])
    j = json.loads(raw)
    out = []
    if j.get("leading"):
        out.append("leading: " + str(j.get("reason", "")))
    if j.get("new_topic"):
        out.append("raises a topic that is in neither the definition nor the reviewer's words")
    return out


def explain_part(c):
    d = c["definition"].strip()[:3000] if c["has_definition"] else ""
    if not d:
        return {"done": False, "question": "", "source": "default",
                "text": f"This part of the form is called {c['name']}. The venue has not added a definition for it yet, so there is nothing more to explain.",
                "why": "no definition has been added for this part"}
    t = ""
    try:
        raw = _chat([{"role": "system", "content": EXPLAIN_SYS},
                     {"role": "user", "content": f"Part of the form: {c['name']}\nThe venue's definition:\n{d}"}])
        t = str(json.loads(raw).get("text", "")).strip()
    except Exception as e:
        print("[talk] explain failed:", repr(e)[:200])
    if not t or len(t) > 900:
        t = d[:500]
    return {"done": False, "question": "", "text": t, "source": "definition", "why": ""}


def next_question(cid, notes_text, history, kind="open", asked=()):
    """`asked`: every question already put to the reviewer for this part (from the event log)."""
    c = criteria.by_id()[cid]
    style = c.get("style", "judge")
    if kind == "more":
        return {"done": False, "question": f"What else, if anything, would you add under {c['tab']}?",
                "source": "template", "why": ""}
    if kind == "explain":
        return explain_part(c)
    if kind == "deeper":
        kind = "nudge"
    history = [h for h in (history or []) if isinstance(h, dict)]
    if kind == "nudge" and not history:
        kind = "open"
    earlier = [h.get("q", "") for h in history if h.get("q")] + [q for q in asked if q]
    if kind == "open":
        history = []
    d = c["definition"].strip()[:3000] if c["has_definition"] else ""
    key = (cid, hashlib.sha1(d.encode("utf-8")).hexdigest()[:10])
    cacheable = kind == "open" and not (notes_text or "").strip() and not earlier
    if cacheable and key in OPEN_CACHE:
        return dict(OPEN_CACHE[key])
    fb = fallback_for(c, kind, earlier)
    if not d:
        if fb is None:
            return exhausted("no definition has been added for this part, and the default questions are used up")
        return {"done": False, "question": fb, "source": "default",
                "why": "no definition has been added for this part"}
    answered = " ".join(h.get("a", "") for h in history)
    pool = ((notes_text or "") + " " + answered).strip()
    wanted = {"open": "an opening question", "nudge": "a follow-up on the reviewer's last answer",
              "angle": "a question from a different angle"}.get(kind, "an opening question")
    user = (f"Part of the form: {c['name']}\nStyle of this part: {style}\nThe venue's definition:\n{d}\n"
            f"The reviewer's notes so far: {notes_text or '(none)'}\n"
            f"Kind of question wanted: {wanted}\n"
            f"Earlier questions and the reviewer's answers: {json.dumps(history) if history else '(none yet)'}\n"
            f"Earlier questions to avoid repeating: {earlier}")
    msgs = [{"role": "system", "content": PROMPT_SYS}, {"role": "user", "content": user}]
    last = []
    for _ in range(3):
        raw, q = "", ""
        try:
            raw = _chat(msgs)
            q = json.loads(raw)["question"].strip()
            errs = prompt_errors(q, pool, d, c["name"], earlier)
        except Exception as e:
            errs = [f"invalid output: {e}"]
        if not errs:
            out = {"done": False, "question": q, "source": "definition", "why": ""}
            if cacheable:
                OPEN_CACHE[key] = out
            return dict(out)
        last = errs
        print("[talk]", cid, kind, "retry:", errs[:3], "|", q)
        msgs += [{"role": "assistant", "content": raw or "{}"},
                 {"role": "user", "content": "Rewrite the question. Problems:\n" + "\n".join(errs)}]
    why = "no clean question after 3 tries: " + "; ".join(last[:2])
    if fb is None:
        return exhausted(why + "; the default questions are used up")
    return {"done": False, "question": fb, "source": "default", "why": why}


def diagnose():
    out = []
    for c in criteria.items():
        out.append({"id": c["id"], "name": c["name"], "type": c["type"], "required": c["required"],
                    "definition": "found" if c["has_definition"] else "missing",
                    "definition_chars": len(c["definition"]) if c["has_definition"] else 0,
                    "scale_values": [x["value"] for x in c["scale"]],
                    "used_by": ["sorting notes", "questions"] if c["has_definition"] else []})
    return out