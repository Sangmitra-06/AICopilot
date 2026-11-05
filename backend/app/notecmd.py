"""Save-then-tell: the reviewer's short commands about the note the app just saved, read by rule.

A statement the reviewer makes about the paper is saved right away, in their exact words, in the best-fitting review-form
section, and the app says so ("Saved under Soundness. Say 'move it' if that's wrong."). These commands then act on it:
  undo                       "undo", "undo that", "take that back", "scratch that"
  move  (to a section)       "move it", "put it in strengths", "I want it to go in the strenghts"
  also  (a second section)   "yeah and also as a strength", "also add it to weaknesses"
  add   (the app's text)     "add the summary", "add all of it", "I want you to add thes ummary"
Pure functions: no model, no store. A long message that happens to contain one of these words is a statement, not a
command, so every command is short. Section names may carry small typos ("strenghts").
"""
import difflib
import re

from . import nudges

APOS = r"['’]?"
LEAD = r"^\W*(?:(?:yeah|yes|yep|ok(?:ay)?|and|so|no|nope|actually|please|hmm|oh|wait|sorry)\W+)*"
IT = r"(?:it|that|this|the (?:note|point|comment|last one))"
MAX_WORDS = 14

UNDO = re.compile(LEAD + r"(?:undo(?: (?:that|it|this|the last (?:one|change)))?|take (?:that|it) back|scratch that|"
                  r"never ?mind,? (?:remove|undo) (?:that|it)|remove (?:that|it) again)\W*(?:please)?\W*$", re.I)
MOVE = re.compile(r"\b(?:move|put|place|file|switch|shift|change|re-?file)\s+" + IT + r"\b|"
                  r"\b(?:want|like|need|meant|mean)\s+(?:it|that|this)\s+(?:to\s+)?(?:go|be|sit)\s+(?:in|into|under|to|as)\b|"
                  r"\b(?:it|that|this)\s+(?:should|must|needs to|has to)\s+(?:go|be)\s+(?:in|into|under|to|as)\b|"
                  r"\bbelongs?\s+(?:in|under|to)\b|\bwrong section\b", re.I)
ALSO = re.compile(r"\b(?:also|too|as well)\b", re.I)
ADD = re.compile(r"\b(?:add|put|save|include|keep|copy|use|paste)\b", re.I)
ALL_OF_IT = re.compile(r"\b(?:all of (?:it|that|this)|it all|the whole (?:thing|summary|paragraph|text)|the rest|"
                       r"everything|the full (?:summary|text|paragraph))\b", re.I)
NEGATED = re.compile(r"\b(?:don" + APOS + r"t|do not|never|not|no need)\s+(?:\w+\s+){0,2}?(?:add|put|save|move)\b", re.I)
QUESTIONISH = re.compile(r"\?\s*$|^\W*(?:what|why|how|when|where|which|who|is|are|does|do|did|can you explain)\b", re.I)


def words(message):
    return re.findall(r"[a-z]+", (message or "").lower())


def short(message):
    return 0 < len(words(message)) <= MAX_WORDS


def section_in(message, sections):
    """The review-form section a message names, or None. A full section name wins, then a section word ("strength",
    "soundness"), then a section word with a small typo ("strenghts"). `sections` is [{id, name}]."""
    low = (message or "").lower()
    full = [(low.rfind(s["name"].lower()), s["id"]) for s in sections if s["name"].lower() in low]
    if full:
        return max(full)[1]
    best = None
    for s in sections:
        for w in nudges.section_words(s):
            for m in re.finditer(r"\b" + re.escape(w) + r"s?\b", low):
                if best is None or m.end() > best[0]:
                    best = (m.end(), s["id"])
    if best:
        return best[1]
    for tok in reversed(words(message)):                  # a typo: closest section word, only for longer words
        if len(tok) < 6:
            continue
        for s in sections:
            for w in nudges.section_words(s):
                if len(w) >= 6 and difflib.SequenceMatcher(None, tok, w).ratio() >= 0.85:
                    return s["id"]
    return None


def wants_summary(message):
    """"add the summary", also with the space in the wrong place ("add thes ummary")."""
    squashed = re.sub(r"[^a-z]", "", (message or "").lower())
    return bool(ADD.search(message or "")) and bool(re.search(r"summar(?:y|ies)", squashed))


# The words a command is made of. A move or "also" message with any other word in it ("I also think the baselines are
# weak as a weakness", "I would put that down to the small dataset") is a statement, not a command.
COMMAND_WORDS = set("""yeah yes yep ok okay and so no nope actually please hmm oh wait sorry i you me my your it that this
the a an one note point comment last to in into under as also too well add put save include keep copy move place file
switch shift change refile re want like need needs meant mean would d rather instead go goes be sit should must has have
belongs belong there section sections part wrong one just now can could let s m not but sure fine lets""".split())
THIRD_PARTY = re.compile(r"\b(?:authors?|they|we|it|paper|study|work)\s+(?:also\s+)?(?:add|adds|added|include|includes|"
                         r"included|use|uses|used|put|puts|save|saves|keep|keeps)\b", re.I)


def only_command_words(message, sections):
    sec_words = {w for s in sections for w in nudges.section_words(s)} | {w + "s" for s in sections
                                                                           for w in nudges.section_words(s)}
    low = (message or "").lower()
    for s in sections:                                          # a full section name ("paper summary") counts as one
        low = low.replace(s["name"].lower(), " ")
    rest = [t for t in words(low) if t not in COMMAND_WORDS and t not in sec_words]
    return all(section_in(t, sections) for t in rest)           # a leftover word may only be a misspelled section name


CORRECTION = re.compile(r"^\W*(?:no|nope|actually|rather|instead|wrong)\b|\b(?:i mean|i meant|instead|rather|"
                        r"not there|wrong section)\b", re.I)
IT_TO = re.compile(r"\b(?:add|put|save|file|place)\s+(?:it|that|this)\s+(?:to|in|into|under)\b", re.I)


def read(message, sections, just_saved=False):
    """("undo",) | ("move", section id or None) | ("also", section id) | ("add", "summary" | "all", section id or None)
    | None when the message is not a short command about notes. `just_saved`: the app's previous turn saved a note, so
    a correction that names a section ("No, I mean strengths", "not there, add it to the comments") moves it, and a
    refusal ("don't add that") undoes it."""
    m = (message or "").strip()
    if not short(m) or QUESTIONISH.search(m):
        return None
    if NEGATED.search(m):
        return ("undo",) if just_saved else None
    if UNDO.match(m):
        return ("undo",)
    sid = section_in(m, sections)
    if just_saved and sid and (CORRECTION.search(m) or IT_TO.search(m)) and only_command_words(m, sections):
        return ("move", sid)
    also = bool(ALSO.search(m) and sid and re.search(r"\b(?:as|to|in|into|under)\b", m, re.I))
    if also and not ALL_OF_IT.search(m) and only_command_words(m, sections):    # "also add it to the summary"
        return ("also", sid)
    if ADD.search(m) and (ALL_OF_IT.search(m) or wants_summary(m)) and not THIRD_PARTY.search(m):
        return ("add", "all" if ALL_OF_IT.search(m) else "summary", sid)     # no section named: Paper summary
    if not only_command_words(m, sections):
        return None
    if MOVE.search(m):
        return ("move", sid)
    return None


# ------------------------------------------------------------------ the app's own lines (the model never writes these)

MOVE_HINT = "Say “move it” if that's wrong."


def saved_line(labels):
    where = " and ".join(labels) if labels else "your draft"
    return f"Saved under {where}. {MOVE_HINT}"


def also_line(label):
    return f"Also saved under {label}."


def moved_line(label):
    return f"Moved to {label}."


def where_line(names):
    return "Which section should it go under? " + ", ".join(names) + "."


def proposal_line(label):
    return f"Added to {label}, marked as drafted from the paper's claims."


def already_line(label):
    return f"That's already under {label}, marked as drafted from the paper's claims."


NOTHING_TO_ADD = "I haven't written a summary or other text in this conversation that I could add."
NOTHING_SAVED = "There's no note from this conversation for that to apply to yet."
CLAIMS_LABEL = "Drafted from the paper's claims"


def undo_line(kind, label):
    if kind == "moved":
        return f"Undone: it's back under {label}."
    return f"Undone: I removed it from {label}."
