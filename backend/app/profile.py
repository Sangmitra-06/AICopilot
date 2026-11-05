"""The onboarding profile as the backbone of the conversation: which profile reference the app uses this turn, and the
app's own lines that quote the reviewer's words back.

Pure functions, no model and no store. Rules (CLAUDE.md, "Reviewer profile"): quote the reviewer's words exactly, never
rank or reinterpret them, never use them to say anything about the paper, at most one profile reference per turn, and
never the same reference twice in a row (the previous assistant turn's meta `profile_ref` says which one it used).
"""
import re

from . import onboarding

# The fields that can be referred back to in a turn, in the order the app rotates through them.
LENS = ("strength_criteria", "weakness_criteria", "note_habit")
TIME_WORDS = re.compile(r"\b(?:time|long|slow|hours?|takes? (?:a while|ages|forever)|busy|quick(?:ly)?|fast|deadline)\b",
                        re.I)


def words(view, field):
    """The reviewer's own words for a field ("" when skipped, defaulted or "none")."""
    e = ((view or {}).get("fields") or {}).get(field) or {}
    if e.get("source") not in ("answer", "extracted"):
        return ""
    raw = onboarding.tidy(" ".join(str(e.get("raw") or "").split()), edges_only=True)   # edge marks only
    if not raw or raw.strip(" .!").lower() in ("none", "no", "nothing", "n/a", "na", "skip"):
        return ""
    return raw[:200]


def value(view, field):
    return (((view or {}).get("fields") or {}).get(field) or {}).get("value")


def reads_first(view):
    """workflow_mode "read first": the app waits and answers only when asked (no leading, no nudges, no lens prompts)."""
    return value(view, "workflow_mode") == "read_first"


def choose(view, last_ref, candidates=LENS):
    """The one profile field to refer back to this turn, or None. Rotates through `candidates` the reviewer actually
    stated, starting after the one used last turn, and never picks that same one again."""
    have = [f for f in candidates if words(view, f)]
    if not have:
        return None
    start = (candidates.index(last_ref) + 1) if last_ref in candidates else 0
    for k in range(len(candidates)):
        f = candidates[(start + k) % len(candidates)]
        if f in have and f != last_ref:
            return f
    return None


def quote(w):
    return "“" + w.strip().strip("“”\"'").rstrip(".") + "”"


def lens_line(field, view):
    """The app's own light prompt for a section on screen, tied to what the reviewer said matters to them. It names
    their lens and asks them to look; it never says anything about the paper."""
    w = words(view, field)
    if field == "strength_criteria":
        return f"You said {quote(w)} is what counts as a strength for you. Want to read this part with that in mind?"
    if field == "weakness_criteria":
        return f"You said {quote(w)} is what counts as a weakness for you. Want to read this part with that in mind?"
    if field == "note_habit":
        if value(view, "note_habit") == "annotate_pdf":
            return (f"Since you said you keep notes {quote(w)}, you can drag a box over any passage here to mark it, and "
                    "I'll quote it back in the chat.")
        return f"Since you said you keep notes {quote(w)}, tell me anything here you want to keep and I'll save it in your words."
    return ""


def turn_note(field, view):
    """The THIS TURN directive for a model-written reply: the one profile reference it may use."""
    return (f"PROFILE REFERENCE (optional, at most one this turn): if it fits naturally, tie ONE light prompt about how "
            f"the reviewer is reading to their own words for this field, quoted exactly: {field} = {quote(words(view, field))}. "
            "Ask them to look at the paper with that lens; never say whether the paper meets it. Use no other profile "
            "reference in this reply.")


def wants_brevity(view):
    """hardest_part says time is the hard part: short answers, and a checklist of what is still open instead."""
    return bool(TIME_WORDS.search(words(view, "hardest_part")))


def bad_traits_line(view):
    w = words(view, "bad_review_traits")
    return f"You said {quote(w)} is a trait you don't want in a review, so keep that in mind as you check your draft." if w else ""


def norm(t):
    return " ".join(re.findall(r"[a-z0-9]+", (t or "").lower()))


def duplicates(texts):
    """Pairs of notes in the draft that say the same thing (one contains the other, or they share most words)."""
    out = []
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            a, b = norm(texts[i]), norm(texts[j])
            if not a or not b:
                continue
            wa, wb = set(a.split()), set(b.split())
            if a in b or b in a or len(wa & wb) / max(1, min(len(wa), len(wb))) >= 0.8:
                out.append((texts[i], texts[j]))
    return out
