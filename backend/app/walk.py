"""The guided walk: the order in which the app takes the reviewer through the paper, and the plain lines it uses.

Pure functions, no model and no store. The order comes from the reviewer's own free-text reading_order, matched loosely
against the paper's REAL section titles (the span section metadata); anything that cannot be read falls back to the
paper's own order. Nothing here says anything about the paper: the lines are the reviewer's own words, a section's title
as the paper prints it, and a pointer. chatflow logs the events and sends the lines.
"""
import re

from . import cites, chat_checks, onboarding

HIDDEN = ("References", "Front matter", "Added from PDF")

# What a reviewer may call a part of the paper -> the titles it can stand for. A word names the titles of its first tier
# that matches any section ("results" means a Results section if there is one, otherwise Experiments).
_EXP = [r"experiment|evaluation", r"result|empirical|finding"]
_RES = [r"result", r"experiment|evaluation|empirical|finding"]
_METH = [r"method", r"approach|model|architecture|framework|technique|algorithm|system|set-?up"]
WORDS = [
    (r"abstract", [r"abstract"]),
    (r"intro(?:duction)?", [r"intro"]),
    (r"related\s+work|prior\s+work|literature|background", [r"related|prior work|literature|background"]),
    (r"methodology|methods?", _METH),
    (r"approach", [r"approach"] + _METH),
    (r"set-?up", [r"set-?up"] + _METH),
    (r"models?|architecture", [r"model|architecture"] + _METH),
    (r"results?|findings", _RES),
    (r"experiments?|experimental|evaluations?", _EXP),
    (r"analysis|ablations?", [r"analysis|ablation", r"discussion"]),
    (r"discussion", [r"discussion", r"analysis"]),
    (r"conclusions?|concluding", [r"conclusion|concluding", r"discussion|summary|future"]),
    (r"limitations?", [r"limitation"]),
    (r"ethics|ethical", [r"ethic"]),
    (r"data(?:sets?)?", [r"data"]),
]
_WORD_RE = re.compile("|".join(f"(?P<w{i}>\\b(?:{p})\\b)" for i, (p, _) in enumerate(WORDS))
                      + r"|(?P<num>\bsections?\s+(?P<n>\d+(?:\.\d+)*)\b)", re.I)
_CLAUSE = re.compile(r"[,;.\n]|->|→|\bthen\b|\band\b|\bbut\b", re.I)
_AVOID = re.compile(r"\b(?:skip(?:ping)?|ignore|avoid|never|don(?:'|’)?t|do not|rarely|last|leave|without)\b", re.I)


def real_sections(spans):
    """The paper's own sections, in paper order: no references (or anything after), no front matter, no stray text."""
    out = []
    for s in spans:
        sec = s.get("section")
        if sec == "References":
            break
        if sec in HIDDEN or s.get("kind") in ("loose", "added") or not sec:
            continue
        if sec not in out:
            out.append(sec)
    return out


def titles_for(word_index, sections):
    """The sections one of WORDS stands for in this paper (first tier that matches), in paper order."""
    for pat in WORDS[word_index][1]:
        hit = [t for t in sections if re.search(pat, t.lower())]
        if hit:
            return hit
    return []


def by_number(num, sections):
    return [t for t in sections if re.match(rf"{re.escape(num)}(?:\.?\s|$)", t)]


def mentions(text, sections):
    """[(titles, the reviewer's word)] in the order the words come in `text`. A word in a clause where they say they skip
    or leave it (a "skip related work", "results last") is not an instruction to go there, so it is left out."""
    text = text or ""
    cuts = [m.start() for m in _CLAUSE.finditer(text)]
    out = []
    for m in _WORD_RE.finditer(text):
        clause = sum(1 for c in cuts if c < m.start())
        lo = cuts[clause - 1] if clause else 0
        hi = cuts[clause] if clause < len(cuts) else len(text)
        if _AVOID.search(text[lo:hi]):
            continue
        if m.group("num"):
            hit, said = by_number(m.group("n"), sections), "section " + m.group("n")
        else:
            i = next(k for k in range(len(WORDS)) if m.group(f"w{k}"))
            hit, said = titles_for(i, sections), " ".join(m.group(f"w{i}").lower().split())
        if hit:
            out.append((hit, said))
    return out


def parse_reading_order(text, sections):
    """The reading order as [{"section": title, "said": the reviewer's word or None}]. The sections they named come
    first, in the order they named them (with their word, so we can say "as you said"); every other section follows in
    paper order with said=None. Text that names nothing the paper has is simply the paper's order."""
    out, seen = [], set()
    for titles, said in mentions(text, sections):
        for t in titles:
            if t not in seen:
                seen.add(t)
                out.append({"section": t, "said": said})
    return out + [{"section": t, "said": None} for t in sections if t not in seen]


def reading_text(view):
    """What the reviewer said about how they read, in their words ("" for a skip or a default, which say nothing)."""
    e = ((view or {}).get("fields") or {}).get("reading_order")
    if not e or e.get("source") not in ("answer", "extracted"):
        return ""
    raw = (e.get("raw") or "").strip()
    if e["source"] == "extracted":              # the whole message was scanned: keep only the sentence that said it
        raw = next((s.strip() for s in re.split(r"(?<=[.!?])\s+", raw)
                    if onboarding.x_reading(s, False) == e.get("value")), "")
    return raw


def build_order(view, spans):
    return parse_reading_order(reading_text(view), real_sections(spans))


# ------------------------------------------------------------------ what the app says

def section_spans(spans, title, n=3):
    """The first few passages of a section, to cite: the PDF scrolls to and marks them."""
    return [s for s in spans if s.get("section") == title and cites.citable(s)][:n]


def the(said):
    return said if said.startswith("section") else "the " + said


# Words that rate. The app repeats a paper heading in its own line only if none of these is in it (verify.BANNED and the
# chat checks are consulted too; this list adds the ones CLAUDE.md names that those do not carry).
EXTRA_EVAL = re.compile(r"\b(?:limited|poor|excellent|great|good|bad|clear|unclear|thorough|superior|inferior|better|"
                        r"worse|best|worst|lacking|insufficient|adequate|inadequate|rigorous|robust|elegant)\b", re.I)


def rates(text):
    return bool(chat_checks.banned_hits(text, set()) or chat_checks.EVAL_WORD.search(text) or EXTRA_EVAL.search(text))


def title_phrase(title):
    """A section as a phrase, from the paper's own heading: "3 Method" -> "the method"."""
    rest = re.sub(r"^\s*(?:\d+(?:\.\d+)*\.?|[A-Z]\.)\s+", "", title).strip()
    rest = re.sub(r"(?i)^the\s+", "", rest)
    if rest[:2].isupper() or not rest:
        phrase = rest
    else:
        phrase = rest[:1].lower() + rest[1:]
    phrase = "the " + phrase if phrase else "the next section"
    return "the next section" if rates(phrase) else phrase


def where(entry):
    """How to name a section in a line: the reviewer's own word if they used one, else the paper's heading."""
    return the(entry["said"]) if entry.get("said") else title_phrase(entry["section"])


def marked(line, spans, title):
    """`line` (without its closing full stop) + the section's passages as citation markers + the stop: text the reply
    cites in the usual way (cites.extract turns the markers into a plain "(Section 4)" pointer)."""
    ids = "".join(f"[{s['id']}]" for s in section_spans(spans, title))
    return f"{line} {ids}." if ids else f"{line}."


def opening_lead(entry):
    """The app's own words that take the reviewer to the first section (no full stop, no pointer)."""
    if entry.get("said"):
        return f"You said you like to start with {where(entry)}, here it is"
    return f"Let's begin at the start of the paper, with {where(entry)}"


def opening_line(entry, spans):
    return marked(opening_lead(entry), spans, entry["section"])


# The app's own friendly words around the opening summary (the model writes only the descriptive middle, at most three
# sentences). They say what the message is and what comes next, never anything about the paper.
SUMMARY_LEAD = "You asked for a short summary before reading, so here's what the paper says."
SUMMARY_CLOSES = ("That's the short version. Now let's go through the paper together.",   # a first section follows
                  "That's the short version. Ask me about any part whenever you like.")      # no walk to follow


def summary_message(body, walk_follows=True):
    return SUMMARY_LEAD + "\n\n" + body + "\n\n" + SUMMARY_CLOSES[0 if walk_follows else 1]


GUIDE_HINT = "Say “next” when you want to move on, name any part to go straight there, or tell me to stop guiding."


# ------------------------------------------------------------------ model-written descriptions: sentences and pointers

_ABBR = re.compile(r"\b(?:et al|e\.g|i\.e|vs|figs?|eqs?|secs?|cf|etc|approx|no)\.", re.I)
_BOUND = re.compile(r"([.!?][\"”')]*)((?:[ \t]*\[[^\]\n]{1,80}\])*)\s+")
_END = re.compile(r"([.!?]+[\"”')]*)\s*$")
_DOT = "\x00"


def sentences(text):
    """The text cut into sentences. A citation marker that follows the full stop stays with the sentence it ends;
    "et al.", "e.g." and the like do not end one."""
    t = _ABBR.sub(lambda m: m.group(0).replace(".", _DOT), (text or "").strip())
    out, pos = [], 0
    for m in _BOUND.finditer(t):
        out.append(t[pos:m.end(2)])
        pos = m.end()
    if pos < len(t):
        out.append(t[pos:])
    return [s.replace(_DOT, ".").strip() for s in out if s.strip()]


def one_pointer_each(text, valid, limit=None):
    """Tidy a model-written, marker-bearing paragraph. At most `limit` sentences; each sentence carries at most ONE run of
    markers at its end (the sentence's markers, merged); a marker that is not a span in `valid` (id -> span) is dropped; a
    run whose pointer reads exactly like the previous sentence's is not shown again (its spans still count, see the second
    value). Returns (text, [ids whose pointer is not shown])."""
    out, hidden, prev = [], [], None
    for sent in sentences(text)[:limit]:
        ids = []
        for m in cites.GROUP.finditer(sent):
            ids += [t for t in (cites._tokens(m.group(1)) or []) if t in valid]
        body = cites.GROUP.sub(lambda m: "" if cites._tokens(m.group(1)) else m.group(0), sent)
        end = _END.search(body)
        punct = end.group(1) if end else "."
        body = re.sub(r"\s+([.,;:!?])", r"\1", " ".join((body[:end.start()] if end else body).split()))
        ids = list(dict.fromkeys(ids))
        if ids:
            label = cites.label([valid[i] for i in ids])
            if label == prev:
                hidden += ids
                ids = []
            else:
                prev = label
        out.append(body + "".join((" " if k == 0 else "") + f"[{i}]" for k, i in enumerate(ids)) + punct)
    return " ".join(out), list(dict.fromkeys(hidden))


def cite_entry(span):
    return {"id": span["id"], "page": span.get("page"), "bbox": span.get("bbox"), "section": span.get("section"),
            "lines": span.get("lines")}


# ------------------------------------------------------------------ reading the reviewer's message during the walk

_ACK = r"(?:ok(?:ay)?|alright|cool|great|thanks?|thank you|yes|yeah|yep|sure|right|fine|so|and|please)"
ADVANCE = re.compile(
    r"^\W*(?:" + _ACK + r"\W+)*(?:ok(?:ay)?|alright|cool|fine|kk?|got it|understood|noted|makes sense|i see|"
    r"next(?:\s+(?:one|section|part|please))?|(?:let(?:'|’)?s )?move on|moving on|go on|continue|keep going|carry on|"
    r"proceed|done(?:\s+with\s+(?:this|that|it|the section|this section))?|i(?:'|’)?m done|finished|ready|"
    r"what(?:'|’)?s next|onward)(?:\W+(?:please|thanks?|thank you))?\W*$", re.I)

STOP = re.compile(
    r"\b(?:stop|quit|end|cancel|drop|disable|turn off|switch off)\s+(?:the\s+|this\s+|all\s+|your\s+|that\s+)?"
    r"(?:guid\w*|walk\w*|tour|prompting|nudg\w*|leading me)\b|\bno more (?:guid\w*|walk\w*|nudg\w*|prompt\w*)\b|"
    r"\bdon(?:'|’)?t (?:guide|lead|walk|nudge|prompt) me\b|\b(?:i(?:'|’)?ll|i will|let me) (?:take it|go|do it|drive) "
    r"from here\b|\bi(?:'|’)?ve got it from here\b", re.I)

JUMP = re.compile(
    r"^\W*(?:(?:ok(?:ay)?|now|so|actually|please|and)\W+)*"
    r"(?:(?:let(?:'|’)?s|can we|could we|can you|could you|i(?:'|’)?d like to|i want to|i(?:'|’)?ll|let me)\s+)?(?:please\s+)?"
    r"(?:(?:go|jump|move|skip|head|turn)(?:\s+(?:straight|directly|right|ahead|back|over|on))*\s+to|take me to|bring me to|"
    r"show me|look at|looking at|read|open|start with|begin with|see)\s+(?P<what>[^?]{1,60}?)\W*(?:please)?\W*$", re.I)
_FILLER = re.compile(r"\b(?:the|a|an|section|sections|part|parts|of|paper|again|now|please|first|bit|to|over|there|it|"
                     r"then|straight|directly|right|ahead)\b", re.I)


def jump_target(message, sections):
    """{"section", "said"} when the whole message is a request to go to a part of the paper ("go to results", "take me to
    section 3"); None for anything else, including a request that asks for more than the move."""
    m = JUMP.match(message or "")
    if not m:
        return None
    what = m.group("what")
    found = mentions(what, sections)
    if not found:
        return None
    hit = _WORD_RE.sub(" ", what)
    if _FILLER.sub(" ", hit).strip(" ,.;:-	"):
        return None                                  # "go to results and tell me if ...": more than a move
    titles, said = found[0]
    return {"section": titles[0], "said": said}


def next_index(w):
    """The next section in the order that has not been shown, after the pointer; None when the order is used up."""
    for i in range((w["pointer"] if w["pointer"] is not None else -1) + 1, len(w["order"])):
        if w["order"][i]["section"] not in w["covered"]:
            return i
    return None


def active(w):
    return bool(w["opened"] and w["order"] and not w["stopped"])




def move_lead(entry, kind="advance"):
    """"Moving to the methods, as you said" (no full stop, no pointer). The reviewer's own word is used when they named the
    part, "as you asked" after a jump, and nothing is claimed for a part they did not name."""
    x = where(entry)
    if kind == "jump":
        return f"Going to {x}, as you asked"
    return f"Moving to {x}{', as you said' if entry.get('said') else ''}"


def move_line(entry, spans, n, kind="advance"):
    return marked(move_lead(entry, kind), spans, entry["section"])


STOPPED = "Okay, I'll stop guiding. Ask for anything you want from here, and I'll follow."
LAST = "That was the last section in your order."
