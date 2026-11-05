import base64, hashlib, logging, os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
import pymupdf
from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import re
from contextlib import asynccontextmanager
from . import fresh, ingest, llm, store, pointers, synth, criteria, criterion, factcheck, chat, helper, onboarding, venue, chatflow
from . import brief as brief_mod, walk as walk_mod
from . import guide as guide_mod


@asynccontextmanager
async def lifespan(_app):
    # Fails fast if definitions/venue_criteria.json is missing or malformed, and warns in the logs
    # while its source is still marked as placeholder text.
    venue.warn_if_placeholder()
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware,
                   allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
                   allow_methods=["*"], allow_headers=["*"])
CACHE = {}
MAXP = int(os.environ.get("MAXP", "8"))
DATA_DIR = os.environ.get("COPILOT_DATA_DIR", "data")


def spans_of(pid):
    if pid not in CACHE:
        sp = walk_mod.add_tops(ingest.ingest(f"{DATA_DIR}/{pid}.pdf"), ingest.INFO.get("headings"))   # (ingest: old flow)
        for e in store.events(pid):
            if e["type"] == "span_added":
                sp.append(e["payload"])
        CACHE[pid] = sp
    return CACHE[pid]


def pdf_ctx(pid, focus):
    spans = spans_of(pid)
    total = max(s["page"] for s in spans if s.get("page"))
    order = []
    for s in focus:
        if s["page"] not in order:
            order.append(s["page"])
    for p in range(1, total + 1):
        if p not in order:
            order.append(p)
    return {"path": f"{DATA_DIR}/{pid}.pdf", "pages": sorted(order[:MAXP]), "store": spans}


def log_new(pid, out):
    for s in out.get("new_spans", []):
        store.log(pid, "span_added", s)


def sent_text(out):
    if out.get("declined"):
        return out.get("message", "")
    return " ".join(s["text"] for s in out.get("sentences", []))


def log_turn(pid, user_text, out, kind, title=""):
    if user_text:
        store.log(pid, "chat_turn", {"role": "user", "kind": kind, "text": user_text})
    store.log(pid, "chat_turn", {"role": "assistant", "kind": kind, "title": title,
                                 "text": sent_text(out), "sentences": out.get("sentences", []),
                                 "declined": out.get("message", "") if out.get("declined") else ""})


class Explain(BaseModel): paper_id: str; section: str; simpler: bool = False
class Ask(BaseModel): paper_id: str; question: str; context: str = ""; history: list[dict] = []
class Teach(BaseModel): paper_id: str; section: str; text: str
class Event(BaseModel): paper_id: str; type: str; payload: dict
class Guide(BaseModel):
    paper_id: str; tag: str; span_ids: list[str]
    flag_id: Optional[int] = None; note: str = ""; previous: list[str] = []
class Pointer(BaseModel): paper_id: str; note: str; flag_id: Optional[str] = None
class Select(BaseModel): paper_id: str; page: int; rect: list[float]
class ExplainSpans(BaseModel): paper_id: str; span_ids: list[str]; simpler: bool = False
class SelAsk(BaseModel):
    paper_id: str; page: int; rect: list[float]; question: str = "What does this show?"
class Sort(BaseModel): paper_id: str
class Draft(BaseModel): paper_id: str; mode: str = "smooth"; field: Optional[str] = None
class Score(BaseModel): paper_id: str; criterion: str; value: str = ""; reason: str = ""
class Talk(BaseModel): paper_id: str; criterion: str; history: list[dict] = []; kind: str = "open"
class Skip(BaseModel): paper_id: str; criterion: str; skipped: bool = True; note: str = ""
class BriefReq(BaseModel): paper_id: str; force: bool = False
class Verify(BaseModel): paper_id: str; keys: Optional[list[str]] = None; force: bool = False
class Dispute(BaseModel): paper_id: str; key: str; reason: str


@app.post("/papers")
async def upload(file: UploadFile):
    data = await file.read()
    pid = hashlib.sha1(data).hexdigest()[:10]
    os.makedirs(DATA_DIR, exist_ok=True)
    open(f"{DATA_DIR}/{pid}.pdf", "wb").write(data)
    return {"paper_id": pid, "sections": list(dict.fromkeys(s["section"] for s in spans_of(pid)))}


@app.get("/papers/{pid}/pdf")
def pdf(pid: str):
    path = f"{DATA_DIR}/{pid}.pdf"
    if not os.path.isfile(path):
        raise HTTPException(404, "paper not found")
    return FileResponse(path)


@app.get("/papers/{pid}/spans")
def spans(pid: str): return spans_of(pid)


@app.get("/walk/{pid}")
def walk(pid: str):
    out = []
    for s in spans_of(pid):
        sec = s["section"]
        if sec == "References":
            break
        if sec in ("Front matter", "Added from PDF") or s["kind"] == "loose":
            continue
        if sec not in out:
            out.append(sec)
    return out


@app.post("/explain")
def explain(r: Explain):
    spans = spans_of(r.paper_id)
    sec = [s for s in spans if s["section"] == r.section and s["kind"] != "loose"]
    out = llm.explain(sec, r.simpler, pdf_ctx(r.paper_id, sec))
    log_new(r.paper_id, out)
    log_turn(r.paper_id, "", out, "explain", r.section)
    return out


@app.post("/ask")
def ask(r: Ask):
    spans = spans_of(r.paper_id)
    hist = r.history[-6:]
    query = r.question + " " + r.context + " " + " ".join(str(h.get("text", ""))[:300] for h in hist[-2:])
    focus = pointers.retrieve(query, spans)
    out = llm.ask(r.question, spans, pdf_ctx(r.paper_id, focus), r.context, hist)
    log_new(r.paper_id, out)
    log_turn(r.paper_id, r.question, out, "ask")
    store.log(r.paper_id, "ask", {"question": r.question, "context": r.context,
                                  "declined": bool(out.get("declined"))})
    return out


@app.get("/thread/{pid}")
def get_thread(pid: str): return store.thread(pid)


@app.post("/teachback")
def teach(r: Teach):
    store.log(r.paper_id, "teachback", {"section": r.section, "text": r.text})
    return {"mismatches": llm.teachback(r.text, [s for s in spans_of(r.paper_id) if s["section"] == r.section])}


@app.post("/guide")
def guide_ep(r: Guide):
    by = {s["id"]: s for s in spans_of(r.paper_id)}
    out = guide_mod.guide(r.tag, r.note, [by[x] for x in r.span_ids if x in by], r.previous)
    if "question" in out:
        store.log(r.paper_id, "question_asked", {"flag_id": r.flag_id, **out})
    return out


@app.post("/pointers")
def pointers_ep(r: Pointer):
    out = pointers.check(r.note, spans_of(r.paper_id))
    if out:
        store.log(r.paper_id, "pointer_shown", {"flag_id": r.flag_id, "pointers": out})
    return out


def facts_view(pid):
    stored, disp = store.facts(pid), store.disputes(pid)
    out = {}
    for it in synth.items(pid):
        rec = stored.get(it["key"])
        if not rec or rec["hash"] != factcheck.h(it["text"]):
            continue
        d = disp.get(it["key"])
        out[it["key"]] = {"pointers": rec["pointers"],
                          "disputed": d["reason"] if d and d["hash"] == rec["hash"] else ""}
    return out


@app.get("/facts/{pid}")
def facts_ep(pid: str): return facts_view(pid)


@app.post("/verify")
def verify(r: Verify):
    _, unchecked = factcheck.run(r.paper_id, spans_of(r.paper_id), r.keys, r.force)
    return {"facts": facts_view(r.paper_id), "unchecked": unchecked}


@app.post("/dispute")
def dispute(r: Dispute):
    if not criteria.load().get("allow_dispute", True):
        raise HTTPException(403, "Disputes are turned off for this venue.")
    reason = r.reason.strip()
    if not reason:
        raise HTTPException(400, "Write why you disagree with the check.")
    it = next((i for i in synth.items(r.paper_id) if i["key"] == r.key), None)
    if not it:
        raise HTTPException(404, "unknown note")
    store.log(r.paper_id, "fact_dispute", {"key": r.key, "hash": factcheck.h(it["text"]), "reason": reason})
    return {"ok": True}


@app.post("/events")
def event(e: Event):
    store.log(e.paper_id, e.type, e.payload); return {"ok": True}


@app.get("/state/{pid}")
def state(pid: str): return store.state(pid)


@app.get("/notes/{pid}")
def notes_ep(pid: str): return store.notes(pid)


@app.get("/draft/{pid}")
def get_draft(pid: str): return store.draft(pid)


@app.get("/history/{pid}")
def history(pid: str): return store.events(pid)


@app.post("/sort")
def sort_ep(r: Sort):
    return {"asks": synth.sort_items(r.paper_id)}


@app.post("/draft")
def draft_ep(r: Draft):
    return synth.make_draft(r.paper_id, spans_of(r.paper_id),
                            r.mode if r.mode in ("stitch", "smooth") else "smooth", r.field)
@app.get("/criteria")
def criteria_ep():
    try:
        return criteria.load()
    except Exception as e:
        raise HTTPException(500, f"criteria.json problem: {e}")


@app.get("/criteria/diagnose")
def crit_diag(): return criterion.diagnose()


@app.get("/criteria/status/{pid}")
def crit_status(pid: str):
    its = synth.items(pid)
    sc = store.scores(pid)
    dr = store.draft(pid)
    cov = synth.coverage(pid)
    out = {}
    for c in criteria.items():
        cid = c["id"]
        cv = cov[cid]
        mine = [i for i in its if i["field"] == cid]
        d = dr.get(cid)
        started = bool(mine) or bool(cv["score"]) or cv["skipped"]
        drafted = bool(d and d["sentences"])
        out[cid] = {"notes": cv["notes"], "score": cv["score"] or None,
                    "reason": sc.get(cid, {}).get("reason", ""),
                    "required": cv["required"], "addressed": cv["addressed"], "skipped": cv["skipped"],
                    "status": "drafted" if drafted else ("started" if started else "empty")}
    cfg = criteria.load()
    gate = cfg.get("gate", True)
    miss = synth.missing_required(pid)
    conf = factcheck.unresolved(pid)
    return {"criteria": out, "unsorted": len([i for i in its if not i["field"]]),
            "started": sum(1 for v in out.values() if v["status"] != "empty"), "total": len(out),
            "gate": gate, "missing": miss if gate else [], "conflicts": [c["key"] for c in conf],
            "ready": ((not gate) or not miss) and not conf,
            "allow_dispute": cfg.get("allow_dispute", True)}


@app.get("/scores/{pid}")
def scores_ep(pid: str): return store.scores(pid)


@app.post("/score")
def score(r: Score):
    c = criteria.by_id().get(r.criterion)
    if not c or c["type"] != "score":
        raise HTTPException(400, "not a score criterion")
    v = criteria.val(r.value) if r.value else ""
    vals = [x["value"] for x in c["scale"]]
    if v and vals and v not in vals:
        raise HTTPException(400, "value not on this scale")
    store.log(r.paper_id, "score_set", {"criterion": r.criterion, "value": v, "reason": r.reason})
    return store.scores(r.paper_id)[r.criterion]


@app.post("/talk")
def talk(r: Talk):
    if r.criterion not in criteria.by_id():
        raise HTTPException(400, "unknown criterion")
    notes_text = " ".join(i["text"] for i in synth.items(r.paper_id) if i["field"] == r.criterion)
    out = criterion.next_question(r.criterion, notes_text, r.history, r.kind,
                                  store.asked_questions(r.paper_id, r.criterion))
    store.log(r.paper_id, "question_asked", {"criterion": r.criterion, "kind": r.kind, **out})
    return out


@app.post("/skip")
def skip(r: Skip):
    if r.criterion not in criteria.by_id():
        raise HTTPException(400, "unknown criterion")
    store.log(r.paper_id, "criterion_skip", {"criterion": r.criterion, "skipped": r.skipped, "note": r.note})
    return {"ok": True}


@app.get("/skips/{pid}")
def skips_ep(pid: str): return store.skips(pid)


@app.post("/finish/{pid}")
def finish(pid: str):
    cfg = criteria.load()
    miss = synth.missing_required(pid) if cfg.get("gate", True) else []
    conf = factcheck.gate(pid, spans_of(pid)) if cfg.get("fact_gate", True) else []
    if miss or conf:
        store.log(pid, "finish_blocked", {"missing": [m["id"] for m in miss], "conflicts": [c["key"] for c in conf]})
        return {"ok": False, "missing": miss, "conflicts": conf}
    store.log(pid, "review_finished", {"venue": cfg.get("venue"), "version": cfg.get("version")})
    return {"ok": True, "missing": [], "conflicts": []}


@app.get("/brief/{pid}")
def get_brief(pid: str): return store.brief(pid)


@app.post("/brief")
def post_brief(r: BriefReq):
    cur = store.brief(r.paper_id)
    if cur and not r.force:
        return cur
    b = brief_mod.build(spans_of(r.paper_id))
    store.log(r.paper_id, "brief_generated", b)
    return b


@app.post("/select")
def select(r: Select):
    path = f"{DATA_DIR}/{r.paper_id}.pdf"
    spans = spans_of(r.paper_id)
    x0, y0, x1, y1 = r.rect
    page = pymupdf.open(path)[r.page - 1]
    text = " ".join(page.get_text("text", clip=pymupdf.Rect(x0, y0, x1, y1)).split())
    near = [s for s in spans if s["page"] == r.page and s["kind"] != "added"
            and s["bbox"][0] < x1 and s["bbox"][2] > x0 and s["bbox"][1] < y1 and s["bbox"][3] > y0]
    if len(text) < 3:
        return {"kind": "region"}
    for s in spans:
        if s.get("kind") == "added" and s["page"] == r.page and ingest.norm(s["text"]) == ingest.norm(text):
            return {"kind": "span", "span": s}
    hit = ingest.add_span(path, r.page, text, len(spans))
    if hit:
        spans.append(hit)
        store.log(r.paper_id, "span_added", hit)
        return {"kind": "span", "span": hit}
    if near:
        return {"kind": "span", "span": near[0]}
    return {"kind": "region"}


@app.post("/explain_spans")
def explain_spans(r: ExplainSpans):
    by = {s["id"]: s for s in spans_of(r.paper_id)}
    sec = [by[i] for i in r.span_ids if i in by]
    out = llm.explain(sec, r.simpler, pdf_ctx(r.paper_id, sec))
    log_new(r.paper_id, out)
    log_turn(r.paper_id, "", out, "explain", "Selection")
    return out


@app.post("/ask_selection")
def ask_selection(r: SelAsk):
    spans = spans_of(r.paper_id)
    page = pymupdf.open(f"{DATA_DIR}/{r.paper_id}.pdf")[r.page - 1]
    x0, y0, x1, y1 = r.rect
    pix = page.get_pixmap(dpi=150, clip=pymupdf.Rect(x0, y0, x1, y1))
    uri = "data:image/png;base64," + base64.b64encode(pix.tobytes("png")).decode()
    caps = [s for s in spans if s["page"] == r.page and s["kind"] == "caption"]
    more = pointers.retrieve(" ".join(c["text"] for c in caps) + " " + r.question, spans)[:6]
    focus = caps + [s for s in more if s not in caps]
    out = llm.look(r.question, focus, uri, r.page)
    log_turn(r.paper_id, r.question, out, "ask_selection")
    store.log(r.paper_id, "ask_selection", {"page": r.page, "rect": r.rect, "question": r.question,
                                           "declined": bool(out.get("declined"))})
    return out
class Intent(BaseModel):
    paper_id: str; text: str; criterion: str = ""; last_q: str = ""; stage: str = ""

@app.post("/intent")
def intent_ep(r: Intent):
    out = chat.classify(r.text, r.criterion, r.last_q, r.stage)
    store.log(r.paper_id, "intent", {"criterion": r.criterion, "stage": r.stage,
                                     "intent": out["intent"], "via": out.get("via", "model")})
    return out

class OnbAnswer(BaseModel): text: str


def run_onboarding(rid, text=None):
    """Log the reply (if any), then return (next step, conflict). All rules live in onboarding.py.

    conflict is True when a reply arrives while no question is pending and onboarding is still open, which
    means the client never fetched the first question. Nothing is logged then: the step returned is the
    question a GET would return, so the reply is refused loudly instead of being silently dropped."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", rid):
        raise HTTPException(400, "reviewer id must be 1-64 letters, digits, - or _")
    key = store.reviewer_key(rid)
    st = store.onboarding(rid)
    if text is not None and st["pending"] is None and not st["closed"]:
        _, step = onboarding.next_step(st, rid)  # the events are discarded: a 409 changes nothing
        step["profile"] = onboarding.profile_view(st)
        step["error"] = "no_question_pending"
        step["message"] = "No question has been fetched yet. GET /onboarding/{rid} first, then answer the question it returns."
        step["ack"] = ""
        return step, True
    ack = ""
    if text is not None:
        answered = onboarding.process(st, text, onboarding.model_on_topic)
        for e in answered:
            store.log(key, e["type"], e["payload"])
        outcome = next((e["payload"].get("outcome") for e in answered if e["type"] == "onboarding_answered"), None)
        if outcome == "answered":
            # A brief neutral acknowledgement, shown before the next question, only for a real answer: never after a
            # skip, or an off-topic reply that earned a follow-up. Plain words from a varied pool; it never repeats or
            # rates what the reviewer said.
            ack = chatflow.onboarding_ack("answered", text.strip(), False, st["turn"])
        st = store.onboarding(rid)
    evs, step = onboarding.next_step(st, rid)
    for e in evs:
        store.log(key, e["type"], e["payload"])
    step["profile"] = onboarding.profile_view(store.onboarding(rid))
    step["ack"] = ack
    return step, False


@app.get("/onboarding/{rid}")
def onboarding_step(rid: str):
    """The current onboarding question (repeated, not advanced, if already pending), or done."""
    return run_onboarding(rid)[0]


@app.post("/onboarding/{rid}/answer")
def onboarding_answer(rid: str, r: OnbAnswer):
    """Record the reply to the pending question and return the next step.

    409, with the current question in the body, if no question had been fetched yet."""
    step, conflict = run_onboarding(rid, r.text)
    return JSONResponse(step, status_code=409) if conflict else step


@app.get("/profile/{rid}")
def profile_ep(rid: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", rid):
        raise HTTPException(400, "reviewer id must be 1-64 letters, digits, - or _")
    return onboarding.profile_view(store.onboarding(rid))


FLOWS = ("chat", "guided")


def flow_mode():
    """Which flow this backend serves: "chat" (default, POST /chat) or "guided" (the old part-by-part flow).
    Set COPILOT_FLOW=guided to turn /chat off. The old flow's endpoints are always registered and unchanged;
    the frontend picks its own flow with ?mode=guided."""
    m = os.environ.get("COPILOT_FLOW", "chat").strip().lower()
    if m not in FLOWS:
        logging.getLogger("copilot").warning("COPILOT_FLOW=%r is not one of %s; using 'chat'", m, FLOWS)
        return "chat"
    return m


@app.get("/config")
def config_ep():
    return {"flow": flow_mode(), "chat_enabled": flow_mode() == "chat", "modes": list(FLOWS), "boot_id": fresh.BOOT_ID}


class ChatReq(BaseModel): reviewer_id: str; message: str = Field(min_length=1, max_length=20000)


def have_paper(pid):
    return pid in CACHE or os.path.exists(f"{DATA_DIR}/{pid}.pdf")


@app.post("/chat/{pid}")
def chat_ep(pid: str, r: ChatReq):
    """Chat-first: one message in, one free-form reply out (onboarding first, then conversation)."""
    if flow_mode() != "chat":
        return JSONResponse({"error": "chat_disabled", "flow": flow_mode(),
                             "message": "This backend is serving the old guided flow (COPILOT_FLOW=guided)."},
                            status_code=409)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", r.reviewer_id):
        raise HTTPException(400, "reviewer id must be 1-64 letters, digits, - or _")
    if not have_paper(pid):
        raise HTTPException(404, "unknown paper")
    return chatflow.turn(pid, r.reviewer_id, r.message, spans_of(pid))


class OpenReq(BaseModel): reviewer_id: str


@app.post("/chat/{pid}/open")
def chat_open_ep(pid: str, r: OpenReq):
    """The app starts the conversation once a paper is attached and onboarding is closed (see chatflow.open_turn).
    Safe to call again (a reload): it then returns opened=false and nothing new."""
    if flow_mode() != "chat":
        return JSONResponse({"error": "chat_disabled", "flow": flow_mode()}, status_code=409)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", r.reviewer_id):
        raise HTTPException(400, "reviewer id must be 1-64 letters, digits, - or _")
    if not have_paper(pid):
        raise HTTPException(404, "unknown paper")
    return chatflow.open_turn(pid, r.reviewer_id, spans_of(pid))


class Hl(BaseModel): paper_id: str
class Bear(BaseModel): paper_id: str; criterion: str; text: str


@app.post("/help/highlights")
def help_highlights(r: Hl):
    return {"items": helper.highlights(r.paper_id, spans_of(r.paper_id))}


@app.post("/help/bear")
def help_bear(r: Bear):
    c = criteria.by_id().get(r.criterion)
    if not c:
        raise HTTPException(400, "unknown criterion")
    return {"facts": helper.bear(r.paper_id, spans_of(r.paper_id), c["name"], r.text)}

class Plan(BaseModel): paper_id: str; criterion: str; text: str


@app.post("/help/plan")
def help_plan(r: Plan):
    c = criteria.by_id().get(r.criterion)
    if not c:
        raise HTTPException(400, "unknown criterion")
    out = helper.plan(c["name"], r.text, walk(r.paper_id))
    store.log(r.paper_id, "plan", {"criterion": r.criterion, **out})
    return out