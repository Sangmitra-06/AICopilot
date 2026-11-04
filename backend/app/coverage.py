"""What the REVIEW has and lacks. Pure functions over a plain "review state" dict; nothing here looks at, or
says anything about, the quality of the paper.

review state (built by chatflow.review_state):
  sections : [{"id", "name", "required", "type"}]            the venue's form, in order
  addressed: {section id: bool}                              has content (or a score), or was skipped
  skipped  : {section id: bool}
  notes    : [{"key", "field", "text", "cited": bool}]       the reviewer's content, with whether it points at the paper
  views    : {view id: {"text", "section", "outcome"}}       things they said in chat; outcome is accepted/rejected/None
  promised : [section id]                                    sections they said they would cover
  titles   : [paper section titles]                          to recognise "see Related Work" as a citation
"""
import re

CITE = re.compile(r"(?:\b(?:sections?|sec\.?|tables?|figures?|figs?\.?|appendix|appendices|pages?|lines?|"
                  r"algorithm|equations?|eq\.?)\s*[A-Z]?\d+|§\s*\d+|"
                  r"\b(?:the )?(?:abstract|introduction|conclusions?|related work)\b)", re.I)
CITING = {"weaknesses"}  # form sections whose points should say where in the paper they come from


def cites(text, span_ids=(), titles=()):
    """Does a note point at a place in the paper? Span ids from the reader, a numbered reference, or a
    section title all count."""
    low = (text or "").lower()
    return bool(span_ids) or bool(CITE.search(text or "")) or any(
        len(t) >= 5 and t in low for t in (re.sub(r"^[\dA-Z.]+\s+", "", x).lower() for x in titles))


def word_set(text):
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def in_draft(text, notes):
    """Is what the reviewer said already in their draft (nearly all of its words appear in one note)?"""
    w = word_set(text)
    return bool(w) and any(len(w & word_set(n["text"])) / len(w) >= 0.8 for n in notes)


def label(rs, sid):
    return next((s["name"] for s in rs["sections"] if s["id"] == sid), sid)


def gap_report(rs):
    """Everything open in the review, at once. Four kinds, all about the review."""
    secs = rs["sections"]
    open_ = [s for s in secs if not rs["addressed"].get(s["id"])]
    uncited = [{"key": n["key"], "text": n["text"], "section": n["field"], "label": label(rs, n["field"])}
               for n in rs["notes"] if n["field"] in CITING and not n["cited"]]
    uncaptured = [{"vid": vid, "text": v["text"], "section": v["section"]}
                  for vid, v in rs["views"].items()
                  if v["outcome"] not in ("accepted", "rejected") and not in_draft(v["text"], rs["notes"])]
    promised = [{"section": sid, "label": label(rs, sid)} for sid in rs["promised"]
                if not rs["addressed"].get(sid)]
    return {"required_open": [{"id": s["id"], "label": s["name"]} for s in open_ if s["required"]],
            "optional_open": [{"id": s["id"], "label": s["name"]} for s in open_ if not s["required"]],
            "uncited": uncited, "uncaptured": uncaptured, "promised": promised}


def is_empty(report):
    return not any(report[k] for k in ("required_open", "optional_open", "uncited", "uncaptured", "promised"))


OPENERS = ["Here's what's open in your review right now.",
           "Going through your review, this is what I see still open.",
           "These are the open items in your review so far."]
NOTHING = ("Nothing is open right now: every required part has something in it, and I don't see anything you "
           "said that is missing from the draft.")


def gap_text(report, variant=0):
    """The gap report as chat text. Labels and the reviewer's own quoted words only."""
    if is_empty(report):
        return NOTHING
    out = [OPENERS[variant % len(OPENERS)]]
    if report["required_open"]:
        out.append("- Required, nothing in it yet: " + ", ".join(g["label"] for g in report["required_open"]) + ".")
    if report["optional_open"]:
        out.append("- Optional, nothing in it yet: " + ", ".join(g["label"] for g in report["optional_open"]) + ".")
    for g in report["uncited"]:
        out.append(f"- Under {g['label']}, “{g['text']}” doesn't point to a section, table or figure of the paper.")
    for g in report["uncaptured"]:
        out.append(f"- You said “{g['text']}” earlier; it isn't in your draft.")
    for g in report["promised"]:
        out.append(f"- You mentioned you would cover {g['label']}; nothing is there yet.")
    return "\n".join(out)
