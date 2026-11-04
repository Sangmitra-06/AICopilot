import re, json
from .llm import _chat, ctx
from .verify import BANNED, NUM, norm
from .ingest import locate

GROUPS = ["Claims in the abstract", "What they did", "Contributions they list",
          "Headline results", "Limitations they state"]
PICK = re.compile(r"abstract|introduction|conclusion|limitation", re.I)

BRIEF_SYS = """You build a short brief of a paper from the authors' OWN emphasis. You never judge the paper and never decide what matters: you only surface what the authors themselves state.
Return JSON {"groups":[{"title":str,"items":[{"text":str,"span_id":str,"quote":str}]}]} using exactly these group titles, in this order: {GROUPS}
Rules:
1. Every item restates something the authors explicitly state, phrased as "The authors say / report / introduce ...". It is the authors' framing, labeled as theirs.
2. "Claims in the abstract": claims made in the Abstract. "What they did": the data, method, or setup the authors describe. "Contributions they list": contributions the authors name. "Headline results": results the authors state in the abstract, introduction, or conclusion. "Limitations they state": limitations the authors state about their own work.
3. At most 4 items per group, in the paper's order. Include only what is stated. Add nothing.
4. quote is the shortest exact snippet (under 20 words) copied from the span named by span_id that supports the item. Every number in text must appear in that quote. span_id is the id in the brackets, nothing else.
5. Never use evaluative words (key, important, strong, weak, novel, impressive...) outside a quote.
6. If a group has nothing stated, return it with an empty items list."""


def pool_of(spans):
    pool = [s for s in spans if s["kind"] == "body" and PICK.search(s["section"])
            and not s["section"].startswith(("A.", "A "))]
    if len(pool) < 3:
        pool = [s for s in spans if s["kind"] == "body"][:25]
    return pool


def clean(data, by):
    errs, groups = [], []
    got = data.get("groups", [])
    if [g.get("title") for g in got] != GROUPS:
        errs.append("use exactly these group titles, in this order: " + "; ".join(GROUPS))
    for g in got:
        items = []
        for j, it in enumerate((g.get("items") or [])[:4]):
            raw_id = str(it.get("span_id", "")).strip()
            sid = raw_id.split()[0] if raw_id else ""
            text, quote = str(it.get("text", "")).strip(), str(it.get("quote", "")).strip()
            s, tag = by.get(sid), f"{g.get('title')} item {j}"
            if not s:
                errs.append(f"{tag}: unknown span_id"); continue
            if not quote or norm(quote) not in norm(s["text"]) or len(quote.split()) > 25:
                errs.append(f"{tag}: quote must be verbatim from the span and under 25 words"); continue
            if BANNED.search(re.sub(r'"[^"]*"', "", text)):
                errs.append(f"{tag}: evaluative wording"); continue
            bad = [n for n in NUM.findall(text) if n not in quote]
            if bad:
                errs.append(f"{tag}: number {bad[0]} is not in the quote"); continue
            items.append({"text": text, "span_id": sid, "quote": quote,
                          "lines": locate(s, quote) or s["lines"], "page": s["page"]})
        groups.append({"title": g.get("title"), "items": items})
    return groups, errs


def build(spans):
    pool = pool_of(spans)
    by = {s["id"]: s for s in pool}
    msgs = [{"role": "system", "content": BRIEF_SYS.replace("{GROUPS}", "; ".join(GROUPS))},
            {"role": "user", "content": "Spans:\n" + ctx(pool)}]
    groups = []
    for _ in range(3):
        raw = ""
        try:
            raw = _chat(msgs)
            groups, errs = clean(json.loads(raw), by)
        except Exception as e:
            groups, errs = [], [f"invalid JSON: {e}"]
        if not errs:
            break
        print("[brief] retry:", errs[:4])
        msgs += [{"role": "assistant", "content": raw or "{}"},
                 {"role": "user", "content": "Fix these and return the full JSON again:\n" + "\n".join(errs)}]
    by_title = {g["title"]: g for g in groups}
    return {"groups": [by_title.get(t, {"title": t, "items": []}) for t in GROUPS]}