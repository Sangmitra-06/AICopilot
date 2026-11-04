"""The silent coverage map and guided nudges.

A nudge is a plain statement about the REVIEW plus one light prompt toward the next uncovered section. It never
says what belongs in a section and never says anything about the paper. What to nudge toward, whether this is a
moment for one, and whether one is allowed at all are decided here, in code, from the event log. The model only
phrases it, from a directive built out of the reviewer's own words (nudge_note).
"""
import re

from .coverage import CITING

SYNONYMS = {"summary": ["summary", "summarize", "summarise"], "strengths": ["strength", "strengths", "pros"],
            "weaknesses": ["weakness", "weaknesses", "concerns", "cons"],
            "comments": ["comments", "typos", "suggestions"], "soundness": ["soundness"],
            "excitement": ["excitement"], "overall": ["overall", "score", "scores", "recommendation"],
            "confidence": ["confidence"], "reproducibility": ["reproducibility", "reproduce"],
            "ethics": ["ethics", "ethical"]}
STOP = {"summary", "paper", "comments", "suggestions", "assessment", "concerns", "and", "the", "of"}


def section_words(section):
    """Words that name a review-form section: its id, the long-enough words of its label, known synonyms."""
    words = {section["id"].lower()} | {w for w in re.findall(r"[a-z]+", section["name"].lower())
                                       if len(w) > 3 and w not in STOP}
    return words | set(SYNONYMS.get(section["id"], []))


def mentions(text, sections):
    """Ids of the sections a piece of text talks about (whole words, plural allowed)."""
    low = (text or "").lower()
    return [s["id"] for s in sections
            if any(re.search(r"\b" + re.escape(w) + r"s?\b", low) for w in section_words(s))]


FUTURE = re.compile(r"\b(?:i(?:'|’)?ll|i will|i(?:'|’)?m going to|i am going to|going to|i(?:'|’)?m gonna|"
                    r"i need to|i have to|i want to|i plan to|i should|let me|later|come back to|get to)\b", re.I)
ACTION = re.compile(r"\b(?:cover|write|add|fill|discuss|talk about|get to|come back to|work on|handle|draft|"
                    r"put together|address|do)\b", re.I)


def promises(message, sections):
    """Sections the reviewer said they would cover ("I'll cover the ethics part later")."""
    out = []
    for sent in re.split(r"(?<=[.!?])\s+|\n+", message or ""):
        if FUTURE.search(sent) and ACTION.search(sent):
            out += [sid for sid in mentions(sent, sections) if sid not in out]
    return out


NOT_NOW = re.compile(r"\b(?:not now|not yet|maybe later|later|leave (?:it|that)|skip (?:it|that|this)|no thanks|"
                     r"not (?:right )?now|drop it|don(?:'|’)?t (?:bother|worry) about (?:it|that))\b", re.I)

# reading_order -> the order in which a reviewer who reads this way arrives at the form's sections. A section is
# placed by the part of the paper it most naturally follows; data, not judgment. Unknown ids go last.
PHASE_OF = {"summary": "abstract", "soundness": "method", "reproducibility": "method",
            "strengths": "results", "weaknesses": "results", "excitement": "conclusion", "ethics": "conclusion"}
_STD = ["abstract", "intro", "method", "results", "conclusion"]
SEQUENCES = {
    "abstract_first": _STD, "intro_first": _STD, "in_order": _STD, "paper_order": _STD, "skim_first": _STD,
    "methods_first": ["method", "results", "abstract", "intro", "conclusion"],
    "results_first": ["results", "method", "abstract", "intro", "conclusion"],
    "figures_first": ["results", "abstract", "method", "intro", "conclusion"],
    "conclusion_first": ["conclusion", "abstract", "intro", "method", "results"],
}
MAX_OFFERS = 3  # a section is nudged at most this many times in all, even if the reviewer engages each time


def rank(section_id, reading_order):
    seq = SEQUENCES.get(reading_order, SEQUENCES["paper_order"])
    phase = PHASE_OF.get(section_id)
    return seq.index(phase) if phase in seq else len(seq)


def candidates(rs):
    """The coverage map, as nudgeable gaps in the review: promised-but-empty, empty, or content that cites nothing."""
    out = []
    for i, s in enumerate(rs["sections"]):
        sid = s["id"]
        if rs["skipped"].get(sid):
            continue
        if not rs["addressed"].get(sid):
            kind = "promised" if sid in rs["promised"] else "empty"
            out.append({"section": sid, "label": s["name"], "kind": kind, "index": i, "text": None})
        else:
            unc = [n for n in rs["notes"] if n["field"] == sid and sid in CITING and not n["cited"]]
            if unc:
                out.append({"section": sid, "label": s["name"], "kind": "uncited", "index": i, "text": unc[0]["text"]})
    return out


def statement(c):
    """The nudge's statement. About the review only; the reviewer's own words are quoted."""
    if c["kind"] == "promised":
        return f"You mentioned you would cover {c['label']}; nothing is there yet."
    if c["kind"] == "uncited":
        return f"Under {c['label']}, “{c['text']}” doesn't point to a section of the paper yet."
    return f"Your draft has nothing under {c['label']} yet."


def pick_nudge(rs, reading_order, hardest_part, nudges):
    """The one section to nudge toward next, or None. Ordered by the reviewer's reading order, pulled forward
    when they said that section is the hardest part, and when they promised it. Dismissed sections (and ones
    already nudged MAX_OFFERS times) are never chosen."""
    hard = set(mentions(hardest_part, rs["sections"])) if hardest_part else set()
    pool = []
    for c in candidates(rs):
        n = nudges.get(c["section"], {})
        if n.get("dismissed") or n.get("offered", 0) >= MAX_OFFERS:
            continue
        weight = (0 if c["section"] in hard else 1, 0 if c["kind"] == "promised" else 1,
                  rank(c["section"], reading_order), c["index"])
        pool.append((weight, c))
    if not pool:
        return None
    _, best = min(pool, key=lambda x: x[0])
    return dict(best, statement=statement(best), hardest=hardest_part if best["section"] in hard else None)


PAUSE = re.compile(r"^\s*(?:ok(?:ay)?|thanks?|thank you|got it|cool|nice|sure|right|alright|yep|yeah|hm+|i see|"
                   r"makes sense|fine|that(?:'|’)?s (?:all|it)|(?:nothing|that(?:'|’)?s all) (?:else|for now)|"
                   r"done(?: with (?:this|that))?|next|continue|go on|what now|what next|anything else)\W*$", re.I)


def natural_pause(message, just_answered_offer=False):
    """Is this a point where a nudge fits: a capture just got answered, a short acknowledgement, or a closing remark?"""
    if just_answered_offer or PAUSE.match(message or ""):
        return True
    words = re.findall(r"[A-Za-z']+", message or "")
    return len(words) <= 3 and "?" not in (message or "")


def nudge_note(c):
    """The directive added to the prompt for this turn: a statement plus one light prompt, in the reviewer's words."""
    note = ("NUDGE (optional): if this is a natural pause, work ONE light nudge about the reviewer's REVIEW into your "
            "reply (as part of what you say, never as a stock closing line). " + f"Say: {c['statement']} "
            f"Then give one light prompt toward {c['label']}.")
    if c.get("hardest"):
        note += f" They told you the hardest part of reviewing is “{c['hardest']}”; you may use their words."
    note += (" Never say what should go in that section, never say it is strong or weak or missing something in the "
             "paper, and never comment on the paper. Skip the nudge if the reviewer is mid-thought, asked you a "
             "question, or you are offering to capture one of their views this turn. Set nudge_used to true only if "
             "you used it.")
    return note
