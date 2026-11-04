"""Neutrality checks for chat replies.

Every reply goes through reply_errors(). It reuses the existing layers rather than replacing them:
verify.BANNED (evaluative words) and llm.JUDGE (requests for / statements of judgment), and adds what a
free-form reply needs: no stated opinion about the reviewer's take, no stock re-ask at the end, no pile of
questions, a real decline when judgment was asked for, no unrequested summary.

Over-blocking matters as much as leaking, so the reviewer's own words are licensed in one narrow place:
a sentence addressed to them ("you said the baseline is weak"). Quoted text (the paper's words, or theirs) is
never checked, and a few established technical terms ("weak supervision") are not evaluations.
"""
import logging
import re
from collections import Counter

from .llm import JUDGE, _EVAL
from .verify import BANNED

log = logging.getLogger("copilot.chat")
STATS = Counter()  # process-wide totals; per-paper numbers are replayed from the chat_check events

QUOTED = re.compile(r'"[^"]*"|“[^”]*”')
SENT = re.compile(r"(?<=[.!?])\s+|\n+")
ADDRESSED = re.compile(r"\b(you|your|you're|you've|you'd|you'll|yours)\b", re.I)
EVAL_WORD = re.compile(r"\b" + _EVAL + r"\b", re.I)
# Technical terms that happen to contain an evaluative word. They name a method; they do not rate anything.
TECH_TERMS = re.compile(r"\b(?:weak(?:ly)?[- ](?:supervis\w*|label\w*|learn\w*|annotat\w*)|"
                        r"strong(?:ly)?[- ]supervis\w*|key[- ](?:value|frames?|terms?|words?|phrases?)|"
                        r"novel[- ]view|promising[- ]region)\b", re.I)
OKAY = re.compile(r"\b(?:ok|okay)\b", re.I)  # "Okay," / "Is that okay?" is a colleague talking, not a rating

# The assistant siding with, or ruling on, the reviewer's take (or the paper). Never allowed, even if the
# reviewer used the same words.
OPINION = re.compile(
    r"\bi (?:agree|disagree)\b|"
    r"\bi (?:think|believe|feel) (?:the paper|this paper|the authors|the results|the experiments|the method|"
    r"your (?:concern|point|view|assessment|criticism|take|read))\b|"
    r"\bi would (?:accept|reject|score|rate|recommend)\b|"
    r"\byou(?:'|’)?re (?:absolutely |completely |totally |quite )?(?:right|correct|wrong|mistaken)\b|"
    r"\byou are (?:absolutely |completely |totally |quite )?(?:right|correct|wrong|mistaken)\b|"
    r"\b(?:good|great|excellent|fair|valid|astute|sharp) (?:point|catch|call|observation|criticism)\b|"
    r"\bthat(?:'|’)?s (?:a )?(?:fair|valid|good|great|reasonable|legitimate|solid|strong) "
    r"(?:concern|point|criticism|take|read|worry|observation)\b|"
    r"\b(?:the paper|this paper|it) (?:deserves|should be) (?:accepted|rejected)\b", re.I)

# Stock endings from the old guided flow, or any line that just steers back to a topic.
FORM_TAIL = re.compile(r"(?:\bback to [^.?!\n]{0,60}|\banything (?:else )?to add\b[^.?!\n]{0,20}|"
                       r"\bwant to move on\b[^.?!\n]{0,20}|\bshall we move on\b[^.?!\n]{0,20}|"
                       r"\bready to move on\b[^.?!\n]{0,20}|\blet(?:'|’)?s get back to [^.?!\n]{0,60})"
                       r"[.?!\s]*$", re.I)

DECLINE_MARK = re.compile(
    r"\b(?:can(?:'|’)?t|cannot|won(?:'|’)?t|not (?:going to|something i|my (?:call|place|role))|"
    r"isn(?:'|’)?t (?:mine|something i)|stays? with you|(?:is|that(?:'|’)?s|it(?:'|’)?s) "
    r"(?:yours|your (?:call|decision|judg\w+)|up to you|for you to)|not for me to|"
    r"i (?:leave|stay out|steer clear)|i don(?:'|’)?t (?:give|offer|weigh in|take a side|rate|score)|"
    r"judg(?:e)?ment call)\b", re.I)

SUMMARY_REQ = re.compile(r"\b(?:summar\w*|overview|tl;?dr|what(?:'|’)?s (?:this|the) paper about|"
                         r"what is (?:this|the) paper about|walk me through|main claims?|gist)\b", re.I)
SUMMARY_MARK = re.compile(r"\b(?:summary of the paper|in summary|to summari[sz]e|here(?:'|’)?s a (?:short |quick )?"
                          r"summary|here is a (?:short |quick )?summary|short summary|overview of the paper|"
                          r"the paper(?:'|’)?s main claims)\b", re.I)
POINTER = re.compile(r"\((?:sections?|sec\.|lines?|§|abstract|appendix|table|figure|page)[^)]*\)|\bsections? \d|"
                     r"§\s*\d|\blines? \d|\bin the abstract\b|\bthe abstract\b", re.I)

DECLINE_NOTE = ("The reviewer's message looks like a request for your own judgment. Your first sentence must "
                "decline in one short sentence (say it is their call, not yours). Then point them back to their "
                "own criteria and evidence, using their words from the profile when they fit, and then be useful: "
                "offer to find what the paper says, explain a term, or look at it with them.")

FALLBACK = ("I couldn't put together a reply I'm happy with just now. Tell me where you'd like to go next: "
            "a part of the paper, or a part of your review.")


def decline_fallback(phrases):
    """A one-sentence decline plus a redirect to the reviewer's own criteria, for when the model's attempts fail."""
    own = phrases.get("weakness_criteria") or phrases.get("strength_criteria")
    if own:
        return (f"That's a judgment call, so it stays with you. You said you look for “{own}”; I can show "
                "you where the paper speaks to that, or help you put your own view into words.")
    return ("That's a judgment call, so it stays with you. I can show you where the paper speaks to the point, "
            "or help you put your own view into words.")


def words(text):
    return set(re.findall(r"[a-z]+", (text or "").lower()))


def banned_hits(reply, licensed):
    hits = []
    for sent in SENT.split(TECH_TERMS.sub(" ", QUOTED.sub(" ", reply))):
        for m in BANNED.finditer(sent):
            w = m.group(0).lower()
            if w in licensed and ADDRESSED.search(sent):
                continue
            hits.append(w)
    return hits


def scrubbed(reply, licensed):
    """The reply as JUDGE should see it: quotes and technical terms gone, "okay" gone, and the reviewer's own
    evaluative words blanked in sentences addressed to them."""
    out = []
    for sent in SENT.split(TECH_TERMS.sub(" ", QUOTED.sub(" ", reply))):
        sent = OKAY.sub(" ", sent)
        if ADDRESSED.search(sent):
            sent = EVAL_WORD.sub(lambda m: "xx" if m.group(0).lower() in licensed else m.group(0), sent)
        out.append(sent)
    return ". ".join(out)


def questions(reply):
    return [s for s in SENT.split(QUOTED.sub(" ", reply)) if s.strip().endswith("?")]


def reply_errors(reply, ctx):
    """Why this reply may not be shown (empty list: it may). ctx keys: reviewer_text, wants_decline,
    summary_pref, summary_requested."""
    reply = (reply or "").strip()
    if not reply:
        return ["the reply is empty"]
    if len(reply) > 6000:
        return ["the reply is too long; keep it to what the reviewer needs"]
    errs, lic = [], words(ctx.get("reviewer_text", ""))
    hits = banned_hits(reply, lic)
    if hits:
        errs.append("evaluative wording (" + ", ".join(sorted(set(hits))) + "): describe, do not rate")
    if OPINION.search(QUOTED.sub(" ", reply)):
        errs.append("it takes a side on the paper or on the reviewer's view; say what you heard instead")
    if JUDGE.search(scrubbed(reply, lic)):
        errs.append("it states or asks for a judgment of the paper")
    if FORM_TAIL.search(reply):
        errs.append("it ends with a stock line that steers back to a topic; end where the thought ends")
    if len(questions(reply)) > 2:
        errs.append("too many questions; make a statement and ask at most one thing")
    first = (SENT.split(reply) or [""])[0]
    if ctx.get("wants_decline") and not (DECLINE_MARK.search(first) and len(first.split()) <= 35):
        errs.append("the reviewer asked for your judgment: the FIRST sentence must decline, in one short sentence")
    if SUMMARY_MARK.search(reply):
        if not ctx.get("summary_requested") and ctx.get("summary_pref") != "before_reading":
            errs.append("it volunteers a summary the reviewer has not asked for")
        if not POINTER.search(reply):
            errs.append("a summary needs section pointers, for example (Section 3)")
    return errs


def correction(errs):
    return ("Rewrite your reply and return the full JSON again. Problems with the last one:\n"
            + "\n".join(f"- {e}" for e in errs))


def record(pid, store, info):
    """Count and log how the checks treated one reply: first-try pass, regenerated, or fallback."""
    store.log(pid, "chat_check", info)
    STATS["replies"] += 1
    if info["attempts"] > 1 or info["fallback"]:
        STATS["rejected_first_try"] += 1
    if info["fallback"]:
        STATS["fallbacks"] += 1
        log.warning("chat reply replaced by the fallback (%s); %d of %d replies so far",
                    "; ".join(info.get("errors", []))[:300], STATS["fallbacks"], STATS["replies"])
    elif info["attempts"] > 1:
        STATS["regenerated_ok"] += 1
        log.info("chat reply rejected once and regenerated (%s); %d of %d replies so far",
                 "; ".join(info.get("errors", []))[:300], STATS["rejected_first_try"], STATS["replies"])
