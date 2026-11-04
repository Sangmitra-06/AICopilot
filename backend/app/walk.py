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


def title_phrase(title):
    """A section as a phrase, from the paper's own heading: "3 Method" -> "the method"."""
    rest = re.sub(r"^\s*(?:\d+(?:\.\d+)*\.?|[A-Z]\.)\s+", "", title).strip()
    rest = re.sub(r"(?i)^the\s+", "", rest)
    if rest[:2].isupper() or not rest:
        phrase = rest
    else:
        phrase = rest[:1].lower() + rest[1:]
    phrase = "the " + phrase if phrase else "the next section"
    return "the next section" if chat_checks.banned_hits(phrase, set()) else phrase


def where(entry):
    """How to name a section in a line: the reviewer's own word if they used one, else the paper's heading."""
    return the(entry["said"]) if entry.get("said") else title_phrase(entry["section"])


def marked(line, spans, title):
    """`line` (without its closing full stop) + the section's passages as citation markers + the stop: text the reply
    cites in the usual way (cites.extract turns the markers into a plain "(Section 4)" pointer)."""
    ids = "".join(f"[{s['id']}]" for s in section_spans(spans, title))
    return f"{line} {ids}." if ids else f"{line}."


def opening_line(entry, spans):
    if entry.get("said"):
        return marked(f"Starting with {where(entry)}, as you said you like to", spans, entry["section"])
    return marked(f"Let's begin at the start of the paper, with {where(entry)}", spans, entry["section"])


GUIDE_HINT = "Say “next” when you want to move on, name any part to go straight there, or tell me to stop guiding."
