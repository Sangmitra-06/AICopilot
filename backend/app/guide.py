import re, json
from .llm import _chat, ctx
from .verify import BANNED, NUM, norm

BANK = {
    "source": "What in the paper led you there?",
    "comparison": "What are you comparing it to?",
    "weight": "How much does this matter to you?",
    "expectation": "What did you expect to see here?",
    "open_item": "What would you want to ask the authors about this?",
}

GUIDE_SYS = f"""You help a paper reviewer think by asking ONE short question about something they flagged.
You never judge the paper and never steer the reviewer toward a conclusion.

A good question is:
- OPEN: it cannot be answered yes/no, and it does not offer the reviewer options to pick from.
- ANCHORED: it builds on the reviewer's own note or tag, or on the passage they are looking at.
- NEUTRAL: it would be equally natural if the reviewer had flagged something they liked.
- NOT NEW: it adds no concern, comparison, or fact that is in neither the reviewer's note nor the passage.

Reference questions (prefer these, or ones of the same character):
{json.dumps(BANK, indent=1)}
You may write a different question if it fits the moment better, but it must meet every rule above.

Bad questions (never write these):
- "Did you notice they only tested three models?"  (points at a problem the reviewer did not raise)
- "Is this a small fix or a big problem?"  (offers a verdict menu)
- "Don't you think the baselines are too weak?"  (leading)
- "Why is this a flaw?"  (presupposes a verdict)

Return JSON: {{"question": str, "type": "source"|"comparison"|"weight"|"expectation"|"open_item"|"other"}}"""

JUDGE_SYS = """You audit a question an assistant wants to ask a paper reviewer.
Return JSON {"leading": bool, "new_topic": bool, "valence_neutral": bool, "reason": str}.
leading: presupposes a problem or verdict, or nudges toward a particular answer.
new_topic: raises a concern, comparison, or fact that appears in neither the reviewer's note nor the passage.
valence_neutral: would read as equally natural if the reviewer had flagged a strength instead of a problem."""

YESNO = re.compile(r"^\s*(is|are|do|does|did|was|were|can|could|would|should|have|has|will|isn't|aren't|don't|didn't)\b", re.I)

def rule_errors(q, note, passage):
    errs = []
    if q.count("?") != 1 or not q.strip().endswith("?"):
        errs.append("write exactly one question ending in a question mark")
    if len(q.split()) > 25:
        errs.append("too long, keep it under 25 words")
    if YESNO.match(q):
        errs.append("yes/no form; start with what, how, where, or which")
    if re.search(r"\bor\b", q, re.I):
        errs.append("offers options; ask it open")
    if BANNED.search(q):
        errs.append("evaluative wording")
    pool = norm(note + " " + passage)
    for n in NUM.findall(q):
        if n not in pool:
            errs.append(f"number {n} is not in the note or passage")
    return errs

def judge_errors(q, tag, note, passage):
    raw = _chat([{"role": "system", "content": JUDGE_SYS},
                 {"role": "user", "content": f"Tag: {tag}\nReviewer note: {note or '(none)'}\nPassage: {passage}\nQuestion: {q}"}])
    j = json.loads(raw)
    errs = []
    if j.get("leading"): errs.append("leading: " + j.get("reason", ""))
    if j.get("new_topic"): errs.append("introduces a topic the reviewer did not raise")
    if not j.get("valence_neutral", True): errs.append("not valence-neutral")
    return errs

def guide(tag, note, spans, previous=()):
    passage = " ".join(s["text"] for s in spans)
    user = (f"Reviewer's tag: {tag}\nReviewer's note (their own words): {note or '(none)'}\n"
            f"Passage:\n{ctx(spans)}\nQuestions already asked (do not repeat): {list(previous)}")
    msgs = [{"role": "system", "content": GUIDE_SYS}, {"role": "user", "content": user}]
    for _ in range(3):
        raw = _chat(msgs)
        try:
            out = json.loads(raw)
            q, typ = out["question"].strip(), out.get("type", "other")
            errs = rule_errors(q, note, passage) or judge_errors(q, tag, note, passage)
        except Exception as e:
            q, typ, errs = "", "other", [f"invalid output: {e}"]
        if not errs:
            return {"question": q, "type": typ if typ in BANK else "other", "on_bank": typ in BANK}
        msgs += [{"role": "assistant", "content": raw},
                 {"role": "user", "content": "Rewrite the question. Problems:\n" + "\n".join(errs)}]
    return {"declined": True, "message": "No question this time. Write your note in your own words."}