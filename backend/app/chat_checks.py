"""Neutrality checks for chat replies.

Every reply goes through reply_errors(). It reuses the existing layers rather than replacing them:
verify.BANNED (evaluative words) and llm.JUDGE (requests for / statements of judgment), and adds what a
free-form reply needs: no stated opinion about the reviewer's take, no stock re-ask at the end, no pile of
questions, a real decline when judgment was asked for, no unrequested summary.

Over-blocking matters as much as leaking, so the reviewer's own words are licensed in one narrow place:
a sentence addressed to them ("you said the baseline is weak"), or a sentence that declines to rule on them
("I can't say whether it is novel; that is your call"). Quoted text (the paper's words, or theirs) is never
checked, and a few established technical terms ("weak supervision") are not evaluations.
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
    r"\bi(?: would|(?:'|’)d) (?:accept|reject|score|rate|recommend)\b|"
    r"\byou(?:'|’)?re (?:absolutely |completely |totally |quite )?(?:right|correct|wrong|mistaken)\b|"
    r"\byou are (?:absolutely |completely |totally |quite )?(?:right|correct|wrong|mistaken)\b|"
    r"\b(?:good|great|excellent|fair|valid|astute|sharp) (?:point|catch|call|observation|criticism)\b|"
    r"\bthat(?:'|’)?s (?:a )?(?:fair|valid|good|great|reasonable|legitimate|solid|strong) "
    r"(?:concern|point|criticism|take|read|worry|observation)\b|"
    r"\b(?:the paper|this paper|it) (?:deserves|should be|ought to be) (?:accepted|rejected)\b", re.I)

# A decline may NAME the thing it declines, as an evaluative word may be named ("I can't say whether it is novel"):
# "Whether I agree isn't something I can weigh in on", "I can't weigh in on accept or reject". The named clause
# (after whether / if / on / about / regarding, up to punctuation or a conjunction) is set aside before the
# opinion and judgment patterns are applied. Anything asserted outside that clause is still checked in full, so
# "I can't weigh in on whether it is novel, but I'd accept it" stays blocked.
NAMED = re.compile(r"\b(?:whether|if|on|about|regarding)\b"
                   r"(?:(?!\b(?:and|but|though|although|however|so|then|because|since|while)\b)[^.;,!?]){0,60}", re.I)

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

# JUDGE was written for questions. In chat, reviewers also STATE views ("The baseline is weak."), which is not a
# request for the assistant's judgment, so a message only counts as one when it is also question-shaped or
# addresses the assistant directly.
QUESTION_LIKE = re.compile(r"\?|^\s*(?:is|are|was|were|do|does|did|would|should|can|could|will|shall|what|how|why|"
                           r"which|am i|tell me|give me your)\b|\bdo you (?:agree|think|feel|believe)\b", re.I)


def asks_for_judgment(message):
    """Is this message a request for the assistant's own judgment (as opposed to the reviewer stating theirs)?"""
    return bool(JUDGE.search(message)) and bool(QUESTION_LIKE.search(message))


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


# The reviewer's word, reported as theirs: "you said ...", "you find the baseline weak", "your concern about ...",
# "looks weak to you". Not "as you said, X is weak", which would endorse it.
ATTRIB = re.compile(
    r"\b(?:you(?:'ve|'d|'re|'ll|’ve|’d|’re|’ll)?\s+(?:\w+\s+){0,2}?(?:said|say|saying|mention\w*|"
    r"note[ds]?|wrote|write|call(?:ed)?|describ\w*|flag\w*|find|found|think|thought|feel|felt|see|saw|consider\w*|"
    r"believe\w*|worr\w*|suspect\w*|mean\w*|ask\w*|rais\w*|regard\w*)|"
    r"your\s+(?:note|comment|point|concern|worry|view|take|read|assessment|criticism|words?|phrase|impression|sense))\b",
    re.I)
ATTRIB_NEAR = re.compile(r"\b(?:to|for) you\b|\bin your (?:view|opinion|eyes|words)\b|\baccording to you\b", re.I)
ENDORSING = re.compile(r"\b(?:as|like|since|because|given)\s*$", re.I)


def attributed(sent, word):
    pat = r"\b" + re.escape(word) + r"\b"
    for m in ATTRIB.finditer(sent):
        if not ENDORSING.search(sent[:m.start()]) and re.search(pat, sent[m.start():m.start() + 140], re.I):
            return True
    return any(re.search(pat, sent[max(0, m.start() - 60):m.end() + 60], re.I) for m in ATTRIB_NEAR.finditer(sent))


def licensed_here(sent, word, licensed):
    """May the reviewer's own evaluative `word` appear in this sentence? Yes if the sentence reports it as theirs
    ("you said the baseline is weak"), or is a decline that only NAMES it ("I can't say whether it is novel").
    Not if the sentence merely addresses them ("that's your call") while asserting the word, or endorses it
    ("as you said, the baseline is weak")."""
    if word not in licensed:
        return False
    if attributed(sent, word):
        return True
    return bool(DECLINE_MARK.search(sent)) and bool(
        re.search(r"\b(?:whether|if|about|on|regarding)\b[^.;]{0,40}\b" + re.escape(word) + r"\b", sent, re.I))


def banned_hits(reply, licensed):
    hits = []
    for sent in SENT.split(TECH_TERMS.sub(" ", QUOTED.sub(" ", reply))):
        for m in BANNED.finditer(sent):
            w = m.group(0).lower()
            if licensed_here(sent, w, licensed):
                continue
            hits.append(w)
    return hits


def judgment_flags(reply, licensed):
    """(takes_a_side, states_a_judgment), sentence by sentence. Quotes and technical terms are ignored, "okay" is
    ignored, the reviewer's own evaluative words are blanked where licensed, and in a sentence that declines the
    clause naming what is declined is set aside first."""
    side = judged = False
    for sent in SENT.split(TECH_TERMS.sub(" ", QUOTED.sub(" ", reply))):
        if DECLINE_MARK.search(sent):
            sent = NAMED.sub(" ", sent)
        if OPINION.search(sent):
            side = True
        sent = OKAY.sub(" ", sent)
        sent = EVAL_WORD.sub(lambda m: "xx" if licensed_here(sent, m.group(0).lower(), licensed) else m.group(0), sent)
        if JUDGE.search(sent):
            judged = True
    return side, judged


def questions(reply):
    return [s for s in SENT.split(QUOTED.sub(" ", reply)) if s.strip().endswith("?")]


# A reworded comment must keep the reviewer's stance: the same evaluative words, hedges, intensifiers,
# negations and numbers, with none added.
HEDGES = set("might may maybe perhaps possibly probably seems seem appears appear somewhat slightly rather fairly "
             "quite arguably likely unlikely think thinks believe feel suspect guess suppose sort kind".split())
INTENSIFIERS = set("very extremely highly completely totally entirely clearly obviously definitely certainly too "
                   "really absolutely hardly barely strongly".split())
STANCE_ADJ = set("poor sloppy thin vague unclear confusing insufficient inadequate lacking missing unconvincing "
                 "unjustified unsupported incomplete shallow superficial incremental trivial naive misleading wrong "
                 "bad great nice excellent impressive interesting clear careful thorough rigorous weak strong flawed "
                 "novel solid sound fair convincing important significant original reasonable appropriate justified "
                 "adequate sufficient enough good worthwhile".split())
NEGATION = re.compile(r"\b(?:not|no|never|none|neither|nor|without|cannot)\b|n(?:'|\u2019)t\b", re.I)
NUMBERS = re.compile(r"\d+(?:\.\d+)?")


def stance_words(text):
    return {w for w in words(text) if w in HEDGES or w in INTENSIFIERS or w in STANCE_ADJ}


def stance_errors(original, rewrite):
    """Why `rewrite` is not the same comment in other words (empty list: it keeps the stance)."""
    errs, a, b = [], stance_words(original), stance_words(rewrite)
    if a - b:
        errs.append("the rewrite dropped the reviewer's own words: " + ", ".join(sorted(a - b)))
    if b - a:
        errs.append("the rewrite added words that change the stance: " + ", ".join(sorted(b - a)))
    if len(NEGATION.findall(original)) != len(NEGATION.findall(rewrite)):
        errs.append("the rewrite changes the negations (not/no/never) in the comment")
    if sorted(NUMBERS.findall(original)) != sorted(NUMBERS.findall(rewrite)):
        errs.append("the rewrite changes the numbers in the comment")
    return errs


def reword_errors(reword, reply, pool):
    """Checks on the model's "reword": {"original", "text"} object. `pool` is every text the reviewer wrote."""
    if not isinstance(reword, dict) or not str(reword.get("original", "")).strip() or not str(reword.get("text", "")).strip():
        return ["reword needs both the reviewer's original comment and your version"]
    orig, text = str(reword["original"]), str(reword["text"])
    errs = []
    if not any(_squash(orig) in _squash(p) for p in pool):
        errs.append("the 'original' is not the reviewer's own text; copy their comment exactly")
    if text not in reply:
        errs.append("put your reworded version in the reply, word for word")
    return errs + stance_errors(orig, text)


def _squash(t):
    return re.sub(r"\s+", " ", (t or "").strip().lower())


def reply_errors(reply, ctx):
    """Why this reply may not be shown (empty list: it may). ctx keys: reviewer_text, wants_decline,
    summary_pref, summary_requested."""
    reply = (reply or "").strip()
    if not reply:
        return ["the reply is empty"]
    if len(reply) > 6000:
        return ["the reply is too long; keep it to what the reviewer needs"]
    errs, lic = [], words(ctx.get("reviewer_text", ""))
    reword = ctx.get("reword")
    if reword:
        # The reworded comment is the reviewer's own wording, checked separately for stance; the rest of the
        # reply is scanned as usual.
        errs += reword_errors(reword, reply, ctx.get("reword_pool", []))
        reply = reply.replace(str(reword.get("text", "")), " ") if isinstance(reword, dict) else reply
    hits = banned_hits(reply, lic)
    if hits:
        errs.append("evaluative wording (" + ", ".join(sorted(set(hits))) + "): describe, do not rate")
    side, judged = judgment_flags(reply, lic)
    if side:
        errs.append("it takes a side on the paper or on the reviewer's view; say what you heard instead")
    if judged:
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
    elif ctx.get("require_pointer") and not POINTER.search(reply):
        errs.append("it needs section pointers, for example (Section 3): put the label of the passage after each sentence")
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
