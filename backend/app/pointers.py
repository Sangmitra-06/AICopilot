import re, json
from .llm import _chat, ctx
from .verify import BANNED, norm
from .ingest import locate
from .prompts import NEUTRALITY

STOP = set("the a an of to and or in on for with is are was were that this it as by be at from we they their not no never why how what which".split())
BAD = re.compile(r"\b(address(es|ed)?|resolv\w*|fix(es|ed)?|enough|sufficient\w*|adequate\w*|you should|you must)\b", re.I)
TOK = re.compile(r"\d+(?:\.\d+)?|[a-z]+")


def stem(w):
    if w[0].isdigit():
        return w
    for suf in ("ations", "ation", "ing", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[:-len(suf)]
    return w


def toks(s):
    return {stem(w) for w in TOK.findall(s.lower()) if w not in STOP and (len(w) > 2 or "." in w)}


def retrieve(note, spans, k=8):
    q = toks(note)
    scored = [(len(q & toks(s["text"])), s) for s in spans]
    scored = [x for x in scored if x[0] > 0]
    scored.sort(key=lambda x: (-x[0], x[1]["kind"] != "body"))
    return [s for _, s in scored[:k]]


POINT_SYS = """A reviewer wrote a note about a paper.
""" + NEUTRALITY + """
Using ONLY the spans provided, find places where the
paper directly bears on a FACTUAL statement or an open question in the note. Two kinds:
- "contradicts": the note states what the paper says or did, and a span says something different.
- "answers": the note says something is missing, unexplained, or unreported, and a span reports it.
Return JSON {"pointers":[{"kind":"contradicts"|"answers","reviewer_phrase":str,"span_id":str,"paper_quote":str,"explanation":str}]}.
Rules:
1. reviewer_phrase is copied exactly from the note. paper_quote is copied exactly from the span.
2. explanation is ONE sentence stating what the paper says, as plain fact.
3. Never say whether the paper settles, satisfies, or weakens the reviewer's point. Never use evaluative words.
4. Ignore opinions, emphasis, wording, and importance.
5. Never claim something is absent from the paper. If unsure, return {"pointers":[]}.
6. Do not return a pointer for a span that only repeats the note. A span that gives a different number, name, or fact than the note must still be returned as "contradicts".
7. Prefer spans from the main text over table or figure captions."""


def check(note, spans):
    by = {s["id"]: s for s in spans}
    cand = retrieve(note, spans)
    print("[pointers] candidates:", [s["id"] for s in cand])
    if not note.strip() or not cand:
        return []
    raw = _chat([{"role": "system", "content": POINT_SYS},
                 {"role": "user", "content": f"Reviewer note:\n{note}\n\nSpans:\n{ctx(cand)}"}])
    print("[pointers] model said:", raw[:900])
    try:
        items = json.loads(raw).get("pointers", [])
    except Exception:
        return []
    out, seen = [], set()
    for p in items:
        raw_id = str(p.get("span_id", "")).strip()
        sid = raw_id.split()[0] if raw_id else ""
        s = by.get(sid)
        expl = p.get("explanation", "")
        key = (p.get("kind"), p.get("reviewer_phrase"))
        why = None
        if not s:
            why = "unknown span"
        elif p.get("kind") not in ("contradicts", "answers"):
            why = "bad kind"
        elif key in seen:
            why = "duplicate"
        elif not p.get("paper_quote") or norm(p["paper_quote"]) not in norm(s["text"]):
            why = "quote not in span"
        elif not p.get("reviewer_phrase") or norm(p["reviewer_phrase"]) not in norm(note):
            why = "phrase not in note"
        elif BANNED.search(expl) or BAD.search(expl):
            why = "banned wording in explanation"
        if why:
            print("[pointers] rejected:", why, "|", expl[:100])
            continue
        seen.add(key)
        out.append({**p, "span_id": sid, "lines": locate(s, p["paper_quote"]) or s["lines"], "page": s["page"]})
    return out