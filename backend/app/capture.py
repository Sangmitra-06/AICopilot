"""Honesty about captures.

The assistant must never say a view was added to the review draft unless the backend actually wrote it. A reply
can only claim that when the app recorded a capture this turn. Otherwise sentences that claim it ("Added to
Soundness, in your words"), or offer it without an offer behind them ("Want me to add that?"), are removed.

When a reply carries no structured fields, a view found by the extraction call is offered in the app's own wording
(offer_line), never the model's; nothing is written until the reviewer says yes, as for any offer.
Pure functions: no model calls, no event log.
"""
import json
import re

from . import nudges

NOT_ADDED = "I haven't added anything to your draft."
OK = "Understood."

# Past / perfect forms ("added", "I've saved", "has been noted") and state ("it's now in your draft").
DONE = r"(?:added|saved|captured|recorded|logged|filed|stored|put|placed|noted|written|included|kept)"
BASE = r"(?:add|save|capture|record|put|note|log|file|keep|include|store)"
PREP = r"(?:to|in|into|under|on)"
THAT = r"(?:that|it|this|those|your (?:point|note|comment|view|concern|words?|observation))"
# Saying that something is only an option, not a fact.
OFFER_FRAME = re.compile(
    r"\b(?:want me to|would you like me to|do you want me to|should i|shall i|can i|may i|i can|i could|"
    r"i(?:'|’)d be happy to|happy to|let me know|if you(?:'d)? (?:like|want|prefer)|if you say|just say|"
    r"i(?:'|’)m able to)\b", re.I)


def destination(sections):
    """A regex for 'where the reviewer's draft lives': the draft itself, or one of the form's sections by name."""
    words = sorted({w for s in sections for w in nudges.section_words(s)}, key=len, reverse=True)
    sec = "|".join(re.escape(w) for w in words)
    return (r"(?:(?:your|the|their)\s+(?:review\s+)?(?:draft|review|notes)\b|\breview draft\b|"
            r"\b(?:" + sec + r")s?\b)")


def patterns(sections):
    dest = destination(sections)
    claim = [
        # "Added to Soundness", "I've saved that in your draft", "noted under weaknesses"
        re.compile(r"\b" + DONE + r"\b[^.?!\n]{0,70}?\b" + PREP + r"\b[^.?!\n]{0,50}?" + dest, re.I),
        # "That's in your draft", "It's now under Weaknesses". (A bare "it's in the summary" is not enough: that can be
        # about the paper, so a section name needs "now" or "already", or the draft itself must be named.)
        re.compile(r"\b(?:that(?:'|’)?s|it(?:'|’)?s|that is|it is|those are)\s+(?:now\s+|already\s+)?"
                   r"(?:in|under|on)\s+(?:your|the|their)\s+(?:review\s+)?(?:draft|notes)\b", re.I),
        re.compile(r"\b(?:that(?:'|’)?s|it(?:'|’)?s|that is|it is|those are)\s+(?:now|already)\s+"
                   r"(?:in|under|on)\s+(?:[^.?!\n]{0,30}?)" + dest, re.I),
        # "I'm adding that", "I'll add that to your draft", "I will save it"
        re.compile(r"\bi(?:'|’)?m\s+(?:now\s+)?(?:adding|saving|capturing|recording|putting|noting|logging|filing)\b"
                   r"|\bi(?:'|’)ll\s+(?:go ahead and\s+)?" + BASE + r"\b[^.?!\n]{0,40}?" + dest
                   + r"|\bi will\s+(?:go ahead and\s+)?" + BASE + r"\b[^.?!\n]{0,40}?" + dest, re.I),
        # "has been added", "have been saved to ..."
        re.compile(r"\b(?:has|have)\s+been\s+" + DONE + r"\b", re.I),
        # "I've added that" with no destination at all
        re.compile(r"\bi(?:'|’)ve\s+(?:just\s+)?" + DONE + r"\s+" + THAT + r"\b", re.I),
    ]
    offer = re.compile(r"\b" + BASE + r"\s+" + THAT + r"\b[^.?!\n]{0,60}?" + dest, re.I)
    return claim, offer


NEGATED = re.compile(r"\b(?:not|never|nothing|none)\b|n(?:'|’)t\b", re.I)
ABOUT_THE_PAPER = re.compile(r"\b(?:authors?|paper|they|their|study)\b", re.I)
SPEAKER = re.compile(r"\b(?:i|i(?:'|’)(?:ve|ll|m)|you|your|you(?:'|’)ve)\b", re.I)


def classify(sentence, claim, offer):
    """'claim', 'offer' or None for one sentence. A claim is the assistant saying something was added to the draft:
    not a negation ("I haven't added anything"), and not a sentence about the paper ("The authors added ...")."""
    s = sentence.strip()
    if not s:
        return None
    asked = s.endswith("?") or bool(OFFER_FRAME.search(s))
    about_paper = bool(ABOUT_THE_PAPER.search(s)) and not SPEAKER.search(s)
    if not asked and not NEGATED.search(s) and not about_paper and any(p.search(s) for p in claim):
        return "claim"
    if asked and offer.search(s):
        return "offer"
    return None


SPLIT = re.compile(r"((?<=[.!?])\s+|\n+)")


def scrub(reply, sections, claims_ok=False, offers_ok=False, empty_line=OK):
    """Remove capture claims (unless the backend recorded a capture this turn) and unbacked offers (unless an offer
    was registered this turn). Returns (text, removed sentences). Everything else is left exactly as written."""
    claim, offer = patterns(sections)
    parts = SPLIT.split(reply)
    kept, removed = [], []
    for i in range(0, len(parts), 2):
        sent, sep = parts[i], parts[i + 1] if i + 1 < len(parts) else ""
        kind = classify(sent, claim, offer)
        if (kind == "claim" and not claims_ok) or (kind == "offer" and not offers_ok):
            removed.append(sent.strip())
            continue
        kept.append(sent + sep)
    text = "".join(kept).strip()
    return (text or empty_line if removed else text), removed


def offer_line(label, text=None):
    """The app's own words for offering a capture (never the model's): "Want me to add that to Summary of
    weaknesses?". `label` is the section's name ("" = not placed in a section). The reviewer's words are quoted only
    when several views were found, so "that" is unambiguous otherwise."""
    where = label or "your draft"
    return f"Want me to add that to {where}?" if text is None else f"Want me to add “{text}” to {where}?"


# ------------------------------------------------------------------ reading the extraction call

LINE = re.compile(r"^\s*(?:[-*•]\s*)?VIEW\s*\|\s*([A-Za-z0-9_ -]*?)\s*\|\s*(.+?)\s*$", re.I)


def parse_views(raw):
    """[{text, section}] from the extraction call's output. The line form ("VIEW | weaknesses | their words") is
    what the prompt asks for; a JSON object or list with "views" is accepted too. Anything else is no views."""
    text = raw.strip() if isinstance(raw, str) else ""
    if not text or re.fullmatch(r"\W*none\W*", text, re.I):
        return []
    found = []
    for line in text.splitlines():
        m = LINE.match(line)
        if m:
            found.append({"section": m.group(1).strip(), "text": m.group(2).strip().strip("\"'“”")})
    if found:
        return found
    decoder = json.JSONDecoder()
    for m in re.finditer(r"[\[{]", text):
        try:
            j, _ = decoder.raw_decode(text, m.start())
        except ValueError:
            continue
        views = j.get("views") if isinstance(j, dict) else j if isinstance(j, list) else None
        if isinstance(views, list):
            return [v for v in views if isinstance(v, dict) and v.get("text")]
    return []
