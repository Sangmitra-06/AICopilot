import hashlib
from concurrent.futures import ThreadPoolExecutor
from . import store, synth, pointers, criteria


def h(t):
    return hashlib.sha1(t.encode("utf-8")).hexdigest()[:12]


def run(pid, spans, keys=None, force=False):
    its = synth.items(pid)
    if keys is not None:
        wanted = set(keys)
        its = [i for i in its if i["key"] in wanted]
    stored = store.facts(pid)
    out, todo = {}, []
    for it in its:
        rec = stored.get(it["key"])
        if rec and rec["hash"] == h(it["text"]) and not force:
            out[it["key"]] = rec["pointers"]
        else:
            todo.append(it)

    def one(it):
        try:
            return it, pointers.check(it["text"], spans)
        except Exception as e:
            print("[facts] check failed for", it["key"], repr(e)[:200])
            return it, None

    unchecked = []
    if todo:
        with ThreadPoolExecutor(max_workers=4) as ex:
            for it, ps in ex.map(one, todo):
                if ps is None:
                    unchecked.append(it["key"])
                    continue
                store.log(pid, "fact_check", {"key": it["key"], "hash": h(it["text"]), "pointers": ps})
                out[it["key"]] = ps
    return out, unchecked


def unresolved(pid, fields=None):
    cfg = criteria.load()
    if not cfg.get("fact_gate", True):
        return []
    facts, disp = store.facts(pid), store.disputes(pid)
    out = []
    for it in synth.items(pid):
        if fields is not None and it["field"] not in fields:
            continue
        rec = facts.get(it["key"])
        if not rec or rec["hash"] != h(it["text"]):
            continue
        bad = [p for p in rec["pointers"] if p.get("kind") == "contradicts"]
        if not bad:
            continue
        d = disp.get(it["key"])
        if cfg.get("allow_dispute", True) and d and d["hash"] == rec["hash"]:
            continue
        out.append({"key": it["key"], "text": it["text"], "field": it["field"], "pointers": bad})
    return out


def gate(pid, spans, fields=None):
    keys = None
    if fields is not None:
        keys = [i["key"] for i in synth.items(pid) if i["field"] in fields]
    run(pid, spans, keys)
    return unresolved(pid, fields)