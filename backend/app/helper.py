import json, re
from . import store, pointers, brief as brief_mod
from .llm import _chat, ctx
from .verify import BANNED, NUM, norm
from .ingest import locate

GROUPS = ["Claims in the abstract", "What they did", "Headline results"]
EXTRA = re.compile(r"\b(only|just|merely|limited|impressive|surprising|enough)\b", re.I)
FOOTNOTES = True
GENERIC = {"paper", "author", "work", "study", "seem", "think", "feel", "like", "real", "very", "much", "lot", "bit",
           "thing", "way", "use", "used", "instead", "low", "high", "hard", "bad", "good", "weak", "strong", "small",
           "large", "enough", "follow", "some", "also", "they", "their", "this", "that", "them", "will", "would",
           "could", "should", "just", "only", "more", "most", "any", "all", "and", "the"}

BEAR_SYS = """You show a paper reviewer facts from the paper that relate to something they just said. You never judge the paper or the reviewer's view.
Return JSON {"facts":[{"span_id":str,"quote":str,"says":str}]}.
Rules:
1. Use ONLY the spans provided. quote is copied exactly from the span (under 25 words). span_id is the id in the brackets, nothing else.
2. says is ONE plain sentence stating what the paper states there, in neutral words. Begin with "The paper" or "The authors". Do not use evaluative words (strong, weak, only, just, limited, small, large, impressive). Do not say whether anything is enough, sufficient, or adequate. Every number in says must appear in the quote.
3. Choose at most 3 facts that directly concern the specific thing the reviewer raised (a number, a method, a dataset, a claim). Choose by topic. Do not choose facts because they agree or disagree with the reviewer's view.
4. If the reviewer's view is about writing style, clarity, organization, or taste, or it names no specific number, method, dataset, or claim, return {"facts":[]}.
5. Never claim something is missing or absent. If nothing is relevant, return {"facts":[]}."""


def highlights(pid, spans):
    b = store.brief(pid)
    if not b:
        b = brief_mod.build(spans)
        store.log(pid, "brief_generated", b)
    by = {g["title"]: g for g in b.get("groups", [])}
    items = []
    for t in GROUPS:
        g = by.get(t)
        if g and g["items"]:
            it = g["items"][0]
            items.append({"text": it["text"], "span_id": it["span_id"], "quote": it["quote"],
                          "lines": it["lines"], "page": it["page"], "group": t})
    store.log(pid, "facts_shown", {"criterion": "summary", "kind": "highlights",
                                   "spans": [i["span_id"] for i in items]})
    return items


def bear(pid, spans, cname, text):
    topic = {t for t in pointers.toks(text) if t not in GENERIC}
    if not topic:
        return []
    pool = [s for s in spans
            if s["section"] != "References"
            and (s["kind"] != "loose" or (FOOTNOTES and s.get("small") and len(s["text"]) > 80))]
    cand = pointers.retrieve(text, pool, k=10)
    if not cand:
        return []
    by = {s["id"]: s for s in cand}
    user = f"Part of the review form: {cname}\nWhat the reviewer said: {text}\nSpans:\n{ctx(cand)}"
    try:
        data = json.loads(_chat([{"role": "system", "content": BEAR_SYS}, {"role": "user", "content": user}]))
    except Exception as e:
        print("[help] bear failed:", repr(e)[:200])
        return []
    out, seen = [], set()
    for it in data.get("facts", []):
        raw = str(it.get("span_id", "")).strip()
        sid = raw.split()[0] if raw else ""
        s, quote, says = by.get(sid), str(it.get("quote", "")), str(it.get("says", ""))
        why = None
        if not s or not quote:
            why = "unknown span"
        elif len(quote.split()) > 30 or norm(quote) not in norm(s["text"]):
            why = "quote not in span"
        elif (sid, norm(quote)) in seen:
            why = "duplicate"
        elif BANNED.search(says) or pointers.BAD.search(says) or EXTRA.search(says):
            why = "evaluative wording"
        elif any(n not in quote for n in NUM.findall(says)):
            why = "number not in quote"
        elif not (topic & pointers.toks(says + " " + quote)):
            why = "shares no specific word with what the reviewer said"
        if why:
            print("[help] dropped:", why, "|", says[:80])
            continue
        seen.add((sid, norm(quote)))
        out.append({"text": says, "span_id": sid, "quote": quote,
                    "lines": locate(s, quote) or s["lines"], "page": s["page"]})
        if len(out) == 3:
            break
    store.log(pid, "facts_shown", {"criterion": cname, "kind": "bear", "spans": [o["span_id"] for o in out]})
    return out


PLAN_SYS = """You decide how an assistant should respond to something a paper reviewer just wrote about one part of a review form. You never judge the paper, never say whether the reviewer is right, and never decide whether their point is good or enough. You only look at what KIND of thing they said.
Return JSON {"move": "facts"|"walk"|"followup"|"none", "sections": [int]}.
facts: the reviewer's point concerns a specific, checkable thing in the paper: a number, method, dataset, model, metric, claim, or result. The assistant will then show what the paper states about it.
walk: the reviewer says something is hard to follow, unclear, confusing, or that they did not understand some part. The assistant will offer to walk through part of the paper. In "sections", list up to 3 numbers from the section list that the reviewer's words point to (for example they mention the abstract or the method). If their words do not point to a section, return an empty list.
followup: the reviewer gave a view or reaction with no specific checkable thing in it, and is not describing difficulty understanding.
none: the message needs no help (for example a plain description or thanks).
When in doubt between facts and followup, choose followup. Never choose a move because the point is positive or negative."""


def plan(cname, text, sections):
    listing = "\n".join(f"{i}: {s}" for i, s in enumerate(sections[:60]))
    user = f"Part of the review form: {cname}\nSections of the paper:\n{listing}\nWhat the reviewer wrote: {text}"
    try:
        j = json.loads(_chat([{"role": "system", "content": PLAN_SYS}, {"role": "user", "content": user}]))
    except Exception as e:
        print("[plan] failed:", repr(e)[:200])
        return {"move": "followup", "sections": []}
    move = j.get("move") if j.get("move") in ("facts", "walk", "followup", "none") else "followup"
    secs = []
    for x in j.get("sections") or []:
        try:
            i = int(x)
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(sections) and i not in secs:
            secs.append(i)
    return {"move": move, "sections": secs[:3]}