import os, re, json, base64
import pymupdf
from dotenv import load_dotenv
from openai import OpenAI
from .schemas import Explanation
from .verify import verify, norm
from .ingest import locate, add_span, page_plain, norm as inorm

load_dotenv()
client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENROUTER_API_KEY"])
MODEL = os.environ["MODEL"]
USE_PDF = os.environ.get("USE_PDF", "1") == "1"
IMG = {}

EXPLAIN_SYS = """You explain a research paper to a reviewer. You never judge it.
You get the paper's text as labeled spans, and also images of its pages.
Return JSON: {"sentences":[{"text":str,"kind":"paper"|"authors_claim"|"background","source":"text"|"pdf"|"image","span_ids":[str],"quote":str|null,"page":int|null}]}
Rules:
1. kind "paper": something the paper states or does. kind "authors_claim": the authors' own framing, phrased as "The authors say/argue/attribute...". kind "background": a plain textbook definition not from the paper, with source "text", no span_ids, no quote.
2. source "text" (use whenever a provided span covers it): cite span_ids and give a quote, the shortest exact snippet (under 20 words) copied from a cited span. Every number in the sentence must appear in a cited span.
3. source "pdf": only when the answer is on the page images but in none of the spans (tables, figure labels, text the extraction missed). Give "page" and a "quote": the exact words as printed on that page (under 20 words). span_ids stay empty. Every number in the sentence must appear in the quote.
4. source "image": only for things that exist purely as a picture (bar heights, curves, map shading). Give "page", no quote, and say which figure it is. Use sparingly.
5. Follow the paper's own order. Do not choose what matters. Never use evaluative words (key, important, strong, weak, novel, convincing...). Never say what is missing, flawed, or good.
6. Plain language, short sentences. Do not write line numbers, span ids, or section numbers in the text; the interface adds them.
7. When answering a question, include only sentences that answer it. No extra context.
If the question cannot be answered from the spans or pages, return {"sentences":[]}."""

JUDGE = re.compile(r"\b(good|bad|solid|sound|convincing|valid|fair|worth|important|weak|strong|"
                   r"flawed|accept|reject|novel|should i)\b", re.I)


def _chat(msgs):
    r = client.chat.completions.create(model=MODEL, messages=msgs,
                                       response_format={"type": "json_object"}, temperature=0.2)
    return r.choices[0].message.content


def ctx(spans):
    return "\n".join(f"[{s['id']}] (lines {s['lines'][0]}-{s['lines'][1]}) {s['text']}" if s["lines"]
                     else f"[{s['id']}] {s['text']}" for s in spans)


def page_images(path, pages):
    doc, out = pymupdf.open(path), []
    for p in pages:
        if (path, p) not in IMG:
            png = doc[p - 1].get_pixmap(dpi=100).tobytes("png")
            IMG[(path, p)] = "data:image/png;base64," + base64.b64encode(png).decode()
        out.append((p, IMG[(path, p)]))
    return out


def build_user(text, pdf, extra=None):
    use_pdf = bool(USE_PDF and pdf and pdf.get("pages"))
    if not use_pdf and not extra:
        return text
    parts = [{"type": "text", "text": text}]
    for label, uri in (extra or []):
        parts.append({"type": "text", "text": label})
        parts.append({"type": "image_url", "image_url": {"url": uri}})
    if use_pdf:
        parts.append({"type": "text", "text": "The following images are pages of the paper."})
        for p, uri in page_images(pdf["path"], pdf["pages"]):
            parts.append({"type": "text", "text": f"[page {p}]"})
            parts.append({"type": "image_url", "image_url": {"url": uri}})
    return parts


def _pn(path):
    def f(p):
        try:
            return norm(page_plain(path, int(p)))
        except Exception:
            return ""
    return f


def finish(exp, by_id, pdf):
    out, new = exp.model_dump(), []
    store = pdf["store"] if pdf else []
    for s in out["sentences"]:
        s["lines"], s["precise"] = None, False
        if s["source"] == "image":
            continue
        if s["source"] == "pdf" and pdf:
            hit = next((x for x in store if x.get("kind") == "added" and x["page"] == s["page"]
                        and inorm(x["text"]) == inorm(s["quote"])), None)
            if not hit:
                hit = add_span(pdf["path"], s["page"], s["quote"], len(store))
                if hit:
                    store.append(hit); new.append(hit)
            if hit:
                s["span_ids"], s["lines"], s["precise"] = [hit["id"]], hit["lines"], bool(hit["lines"])
            continue
        ids = [i for i in s["span_ids"] if i in by_id]
        if not ids:
            continue
        s["page"] = by_id[ids[0]]["page"]
        loc = None
        for i in ids:
            loc = locate(by_id[i], s["quote"]) if s.get("quote") else None
            if loc:
                break
        s["precise"] = bool(loc)
        if not loc:
            los = [by_id[i]["lines"] for i in ids if by_id[i]["lines"]]
            loc = [min(l[0] for l in los), max(l[1] for l in los)] if los else None
        s["lines"] = loc
    out["new_spans"] = new
    return out


def _run(user, spans, pdf=None, tries=3, extra=None):
    by_id = {s["id"]: s for s in spans}
    pn = _pn(pdf["path"]) if (pdf and USE_PDF) else None
    msgs = [{"role": "system", "content": EXPLAIN_SYS},
            {"role": "user", "content": build_user(user, pdf if USE_PDF else None, extra)}]
    for _ in range(tries):
        raw = _chat(msgs)
        try:
            exp = Explanation.model_validate_json(raw)
            errs = verify(exp, by_id, pn)
        except Exception as e:
            errs = [f"invalid JSON or schema: {e}"]
        if not errs:
            return finish(exp, by_id, pdf if USE_PDF else None)
        print("[explain] retry:", errs[:3])
        msgs += [{"role": "assistant", "content": raw},
                 {"role": "user", "content": "Fix these and return the full JSON again:\n" + "\n".join(errs)}]
    raise ValueError("could not produce a verified answer")


def hist_text(history):
    rows = []
    for h in (history or [])[-6:]:
        who = "Reviewer" if h.get("role") == "user" else "Assistant"
        rows.append(f"{who}: {str(h.get('text', ''))[:600]}")
    return "\n".join(rows)


def explain(spans, simpler=False, pdf=None):
    return _run(("Use simpler words.\n" if simpler else "") + "Walk through this section:\n" + ctx(spans),
                spans, pdf)


def ask(question, spans, pdf=None, context="", history=None):
    if JUDGE.search(question):
        return {"declined": True, "message": "That's a judgment call, so it stays with you. "
                "I can show what they did and where. What's your take?"}
    extra = f'\nThe reviewer is asking about this earlier sentence: "{context}"' if context else ""
    h = hist_text(history)
    hh = ("\nEarlier in this conversation (context only; answer from the spans, not from earlier answers):\n" + h) if h else ""
    return _run(f"Question: {question}{extra}{hh}\nSpans:\n{ctx(spans)}", spans, pdf)


def look(question, spans, extra, page):
    if JUDGE.search(question):
        return {"declined": True, "message": "That's a judgment call, so it stays with you. "
                "I can show what they did and where. What's your take?"}
    user = (f"Question: {question}\n"
            f"The first image is the area the reviewer selected on page {page}. "
            "Describe what it shows (what is plotted or listed, labels, legend, categories) and answer the question. "
            "Describe only. Do not interpret or judge. "
            f"For anything you read from the picture, use source \"image\" with page {page} and name the figure or table. "
            "If a provided span (such as the caption) says something relevant, use source \"text\" with that span and a quote.\n"
            f"Spans:\n{ctx(spans)}")
    return _run(user, spans, None, extra=[("[selected area]", extra)])


CHECK_SYS = """A reviewer wrote what they understood about part of a paper. Compare ONLY factual claims
about what the paper states or did (numbers, datasets, methods, what was compared). Ignore opinions,
emphasis, wording, and evaluations. Return {"mismatches":[{"claim":str,"span_id":str,"paper_quote":str,"why":str}]}.
paper_quote must be copied exactly from the span. If nothing contradicts the paper, return {"mismatches":[]}."""


def teachback(text, spans):
    by_id = {s["id"]: s for s in spans}
    raw = _chat([{"role": "system", "content": CHECK_SYS},
                 {"role": "user", "content": f"Reviewer wrote:\n{text}\n\nSpans:\n{ctx(spans)}"}])
    out = json.loads(raw).get("mismatches", [])
    return [m for m in out if m.get("span_id") in by_id and norm(m.get("paper_quote", "")) in norm(by_id[m["span_id"]]["text"])]