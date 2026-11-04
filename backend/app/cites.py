"""Citations in chat replies: which paper spans a reply points at.

The chat prompt labels every span `[id]` and asks the model to put a span's label after a sentence only when the
sentence refers to that passage. This module turns those markers into two things:

  * the text the reviewer reads: each marker (or run of markers) becomes a plain section pointer such as
    "(Section 4)". The reviewer never sees an id.
  * `cites`: the spans the reply refers to, so the PDF pane can scroll to and highlight them. An id that is not a
    span of this paper is dropped, and so is a span the prompt never showed (references, stray page text).

`parts` is the reply cut into pieces, `{"text": str, "cite": [ids] | None}`, joined they equal the reply, so the
frontend can render each pointer as clickable text without ever holding an id in the visible string.

The neutrality checks must not see a reply that a marker has split: `plain()` is the reply with every marker removed,
and chatflow runs the checks on it as well as on the displayed text.

Pure functions; nothing here talks to the model or the store.
"""
import re

GROUP = re.compile(r"[ \t]*\[([^\]\n]{1,80})\]")
TOKEN = re.compile(r"[A-Za-z]+\d+(?:-[A-Za-z]+\d+)*")          # shaped like a span id ("p3-s7", "s12"); "[12]" is not
LEADING_NUMBER = re.compile(r"^(\d+(?:\.\d+)*)\b")


def citable(span):
    """A span the prompt showed (see chatflow.paper_text): not references, not stray page text."""
    return span.get("section") != "References" and span.get("kind") not in ("loose", "added")


def _tokens(inner):
    toks = [t.strip() for t in re.split(r"[,;]", inner)]
    return toks if toks and all(TOKEN.fullmatch(t) for t in toks) else None


def label(spans):
    """A plain pointer for a run of cited spans: "(Section 4)", "(Sections 3, 4)", "(Abstract)"."""
    names = []
    for s in spans:
        n = s.get("section") or ""
        if n not in names:
            names.append(n)
    nums = [LEADING_NUMBER.match(n).group(1) if LEADING_NUMBER.match(n) else None for n in names]
    if all(nums):
        return "(Section" + ("s " if len(nums) > 1 else " ") + ", ".join(nums) + ")"
    return "(" + "; ".join(f"Section {x}" if x else n for n, x in zip(names, nums) if n or x) + ")"


def _segments(reply):
    """[["text", str] | ["mark", [tokens]]]. Markers that touch (only whitespace between them) are one run."""
    segs, pos = [], 0
    for m in GROUP.finditer(reply):
        toks = _tokens(m.group(1))
        if toks is None:
            continue
        between = reply[pos:m.start()]
        if segs and segs[-1][0] == "mark" and not between.strip():
            segs[-1][1].extend(toks)
        else:
            if between:
                segs.append(["text", between])
            segs.append(["mark", list(toks)])
        pos = m.end()
    if pos < len(reply):
        segs.append(["text", reply[pos:]])
    return segs


def plain(reply):
    """The reply with every marker removed and nothing put in its place. This is what the neutrality checks read in
    addition to the displayed text, so a marker can never separate the words of a sentence they would block."""
    text = "".join(" " if k == "mark" else v for k, v in _segments(reply))   # a space, so words never fuse
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r" ([.,;:!?)])", r"\1", text).strip()


def extract(reply, spans):
    """(text, parts, cites). `text` is what the reviewer reads, `cites` the spans it points at (order of first
    mention), `parts` the pieces of `text` with the pointers marked, or None when nothing is cited."""
    by_id = {s["id"]: s for s in spans if citable(s)}
    pieces, cites, seen = [], [], set()
    for kind, v in _segments(reply):
        if kind == "text":
            pieces.append({"text": v, "cite": None})
            continue
        real = [by_id[t] for t in dict.fromkeys(v) if t in by_id]
        if not real:                                             # unknown ids are dropped without a trace
            continue
        for s in real:
            if s["id"] not in seen:
                seen.add(s["id"])
                cites.append({"id": s["id"], "page": s.get("page"), "bbox": s.get("bbox"),
                              "section": s.get("section"), "lines": s.get("lines")})
        before = "".join(p["text"] for p in pieces)
        lead = "" if not before or before.endswith((" ", "\n", "\t")) else " "
        if lead:
            pieces.append({"text": lead, "cite": None})          # the space stays outside the clickable pointer
        pieces.append({"text": label(real), "cite": [s["id"] for s in real]})
    text = "".join(p["text"] for p in pieces).strip()
    if not cites:
        return text, None, []
    return text, reconcile(pieces, text), cites


def reconcile(parts, reply):
    """Make `parts` join to exactly `reply` after the reply was edited (a note appended, whitespace cleaned): extra text
    at the end becomes a plain part; any other difference is repaired by re-cutting around the pointers, and if the
    pointers cannot be found in the new text the parts are dropped (the cites stay; the text is just not clickable)."""
    if not parts:
        return None
    joined = "".join(p["text"] for p in parts)
    if joined == reply:
        return parts
    out, pos = [], 0
    for p in parts:
        if p["cite"] is None:
            continue
        at = reply.find(p["text"], pos)
        if at < 0:
            return None
        if at > pos:
            out.append({"text": reply[pos:at], "cite": None})
        out.append({"text": p["text"], "cite": p["cite"]})
        pos = at + len(p["text"])
    if pos < len(reply):
        out.append({"text": reply[pos:], "cite": None})
    return out
