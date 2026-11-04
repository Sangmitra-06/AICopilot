import json, re
from concurrent.futures import ThreadPoolExecutor
from . import store, pointers, guide, criteria
from .llm import _chat
from .verify import BANNED, NUM

TAGLAB = {"just": "Needs justification", "off": "Seems off", "unc": "Unclear", "rev": "Revisit later"}
CONNECT = {"also", "however", "additionally", "further", "furthermore", "moreover", "while", "although", "but",
           "overall", "first", "second", "third", "finally", "then", "next", "lastly", "both", "several", "some",
           "point", "points", "concern", "concerns", "paper", "authors", "author", "work", "review"}
CAUSAL = re.compile(r"\b(because|therefore|thus|hence|consequently|as a result|due to|which means|this means|"
                    r"implies|leading to|resulting in)\b", re.I)
FALLBACK_Q = "Where should this note go in your review?"


def names():
    return {c["id"]: c["name"] for c in criteria.items()}


def items(pid):
    valid = names()
    out = []
    for n in store.notes(pid):
        text = " ".join([n["text"]] + [a["text"] for a in n["answers"]]).strip()
        if text:
            f = criteria.fix(n.get("field", ""))
            out.append({"key": f"n{n['id']}", "kind": "note", "id": n["id"], "order": float(n["id"]),
                        "text": text, "field": f if f in valid else "", "by": n.get("field_by", "")})
    for fl in store.state(pid):
        text = " ".join([fl.get("note", "")] + fl["hist"] + [a["text"] for a in fl["answers"]]).strip()
        if text:
            f = criteria.fix(fl.get("field", ""))
            out.append({"key": f"f{fl['id']}", "kind": "flag", "id": fl["id"], "order": float(fl["id"]),
                        "text": text, "field": f if f in valid else "", "by": fl.get("field_by", ""),
                        "tag": fl.get("tag")})
    for cid, s in store.scores(pid).items():
        r = (s.get("reason") or "").strip()
        if r and cid in valid:
            out.append({"key": f"s:{cid}", "kind": "score", "id": cid, "order": s["ts"] * 1000,
                        "text": r, "field": cid, "by": "user"})
    return out


def coverage(pid):
    its = items(pid)
    sc, sk = store.scores(pid), store.skips(pid)
    out = {}
    for c in criteria.items():
        cid = c["id"]
        mine = [i for i in its if i["field"] == cid and i["kind"] != "score"]
        rec = sc.get(cid) or {}
        value = rec.get("value", "")
        skipped = bool((sk.get(cid) or {}).get("skipped"))
        done = bool(value) if c["type"] == "score" else (bool(mine) or bool((rec.get("reason") or "").strip()))
        out[cid] = {"required": c["required"], "addressed": done or skipped, "skipped": skipped,
                    "notes": len(mine), "score": value}
    return out


def missing_required(pid):
    cov = coverage(pid)
    return [{"id": c["id"], "name": c["name"], "tab": c["tab"], "type": c["type"]}
            for c in criteria.items() if c["required"] and not cov[c["id"]]["addressed"]]


def crit_listing():
    lines = []
    for c in criteria.items():
        d = c["definition"].strip()[:400] if c["has_definition"] else ""
        lines.append(f"[{c['id']}] {c['name']}" + (f": {d}" if d else ""))
    return "\n".join(lines)


SORT_SYS = """You sort a paper reviewer's notes into the parts of their review form.
The parts, with the venue's own definitions where available:
{CRITERIA}
Return JSON {"assignments":[{"key":str,"field":str|null,"ask":str|null}]}. "field" is one of the ids above, or null.
Decide only from the reviewer's own words and the definitions. A note that says something is good goes under strengths; a note that says something is a problem, or is missing or unclear, goes under weaknesses; a neutral description of the paper goes under summary; suggestions and typos go under comments. Use a score part (soundness, excitement, and so on) only when the reviewer's words clearly concern that dimension. A tag is context only, never evidence that a note is positive or negative.
If the words do not make the part clear, set field to null and write ONE short open question in "ask" using the reviewer's own words (not yes/no, no choices, under 25 words).
Never rewrite or summarize the notes. Include every key exactly once."""


def sort_items(pid):
    valid = names()
    lookup = {}
    for c in criteria.items():
        lookup[c["name"].lower()] = c["id"]
        lookup[c["tab"].lower()] = c["id"]
    its = items(pid)
    todo = [i for i in its if i["by"] != "user" and i["kind"] != "score" and not i["field"]]
    if not todo:
        return []
    listing = "\n".join(f"[{i['key']}] " + (f"(tag: {TAGLAB.get(i['tag'], i['tag'])}) " if i.get("tag") else "")
                        + i["text"] for i in todo)
    raw = _chat([{"role": "system", "content": SORT_SYS.replace("{CRITERIA}", crit_listing())},
                 {"role": "user", "content": listing}])
    data = json.loads(raw).get("assignments", [])
    by, seen = {i["key"]: i for i in todo}, {}
    for a in data:
        k = str(a.get("key", "")).strip("[] ").split(" ")[0]
        if k not in by or k in seen:
            continue
        fv = str(a.get("field") or "").strip()
        f = fv if fv in valid else lookup.get(fv.lower())
        q = None
        if f is None:
            q = (a.get("ask") or "").strip()
            if not q or guide.rule_errors(q, by[k]["text"], ""):
                q = FALLBACK_Q
        seen[k] = (f, q)
    for k in by:
        seen.setdefault(k, (None, FALLBACK_Q))
    asks = []
    for k, (f, q) in seen.items():
        it, newf = by[k], (f or "")
        if newf != it["field"] or it["by"] != "auto":
            store.log(pid, "note_field_set" if it["kind"] == "note" else "field_assigned",
                      {"id": it["id"], "field": newf, "by": "auto"})
        if q:
            asks.append({"key": k, "question": q, "text": it["text"]})
    return asks


STITCH_SYS = """You assemble one section of a paper review from the reviewer's own notes. The notes are the ONLY source of content.
Return JSON {"sentences":[{"text":str,"src":[str]}]} where src lists the note keys (like "n123" or "s:soundness") each sentence is built from.
Rules:
1. Use the reviewer's own words wherever possible. Change only tense, person (write as the reviewer, first person is fine), and small connecting words.
2. Do not add any claim, reason, example, cause, comparison, number, name, or evidence that is not in the notes.
3. Keep every hedge and every strength of wording exactly ("might", "I think", "seems", "clearly"). Do not use evaluative words the reviewer did not use.
4. Keep the reviewer's order. Use every note at least once. A sentence may cite 1 to 3 notes."""

COHESIVE_SYS = """You assemble one section of a paper review from the reviewer's own notes. The notes are the ONLY source of content. Write it as a cohesive piece in the reviewer's own voice.
Return JSON {"sentences":[{"text":str,"src":[str]}]}, where src lists the note keys (like "n123" or "s:soundness") each sentence is built from.
Rules:
1. Write as the reviewer, first person where natural. Merge notes that say the same thing, smooth the flow, and fix grammar. Keep the reviewer's own words and register where you can. Do not make it more formal, more forceful, or more polished than the reviewer's wording.
2. Add nothing: no claim, reason, example, cause, comparison, number, name, or evidence that is not in the notes.
3. Keep every hedge and level of confidence exactly ("might", "I think", "seems", "clearly"). Do not turn a suggestion into a requirement or a doubt into a conclusion. Do not use evaluative words the reviewer did not use.
4. Use only neutral joiners (and, also, first, second, then). Do not use because, therefore, thus, hence, or similar unless the reviewer used that word.
5. Keep distinct points distinct: one sentence per separate point when the section lists several, in the reviewer's order. Do not rank or reorder by importance.
6. Use every note at least once. A sentence may cite 1 to 3 notes."""

AUDIT_SYS = """You audit sentences drafted from a reviewer's notes. For each sentence, compare it with ONLY the notes cited for it.
Return JSON {"results":[{"i":int,"ok":bool,"problem":str}]}.
A sentence is NOT ok if it: states anything the notes do not say (a new claim, reason, example, cause, or comparison); adds a causal link or contrast the notes do not state; makes a hedge stronger or weaker (for example "might" becomes "is"); makes a positive or negative judgment stronger or weaker; or changes who or what is being talked about.
Changes of tense, person, grammar, and neutral joining words are fine."""


def clean(data):
    out = []
    for s in data.get("sentences", []):
        t = str(s.get("text", "")).strip()
        src = [str(x).strip("[] ") for x in (s.get("src") or [])]
        if t:
            out.append({"text": t, "src": src})
    return out


def check(sents, pool, mode):
    if not sents:
        return ["no sentences"]
    errs, used = [], set()
    lim = 0.2 if mode == "stitch" else 0.35
    for i, s in enumerate(sents):
        src = [k for k in s["src"] if k in pool]
        if not src or len(src) != len(s["src"]):
            errs.append(f"sentence {i}: src must list note keys from the list"); continue
        used.update(src)
        notes_text = " ".join(pool[k] for k in src)
        low = notes_text.lower()
        for w in BANNED.findall(s["text"]):
            if w.lower() not in low:
                errs.append(f"sentence {i}: the word '{w}' is not in the cited notes")
        for w in {x.lower() for x in CAUSAL.findall(s["text"])}:
            if w not in low:
                errs.append(f"sentence {i}: '{w}' claims a link the reviewer did not state")
        for n in NUM.findall(s["text"]):
            if n not in notes_text:
                errs.append(f"sentence {i}: number {n} is not in the cited notes")
        st, nt = pointers.toks(s["text"]), pointers.toks(notes_text)
        novel = {w for w in st - nt if w not in CONNECT}
        if len(novel) > max(2, lim * len(st)):
            errs.append(f"sentence {i}: adds words that are not in the cited notes: {sorted(novel)[:6]}")
    miss = [k for k in pool if k not in used]
    if miss:
        errs.append(f"these notes are not used: {miss}")
    return errs


def audit(sents, pool):
    listing = "\n\n".join(f"Sentence {i}: {s['text']}\nCited notes: " + " | ".join(pool[k] for k in s["src"])
                          for i, s in enumerate(sents))
    raw = _chat([{"role": "system", "content": AUDIT_SYS}, {"role": "user", "content": listing}])
    res = json.loads(raw).get("results", [])
    return [f"sentence {r.get('i')}: {r.get('problem') or 'not supported by the notes'}"
            for r in res if not r.get("ok", True)]


def draft_field(field, its, mode):
    pool = {i["key"]: i["text"] for i in its}
    listing = "\n".join(f"[{i['key']}] {i['text']}" for i in its)
    msgs = [{"role": "system", "content": STITCH_SYS if mode == "stitch" else COHESIVE_SYS},
            {"role": "user", "content": f"Section: {names()[field]}\nThe reviewer's notes, in their order:\n{listing}"}]
    for _ in range(3):
        raw = ""
        try:
            raw = _chat(msgs)
            sents = clean(json.loads(raw))
            errs = check(sents, pool, mode) or audit(sents, pool)
        except Exception as e:
            errs = [f"invalid output: {e}"]
        if not errs:
            return {"sentences": sents, "fallback": False}
        print("[draft]", field, "retry:", errs[:3])
        msgs += [{"role": "assistant", "content": raw or "{}"},
                 {"role": "user", "content": "Fix these and return the full JSON again:\n" + "\n".join(errs)}]
    return {"sentences": [{"text": i["text"], "src": [i["key"]]} for i in its], "fallback": True}


def make_draft(pid, spans, mode="smooth", only=None):
    from . import factcheck
    valid = names()
    cfg = criteria.load()
    asks = [] if only else sort_items(pid)
    miss = missing_required(pid) if (not only and cfg.get("gate", True)) else []
    conf = factcheck.gate(pid, spans, {only} if only else None) if cfg.get("fact_gate", True) else []
    if miss or conf:
        store.log(pid, "draft_blocked", {"missing": [m["id"] for m in miss], "conflicts": [c["key"] for c in conf]})
        return {"blocked": True, "missing": miss, "conflicts": conf, "asks": asks, "draft": store.draft(pid)}
    its = sorted(items(pid), key=lambda i: i["order"])
    fields = [only] if only in valid else list(valid)
    jobs = {f: [i for i in its if i["field"] == f] for f in fields}
    results = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {f: ex.submit(draft_field, f, sel, mode) for f, sel in jobs.items() if sel}
        for f, fu in futs.items():
            results[f] = fu.result()
    store.log(pid, "criteria_used", {"venue": cfg.get("venue"), "version": cfg.get("version")})
    for f in fields:
        r = results.get(f, {"sentences": [], "fallback": False})
        store.log(pid, "draft_generated", {"field": f, "mode": mode, "fallback": r["fallback"],
                                           "sentences": r["sentences"]})
    return {"blocked": False, "missing": [], "conflicts": [], "asks": asks, "draft": store.draft(pid)}