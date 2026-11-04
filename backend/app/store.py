import sqlite3, json, os, time, threading

db = sqlite3.connect(os.environ.get("COPILOT_DB", "copilot.db"), check_same_thread=False)
LOCK = threading.RLock()
with LOCK:
    db.execute("create table if not exists events(id integer primary key, ts real, paper text, type text, payload text)")
    db.commit()


def log(paper, type_, payload):
    with LOCK:
        db.execute("insert into events(ts,paper,type,payload) values(?,?,?,?)",
                   (time.time(), paper, type_, json.dumps(payload)))
        db.commit()


def events(paper):
    with LOCK:
        rows = db.execute("select id,ts,type,payload from events where paper=? order by id", (paper,)).fetchall()
    out = []
    for r in rows:
        try:
            payload = json.loads(r[3]) if r[3] else None
        except Exception:
            payload = None
        if payload is None:
            continue
        out.append({"id": r[0], "ts": r[1], "type": r[2], "payload": payload})
    return out


def state(paper):
    flags = {}
    for e in events(paper):
        p, t = e["payload"], e["type"]
        if t == "flag_created":
            flags[p["id"]] = {**p, "hist": [], "answers": [], "versions": [], "edits": 0,
                              "field": p.get("field", ""), "field_by": "", "status": "open"}
        elif p.get("id") not in flags:
            continue
        elif t == "note_edited":
            f = flags[p["id"]]
            f["versions"].append({"old": f.get("note", ""), "new": p["note"], "ts": e["ts"]})
            f["note"] = p["note"]; f["edits"] += 1
        elif t == "revisit_added":
            flags[p["id"]]["hist"].append(p["text"]); flags[p["id"]]["status"] = "revisited"
        elif t == "answer_added":
            flags[p["id"]]["answers"].append({"question": p["question"], "text": p["text"]})
        elif t == "field_assigned":
            flags[p["id"]]["field"] = p["field"]
            flags[p["id"]]["field_by"] = p.get("by", "user")
    return list(flags.values())


def notes(paper):
    out = {}
    for e in events(paper):
        p, t = e["payload"], e["type"]
        if t == "note_added":
            out[p["id"]] = {**p, "answers": [], "versions": [], "edits": 0, "removed": False,
                            "field_by": "user" if p.get("field") else ""}
        elif p.get("id") not in out:
            continue
        elif t == "note_text_edited":
            n = out[p["id"]]
            n["versions"].append({"old": n["text"], "new": p["text"], "ts": e["ts"]})
            n["text"] = p["text"]; n["edits"] += 1
        elif t == "note_answer_added":
            out[p["id"]]["answers"].append({"question": p["question"], "text": p["text"]})
        elif t == "note_field_set":
            out[p["id"]]["field"] = p["field"]
            out[p["id"]]["field_by"] = p.get("by", "user")
        elif t == "note_removed":
            out[p["id"]]["removed"] = True
    return [n for n in out.values() if not n["removed"]]


def draft(paper):
    d = {}
    for e in events(paper):
        p, t = e["payload"], e["type"]
        if t == "draft_generated":
            d[p["field"]] = {"mode": p["mode"], "fallback": p.get("fallback", False),
                             "sentences": [dict(s, edits=0, versions=[]) for s in p["sentences"]]}
        elif t == "draft_edited" and p["field"] in d:
            sents = d[p["field"]]["sentences"]
            if 0 <= p["idx"] < len(sents):
                s = sents[p["idx"]]
                s["versions"].append({"old": s["text"], "new": p["text"], "ts": e["ts"]})
                s["text"] = p["text"]; s["edits"] += 1
    return d

def scores(paper):
    out = {}
    for e in events(paper):
        if e["type"] != "score_set":
            continue
        p = e["payload"]
        cur = out.get(p["criterion"])
        rec = {"value": p.get("value") or (cur["value"] if cur else ""),
               "reason": p.get("reason", ""), "ts": e["ts"]}
        rec["versions"] = (cur["versions"] + [{"value": cur["value"], "reason": cur["reason"], "ts": cur["ts"]}]) if cur else []
        out[p["criterion"]] = rec
    return out


def brief(paper):
    b = None
    for e in events(paper):
        if e["type"] == "brief_generated":
            b = e["payload"]
    return b


def thread(paper, limit=200):
    t = [dict(e["payload"], ts=e["ts"]) for e in events(paper) if e["type"] == "chat_turn"]
    return t[-limit:]

def asked_questions(paper, criterion):
    """Every question already put to the reviewer for one part of the form."""
    return [e["payload"]["question"] for e in events(paper)
            if e["type"] == "question_asked" and e["payload"].get("criterion") == criterion
            and e["payload"].get("question")]


def skips(paper):
    out = {}
    for e in events(paper):
        if e["type"] == "criterion_skip":
            p = e["payload"]
            out[p["criterion"]] = {"skipped": bool(p.get("skipped", True)), "note": p.get("note", ""), "ts": e["ts"]}
    return out


def reviewer_key(reviewer):
    """Profile events share the event table; the reviewer id stands where a paper id would."""
    return "reviewer:" + reviewer


def fold_onboarding(evs):
    """Pure replay of a reviewer's profile events into onboarding state.

    Event types: profile_field_set, evidence_set, onboarding_asked, onboarding_answered,
    walkthrough_shown, onboarding_closed. Later events win. No profile schema lives here.
    """
    st = {"fields": {}, "evidence": {}, "turn": 0, "followups": {}, "asked": [], "pending": None,
          "closed": None, "walkthrough_shown": False, "last_answer": None}
    for e in evs:
        p, t = e["payload"], e["type"]
        if t == "profile_field_set":
            st["fields"][p["field"]] = {k: v for k, v in p.items() if k != "field"} | {"ts": e.get("ts")}
        elif t == "evidence_set":
            st["evidence"][p["key"]] = {k: v for k, v in p.items() if k != "key"} | {"ts": e.get("ts")}
        elif t == "onboarding_asked":
            st["pending"] = p
            if p["kind"] == "followup":
                st["followups"][p["field"]] = st["followups"].get(p["field"], 0) + 1
            elif p["field"] not in st["asked"]:
                st["asked"].append(p["field"])
        elif t == "onboarding_answered":
            st["turn"] += 1
            st["pending"] = None
            st["last_answer"] = p if p.get("outcome") == "answered" else None
        elif t == "walkthrough_shown":
            st["walkthrough_shown"] = True
        elif t == "onboarding_closed":
            st["closed"] = p
            st["pending"] = None
    return st


def onboarding(reviewer):
    return fold_onboarding(events(reviewer_key(reviewer)))


def facts(paper):
    out = {}
    for e in events(paper):
        if e["type"] == "fact_check":
            p = e["payload"]
            out[p["key"]] = {"hash": p["hash"], "pointers": p.get("pointers", []), "ts": e["ts"]}
    return out


def disputes(paper):
    out = {}
    for e in events(paper):
        if e["type"] == "fact_dispute":
            p = e["payload"]
            out[p["key"]] = {"hash": p["hash"], "reason": p.get("reason", ""), "ts": e["ts"]}
    return out