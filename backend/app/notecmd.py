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


def only_command_words(message, sections, extra=frozenset()):
    sec_words = {w for s in sections for w in nudges.section_words(s)} | {w + "s" for s in sections
                                                                           for w in nudges.section_words(s)}
    low = (message or "").lower()
    for s in sections:                                          # a full section name ("paper summary") counts as one
        low = low.replace(s["name"].lower(), " ")
    rest = [t for t in words(low) if t not in COMMAND_WORDS and t not in extra and t not in sec_words]
    return all(section_in(t, sections) for t in rest)           # a leftover word may only be a misspelled section name


# Approving the text the app just proposed ("add it", "this is good add it to the draft", "you can add the draft as is").
APPROVE = re.compile(r"\b(?:add|put|save|include|use|paste|keep|take)\s+(?:it|that|this|them|(?:the|your|this|that)\s+"
                     r"(?:draft|line|text|sentence|paragraph|proposal|suggestion|version|wording|one))\b", re.I)
APPROVAL_WORDS = frozenset("""good great fine perfect nice looks look is as can could you draft review works thanks thank
exactly love go ahead them line text sentence paragraph proposal suggestion version wording""".split())


CORRECTION = re.compile(r"^\W*(?:no|nope|not|actually|rather|instead|wrong)\b|\b(?:i mean|i meant|instead|rather|"
                        r"not there|wrong section)\b", re.I)
IT_TO = re.compile(r"\b(?:add|put|save|file|place)\s+(?:it|that|this)\s+(?:to|in|into|under)\b", re.I)
# "not under summary, under strengths": the section after "not" is where it should NOT go.
NOT_THERE = re.compile(r"\bnot\s+(?:(?:under|in|into|as|to)\s+)?[^,;]*?(?=\s(?:under|in|into|to|as|but)\b|[,;]|$)", re.I)
# Where an approving clause may start inside a longer reply: "no it doesnt lets add that to strenghts".
APPROVE_START = re.compile(r"(?:^|[,.;:!]|\b(?:let(?:['’]?s| us)|please|so|then|just|ok(?:ay)?|yes|yeah|but|and)\b)\s*"
                           r"(?=(?:add|put|save|include|use|paste|keep|take)\b)", re.I)


def target_in(message, sections):
    """The section a message sends a note to, leaving out the one after "not" ("not under suimmary under strenghts")."""
    return section_in(NOT_THERE.sub(" ", message or ""), sections)


def approval_tail(message, sections):
    """The approving clause that ends a message ("lets add that to strenghts"), or None."""
    for at in reversed([m.end() for m in APPROVE_START.finditer(message or "")]):
        tail = message[at:]
        if APPROVE.match(tail) and not THIRD_PARTY.search(tail) and not ALL_OF_IT.search(tail) \
                and not wants_summary(tail) and only_command_words(tail, sections, APPROVAL_WORDS):
            return tail
    return None


def read(message, sections, just_saved=False, proposed=False):
    """("undo",) | ("move", section id or None) | ("also", section id) | ("add", "summary" | "all" | "proposed",
    section id or None) | None when the message is not a short command about notes. `just_saved`: the app's previous turn
    saved a note, so a correction that names a section ("No, I mean strengths", "not there, add it to the comments")
    moves it, and a refusal ("don't add that") undoes it. `proposed`: the app's previous turn proposed a text, so "add it"
    / "this is good add it to the draft" / "you can add the draft as is" approves exactly that text."""
    m = (message or "").strip()
    if not short(m) or QUESTIONISH.search(m):
        return None
    if NEGATED.search(m):
        return ("undo",) if just_saved else None
    if UNDO.match(m):
        return ("undo",)
    approve = bool(APPROVE.search(m)) and not THIRD_PARTY.search(m) and not ALL_OF_IT.search(m) \
        and not wants_summary(m) and only_command_words(m, sections, APPROVAL_WORDS)
    if approve and proposed and not CORRECTION.search(m):
        return ("add", "proposed", target_in(m, sections))
    tail = approval_tail(m, sections) if proposed and not approve else None
    if tail:                                                 # "no it doesnt lets add that to strenghts"
        return ("add", "proposed", target_in(tail, sections))
    sid = target_in(m, sections)
    if just_saved and sid and (CORRECTION.search(m) or IT_TO.search(m)) and only_command_words(m, sections):
        return ("move", sid)
    also = bool(ALSO.search(m) and sid and re.search(r"\b(?:as|to|in|into|under)\b", m, re.I))
    if also and not ALL_OF_IT.search(m) and only_command_words(m, sections):    # "also add it to the summary"
        return ("also", sid)
    if ADD.search(m) and (ALL_OF_IT.search(m) or wants_summary(m)) and not THIRD_PARTY.search(m):
        return ("add", "all" if ALL_OF_IT.search(m) else "summary", sid)     # no section named: Paper summary
    fallback = ("add", "proposed", sid) if approve and not (just_saved and sid) else None   # note_turn says so plainly
    if not only_command_words(m, sections):
        return fallback
    if MOVE.search(m):
        return ("move", sid)
    return fallback


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


def approved_line(label):
    return f"Saved under {label}, marked as drafted from the paper's claims and approved by you."


def duplicate_line(labels):
    return "That's already in your draft under " + " and ".join(labels) + ", so I didn't save it again."


POINTER = re.compile(r"\s*\((?:Sections?|Abstract|Appendix|Introduction|References|Table|Figure|Fig\.|p\.?)\s?[^()]{0,40}\)"
                     r"|\s*\[[A-Za-z0-9_.:-]+(?:\s*,\s*[A-Za-z0-9_.:-]+)*\]", re.I)


def without_pointers(text):
    """Text to save: no "(Section 3)" pointers and no span markers, whitespace tidied."""
    return " ".join(POINTER.sub("", text or "").split()).replace(" .", ".").replace(" ,", ",")


NOT_SAVED = "I couldn't save that to your draft."
NOTHING_TO_ADD = "I haven't written a summary or other text in this conversation that I could add."
NOTHING_SAVED = "There's no note from this conversation for that to apply to yet."
CLAIMS_LABEL = "Drafted from the paper's claims"
APPROVED_LABEL = "Drafted from the paper's claims, approved by you"


def undo_line(kind, label):
    if kind == "moved":
        return f"Undone: it's back under {label}."
    return f"Undone: I removed it from {label}."
