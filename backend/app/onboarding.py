"""Mandatory onboarding: pure functions from onboarding state to events and the next question.

State comes from store.fold_onboarding(events). Nothing here touches the database or a
model, so every rule below is unit-testable. The endpoint logs the returned events.

Rules (CLAUDE.md): one question per turn; "not sure" / "no preference" / "skip" are valid
and store a default; at most one clarifying follow-up per field; fields are also extracted
from free answers; a hard turn cap closes with whatever has been collected; experience is
inferred from concrete questions, never asked about directly. The profile changes WHAT is
asked and how much scaffolding is given. It never changes the neutrality rule.
"""
import random
import re

from . import venue
from .prompts import NEUTRALITY

MAX_TURNS = 14  # reviewer answers, follow-ups included

FIELDS = ["reading_order", "workflow_mode", "summary_preference", "note_habit",
          "excellent_review_example", "bad_review_traits", "strength_criteria", "weakness_criteria",
          "over_under_penalize", "hardest_part", "experience_level"]
EVIDENCE = ["papers_reviewed", "subarea_familiarity"]  # inputs to experience_level
ORDER = ["papers_reviewed", "subarea_familiarity", "reading_order", "workflow_mode", "summary_preference",
         "note_habit", "strength_criteria", "weakness_criteria", "over_under_penalize", "hardest_part",
         "excellent_review_example", "bad_review_traits"]
STRUCTURED = {"papers_reviewed", "subarea_familiarity", "reading_order", "workflow_mode",
              "summary_preference", "note_habit"}
MENU_FIELDS = {"strength_criteria", "weakness_criteria"}

# Stored when a reviewer skips, or the cap closes onboarding first. Free-text fields default to
# empty: the reviewer's own criteria are never invented. Experience defaults to the middle level.
DEFAULTS = {"reading_order": "paper_order", "workflow_mode": "collaborative",
            "summary_preference": "after_reading", "note_habit": "unspecified",
            "experience_level": "medium", "excellent_review_example": "", "bad_review_traits": "",
            "strength_criteria": "", "weakness_criteria": "", "over_under_penalize": "", "hardest_part": ""}

QUESTIONS = {
    "papers_reviewed": "To start, roughly how many papers have you reviewed before? A number is fine, and zero is a fine answer.",
    "subarea_familiarity": "How familiar are you with the specific subarea of the paper you will review? Your own words are fine.",
    "reading_order": "When you read a paper to review it, where do you usually start, and what comes next?",
    "workflow_mode": "Would you rather read the paper on your own first and come back to me afterward, or talk it through with me as you read?",
    "summary_preference": "Would a short, descriptive summary of the paper be useful to you, and if so, before you read it or after?",
    "note_habit": "How do you usually keep notes while you read: in the PDF, in a separate document, on paper, or mostly in your head?",
    "strength_criteria": "What makes you count something as a strength when you review? Your own criteria, in your own words.",
    "weakness_criteria": "And what makes you count something as a weakness?",
    "over_under_penalize": "Is there anything you tend to over- or under-penalize in papers?",
    "hardest_part": "What is the hardest part of writing a review for you?",
    "excellent_review_example": "Think of a review you received or read that you thought was excellent. What made it so?",
    "bad_review_traits": "And what traits make a review bad, in your view?",
}
FOLLOWUPS = {
    "papers_reviewed": "A rough number is enough, including zero. About how many papers have you reviewed?",
    "subarea_familiarity": "For example: it is your own area, you know it a little, or it is new to you. Which is closest?",
    "reading_order": "Which part do you open first: the abstract, the introduction, the method, the results, the figures, or do you read straight through?",
    "workflow_mode": "Which is closer: reading alone first and coming back, or talking it through as you go?",
    "summary_preference": "Would you want a summary before you read, after you read, or not at all?",
    "note_habit": "Where do your notes end up: annotations in the PDF, a separate document, paper, or your head?",
    # Free-text follow-ups are only ever sent after an off-topic reply: say so, ask one concrete thing,
    # and offer the skip.
    "strength_criteria": "I didn't catch that as an answer. What do you look for in a strength? Or say skip.",
    "weakness_criteria": "I didn't catch that as an answer. What do you look for in a weakness? Or say skip.",
    "over_under_penalize": "I didn't catch that as an answer. What kind of issue do you tend to weigh more or less heavily than others do? Or say skip.",
    "hardest_part": "I didn't catch that as an answer. What part of writing a review takes you the most effort? Or say skip.",
    "excellent_review_example": "I didn't catch that as an answer. What stood out in a review you thought was excellent? Or say skip.",
    "bad_review_traits": "I didn't catch that as an answer. What makes a review bad, in your view? Or say skip.",
}
OTHER = {"id": "other", "label": "Other, in my words"}

# ---------------------------------------------------------------- skip and unclear answers

SKIP = re.compile(r"\b(idk|i\s*do(?:n'?t| not)\s*know|dunno|not\s+sure|unsure|no\s+idea|no\s+preference|"
                  r"skip(?:\s+(?:this|it|that|one))*|pass|n/?a|do(?:n'?t| not)\s+care|no\s+opinion|"
                  r"no\s+comment|doesn'?t\s+matter|whatever|either\s+(?:is\s+fine|way)|"
                  r"no\s+strong\s+(?:preference|feelings?)|next|nope|nothing|none|no)\b", re.I)
FILLER = {"i", "a", "the", "really", "just", "um", "uh", "sorry", "have", "to", "it", "this", "that", "one",
          "is", "so", "but", "well", "honestly", "of", "my", "for", "on", "about", "here", "right", "now",
          "at", "all", "thanks", "thank", "you", "please", "ok", "okay", "sure", "yeah", "hmm", "mm"}
WORD = re.compile(r"[a-z0-9']+")
QUESTIONISH = re.compile(r"\?\s*$|^\s*(tell me|can you|could you|who are you|what is your|what's your|are you)\b", re.I)


FIRST_PERSON = re.compile(r"\b(i|i'm|i've|i'd|i'll|my|me|mine)\b", re.I)  # cross-field extraction only from "I ..." statements


_QUOTE = "'\"“”‘’`"
_STRAY_QUOTES = re.compile(r"(?<![A-Za-z0-9])[" + _QUOTE + r"]+|[" + _QUOTE + r"]+(?![A-Za-z0-9])")   # not the apostrophe in don't
_STRAY_SYMBOLS = re.compile(r"[\[\](){}<>*_#|\^~=]+")
_LEAD_YES = re.compile(r"^\W*(?:(?:yes|yeah|yep|yup|sure|ok|okay|well|um+|uh+|hmm+|so|i guess|i think|probably|definitely|"
                       r"absolutely|of course)\b\W*)+", re.I)
_TRAIL_POLITE = re.compile(r"\W*\b(?:please|thanks|thank you)\W*$", re.I)


def tidy(text):
    """An answer as it reads once stray punctuation (a dangling quote, a bracket) and a leading "yes," / "ok," are set
    aside: "yes, before '" reads as "before". Used only to READ the answer; what the reviewer wrote is what is stored.
    It never returns an empty string: a bare "yes" stays "yes"."""
    t = _STRAY_SYMBOLS.sub(" ", _STRAY_QUOTES.sub(" ", text or ""))
    t = " ".join(t.split())
    for pat in (_LEAD_YES, _TRAIL_POLITE):
        cut = pat.sub("", t).strip()
        if cut:
            t = cut
    return t.strip(" ,;:-–—") if t.strip(" ,;:-–—") else t


def is_skip(text):
    """True when the answer is only a pass ("not sure", "idk", "skip this one")."""
    t = (text or "").strip()
    if not t or not SKIP.search(t):
        return False
    rest = [w for w in WORD.findall(SKIP.sub(" ", t.lower())) if w not in FILLER]
    return not rest


# A sincere "nothing to add". In the free-text fields where that can be a real answer (NONE_OK) it is stored as the
# explicit answer "none" (a real answer: not a skip, not a default). In the other free-text fields a bare "no" is
# unclear and asked once. Whole replies only: "no baselines in the main table" is an ordinary answer.
NONE_OK = {"over_under_penalize", "hardest_part", "bad_review_traits"}
NONE_VALUE = "none"
_LEAD = re.compile(r"^(?:no|nope|nah|naw|well|um+|uh+|hmm+|honestly|actually|yeah|yep|sorry|oh)\s+")
_TRAIL = re.compile(r"\s+(?:really|sorry|thanks|thank you|honestly|to be honest|i guess|i think|though|at all|no)$")
_NOTHING = re.compile(
    r"(?:no|nope|nah|naw|none|nothing|nobody|no one|no thanks|no thank you|not really|not particularly|not at all|"
    r"probably not|i guess not|i suppose not|not that i (?:can|could) think of|not that i know(?: of)?|"
    r"(?:none|nothing) (?:that i (?:know|can think|could think)(?: of)?|really|in particular|comes to mind)|"
    r"i (?:do not|don't|dont) (?:really )?think so|i (?:do not|don't|dont) think (?:i do|there is|there are any)|"
    r"i (?:do not|don't|dont) tend to(?: really| do that| do so| anything)?|"
    r"i (?:do not|don't|dont) (?:really )?(?:have|know of) (?:any|one|anything)|i have none)")


def is_nothing(text):
    """Is the whole reply a sincere "nothing to add" ("none", "none that I know", "nope", "not really", "I don't think
    so", "I don't tend to", ...)? Filler and a leading "no," are ignored; skips ("idk", "no idea", "no preference",
    "skip") are not this."""
    t = " ".join(re.sub(r"[^a-z' ]+", " ", (text or "").lower().replace("’", "'")).split())
    forms = [t]
    while True:
        m = _LEAD.match(t)
        if not m or m.end() >= len(t):
            break
        t = t[m.end():]
        forms.append(t)
    forms.append(_TRAIL.sub("", t))
    return any(_NOTHING.fullmatch(f) for f in forms)


def hard_junk(text):
    """Replies that are not answers whatever the field: empty, a single word, a question back, or
    repeated characters ("aaaa", "hahahaha", "?????")."""
    t = (text or "").strip()
    letters = re.sub(r"[^a-z0-9]", "", t.lower())
    return (len(WORD.findall(t.lower())) < 1 or bool(QUESTIONISH.search(t))   # a single word passes only if topical (free_text_ok)
            or len(set(letters)) <= 3 or bool(re.search(r"(.)\1{4,}", t)))


# Topical vocabulary for free-text fields: roots shared by all of them, plus a few per field. Sincere but
# vague answers ("I mostly go with my gut") must pass, so the common list includes how-I-work words.
# Nothing here judges an answer; it only asks whether the reply is about reviewing at all.
_COMMON = ("paper claim result experiment baseline method approach novel clear clarity writing written evidence "
           "data dataset review argument contribution motivat evaluat analys ablat reproduc code theor proof figure "
           "table section abstract ground support sound rigor thorough depth detail explain compar related prior "
           "idea insight signif import interest useful solid weak strong flaw gap miss limit confus vague tone "
           "constructive specific actionable fair balanc feedback author score scor accept reject decision criteria "
           "standard bias subjectiv "
           "gut feel instinct intuit impression mostly usually tend depend generally overall sense hunch vibe seem "
           "trust think believe matter care bother annoy system process checklist habit routine rule").split()
_EXTRA = {
    "hardest_part": "time deadline start structur organi wording harsh confiden length summar decid commit".split(),
    "over_under_penalize": "typo english language grammar novelty length format notation presentation polish".split(),
    "bad_review_traits": "short lazy rude generic unfair harsh dismiss superficial".split(),
    "excellent_review_example": "detailed helpful thorough specific polite respectful".split(),
    "strength_criteria": "robust general simple elegant impact".split(),
    "weakness_criteria": "overclaim unsupported incomplete overstat".split(),
}


def topical(field, text):
    roots = set(_COMMON) | set(_EXTRA.get(field, ()))
    return any(w.startswith(r) for w in WORD.findall((text or "").lower()) for r in roots)


TOPIC_SYS = """You check one thing about a reply given during a paper reviewer's onboarding: does the reply have any relation to the question that was asked?
""" + NEUTRALITY + """
Return JSON {"on_topic": bool}.
on_topic is false ONLY when the reply has no relation to the question: it is about something else entirely, is nonsense, or is a question back to the assistant.
Any reply that touches the question's subject (reviewing, papers, or how this reviewer works or decides) is on topic, however vague, short, hesitant, or unusual it is. When in doubt, answer true.
Never judge whether the reply is good, correct, complete, or well reasoned."""


def model_on_topic(field, text):
    """Optional yes/no check for replies the rules cannot place. True / False, or None if unavailable."""
    import json
    from .llm import _chat  # imported here so the rules above stay usable without a model
    q = QUESTIONS.get(field, "")
    raw = _chat([{"role": "system", "content": TOPIC_SYS},
                 {"role": "user", "content": f"Question asked: {q}\nReply: {text}"}])
    v = json.loads(raw).get("on_topic")
    return v if isinstance(v, bool) else None


def free_text_ok(field, text, check=None):
    """Is this reply an attempt at the free-text question?

    The rules decide whether a reply can be accepted at all; the model can never overrule a rejection.
    For a reply the rules accepted, `check` may veto it, and only with an explicit False ("no relation to
    the question"). None, a non-boolean, or an exception all leave the rules' acceptance in place."""
    if hard_junk(text) or not topical(field, text):
        return False
    if check is None:
        return True
    try:
        return check(field, text) is not False
    except Exception as e:
        print("[onboarding] topic check failed, keeping the rules' verdict:", repr(e)[:120])
        return True


# ---------------------------------------------------------------- extraction (rules, no model)
# Each extractor takes (text, direct). direct=True: the text answers this very question.
# direct=False: the text answered another question, so a cue word is required.

NUMWORDS = {"zero": 0, "none": 0, "no": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
            "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15,
            "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "couple": 2, "few": 3, "several": 5,
            "dozen": 12, "dozens": 24, "many": 20, "lots": 20, "loads": 20, "countless": 30, "a lot": 20, "plenty": 20,
            "tons": 30}
_NUM = r"(\d{1,3}|" + "|".join(sorted(NUMWORDS, key=len, reverse=True)) + r")"
# Inside a longer sentence "no" and "none" are not counts ("I see no papers on this").
_NUM_IN_TEXT = r"(\d{1,3}|" + "|".join(sorted(set(NUMWORDS) - {"no", "none"}, key=len, reverse=True)) + r")"
FIRST_TIME = re.compile(r"\b(first (?:time|review|one|paper)|never (?:reviewed|done (?:one|this|a review))|"
                        r"haven'?t (?:reviewed|done (?:one|any))|not reviewed|not yet|none yet|my first|"
                        r"brand new to reviewing)\b", re.I)


def _num(tok):
    tok = tok.lower()
    return int(tok) if tok.isdigit() else NUMWORDS.get(tok)


def x_papers(text, direct):
    t = text.strip()
    if FIRST_TIME.search(t):
        return 0
    verb = r"review(?:ed|ing|s)?" if direct else r"review(?:ed|ing)"
    m = re.search(r"\b" + verb + r"\s+(?:about |around |roughly |maybe |like |over |some )?" + _NUM_IN_TEXT + r"\b", t, re.I)
    if not m and direct:  # "5 papers" only counts as an answer to this very question
        m = re.search(r"\b" + _NUM_IN_TEXT + r"\s+(?:papers?|reviews?|submissions?)\b", t, re.I)
    if m:
        return _num(m.group(1))
    if direct:
        m = re.fullmatch(r"\W*(?:about |around |roughly |maybe |like |~)?" + _NUM + r"(?: or so| times)?\W*", t, re.I)
        if m:
            return _num(m.group(1))
        if is_skip(t) or re.search(r"\b(?:skip|pass|rather not|prefer not)\b", t, re.I):
            return None                                       # "skip this one" is a skip, not a count of one
        m = re.search(r"\b" + _NUM_IN_TEXT + r"\b", t, re.I)  # "a dozen or so, mostly workshop papers"
        if m and len(t.split()) <= 10:
            return _num(m.group(1))
    return None


def x_subarea(text, direct):
    t = text.lower()
    cue = re.search(r"\b(area|field|subarea|topic|expertise|familiar|background|specialty|domain)\b", t)
    if not direct and not cue:
        return None
    if re.search(r"not (?:my|in my) (?:area|field|subarea)|outside (?:of )?(?:my|the) (?:area|field|expertise)|new to (?:this|the|me)|new for me|"
                 r"never worked|unfamiliar|not (?:very |really |that )?familiar|no background|a stranger|don'?t (?:really )?know (?:this|the) (?:area|field)|"
                 r"(?:completely|totally|entirely|brand|pretty|quite|fairly|very|really) new|new here|first time (?:in|with|seeing|reading)|"
                 r"never (?:seen|read|touched|done)|out of my (?:area|depth|wheelhouse|field)|\b(?:beginner|novice|newbie)\b|"
                 r"don'?t know (?:much|anything|it|this)", t):
        return "unfamiliar"
    if re.search(r"somewhat|a bit|a little|some (?:familiarity|background|experience)|adjacent|related (?:area|field)|"
                 r"know the basics|read about|moderately|partly|fairly familiar|kind of|sort of|so-?so|know (?:it|this|the area) "
                 r"(?:okay|ok|reasonably|decently)|intermediate", t):
        return "some"
    if re.search(r"i (?:work|publish|do research|study|write papers) (?:in|on)|my (?:main |own )?(?:area|field|subarea|specialty)|"
                 r"expert|very familiar|deeply|close to my|familiar|"
                 r"know (?:it|this|that|the (?:area|field|topic|subject)|this (?:area|field|topic)|the material)(?: \w+){0,2} well|"
                 r"well[- ]versed|work on (?:this|exactly)|comfortable with (?:it|this)", t):
        return "familiar"
    return None


_READ_TERMS = [("in_order", r"top to bottom|in order|start to finish|beginning to end|linearly|front to back|cover to cover|straight through|read (?:it )?through"),
               ("skim_first", r"skim(?:ming)?|flip through|scan(?:ning)?"),
               ("abstract_first", r"abstract"), ("intro_first", r"intro(?:duction)?"),
               ("methods_first", r"method(?:s|ology)?|approach"),
               ("results_first", r"results?|experiments?|tables?|evaluation"),
               ("figures_first", r"figures?|diagrams?|plots?|charts?"), ("conclusion_first", r"conclusions?")]
_FIRST_CUE = re.compile(r"\b(first|start(?:s|ing)?|begin(?:s|ning)?|open|jump(?:ing)? to|skip(?:ping)? to|go(?:ing)? to|head(?:ing)? to)\b", re.I)


def x_reading(text, direct):
    t = text.lower()
    for val, pat in _READ_TERMS[:1]:  # an explicit "straight through" wins
        if re.search(pat, t):
            return val
    clauses = re.split(r"[,.;]|\bthen\b|\bafter that\b|\bbefore\b", t)
    for c in clauses:
        if _FIRST_CUE.search(c):
            for val, pat in _READ_TERMS[1:]:
                if re.search(pat, c):
                    return val
    if direct:  # no "first" cue: the earliest section named
        hits = [(m.start(), val) for val, pat in _READ_TERMS[1:] for m in [re.search(pat, t)] if m]
        if hits:
            return min(hits)[1]
    return None


_READ_FIRST = re.compile(r"read (?:it |the paper |everything )?(?:first|myself|on my own|alone|by myself|through first)|on my own|"
                         r"by myself|before (?:we|you|i (?:talk|ask))|finish (?:reading|the paper)|once i(?:'ve| have)? (?:read|finished)|"
                         r"after (?:i|reading)|alone first|come back (?:to you )?(?:after|later)", re.I)
_COLLAB = re.compile(r"together|collaborat|with you|as i read|while (?:i'?m )?reading|alongside|talk (?:it |things )?through|"
                     r"back and forth|along the way|as we go|interactive|discuss as|as i go", re.I)


def x_workflow(text, direct):
    a, b = _READ_FIRST.search(text), _COLLAB.search(text)
    if a and b:
        return "read_first" if a.start() < b.start() else "collaborative"
    if a:
        return "read_first"
    if b:
        return "collaborative"
    if direct and re.fullmatch(r"\W*(alone|solo|myself|first)\W*", text, re.I):
        return "read_first"
    return None


def x_summary(text, direct):
    t = text.lower()
    if not direct and not re.search(r"summar", t):
        return None
    if re.search(r"(?:\bno\b|don'?t (?:want|need)|never|skip|without)\b[^.]{0,20}summar|summar\w*[^.]{0,20}(?:not needed|no thanks|don'?t need)", t):
        return "none"
    if re.search(r"(?:only )?(?:if|when) i ask|on request|if i want|only when asked|if needed", t):
        return "on_request"
    if re.search(r"summar\w*[^.]{0,30}\bafter(?:wards)?\b|after (?:i|reading|i'?ve)[^.]{0,30}summar|once i(?:'ve)? read|"
                 r"summary (?:at the end|later)|not (?:before|first)|afterwards|after i read", t):
        return "after_reading"
    if re.search(r"summar\w*[^.]{0,30}\bbefore\b|before[^.]{0,30}(?:read|summar)|summary first|up ?front|beforehand|"
                 r"start with a summary|summary before", t):
        return "before_reading"
    if direct and re.fullmatch(r"\W*(before|first|upfront|up front)\W*", t):
        return "before_reading"
    if direct and re.fullmatch(r"\W*(after|later|afterwards|at the end)\W*", t):
        return "after_reading"
    return None


def x_notes(text, direct):
    t = text.lower()
    if not direct and not re.search(r"\bnotes?\b|annotat|highlight|margin|jot|write down", t):
        return None
    pats = [("in_head", r"in my head|mentally|don'?t (?:really )?(?:take|write|keep) (?:any )?notes|no notes|i just remember|from memory|don'?t write"),
            ("handwritten", r"\bpens?\b|pencil|paper notebook|notebook|handwrit|by hand|print(?:ed|s)? (?:it )?out|index cards|on paper"),
            ("annotate_pdf", r"annotat|highlight|margin|comments? (?:in|on) the pdf|\bpdf\b|zotero|mark(?:ing)? up"),
            ("separate_doc", r"notion|obsidian|evernote|google docs?|\bword\b|\bdoc\b|text file|notes app|apple notes|onenote|spreadsheet|markdown|separate (?:file|doc)|laptop|typed|bullet")]
    hits = [(m.start(), val) for val, pat in pats for m in [re.search(pat, t)] if m]
    return min(hits)[1] if hits else None


EXTRACT = {"papers_reviewed": x_papers, "subarea_familiarity": x_subarea, "reading_order": x_reading,
           "workflow_mode": x_workflow, "summary_preference": x_summary, "note_habit": x_notes}


def infer_experience(papers, familiarity):
    """low / medium / high from papers reviewed and subarea familiarity; None if neither is known.
    Familiarity alone never says "high"."""
    base = None if papers is None else (0 if papers <= 2 else 1 if papers < 10 else 2)
    fam = {"unfamiliar": 0, "some": 1, "familiar": 2}.get(familiarity)
    if base is None and fam is None:
        return None
    if base is None:
        return "low" if fam == 0 else "medium"
    if fam is None:
        return ["low", "medium", "high"][base]
    if base == 0 or (fam == 0 and base == 1):
        return "low"
    return "high" if base == 2 and fam >= 1 else "medium"


# ---------------------------------------------------------------- menu and walkthrough

def menu_items():
    """The criteria menu entries, straight from definitions/venue_criteria.json (venue wording only)."""
    return venue.menu_items()


def menu_for(reviewer_id, field):
    """The venue's criteria in an order that is random across reviewers but stable for one
    reviewer and field (a re-asked question must not reshuffle). "Other" is always last."""
    items = menu_items()
    random.Random(f"{reviewer_id}:{field}").shuffle(items)
    return items + [OTHER]


def walkthrough():
    """A short tour of the review form. Part names and descriptions come only from venue_criteria.json;
    `text` names the parts in the venue's order and `parts` carries the venue's own wording for each."""
    parts = venue.parts()
    text = (f"The {venue.source()['venue']} review form has {len(parts)} parts, in this order: "
            + "; ".join(p["label"] for p in parts) + ". "
            "You can work on the parts in any order, and I will keep your draft organized by these parts.")
    return {"text": text, "parts": parts}


def parse_menu(text, menu):
    """Ids from the menu that the answer names (by number or label)."""
    picked, t = [], text.lower()
    real = [m for m in menu if m["id"] != "other"]
    for n in re.findall(r"\b\d{1,2}\b", t):
        if 1 <= int(n) <= len(real) and real[int(n) - 1]["id"] not in picked:
            picked.append(real[int(n) - 1]["id"])
    for m in real:
        if m["label"].lower() in t and m["id"] not in picked:
            picked.append(m["id"])
    return picked


# ---------------------------------------------------------------- the two entry points

def resolved(st, field):
    return field in st["evidence"] if field in EVIDENCE else field in st["fields"]


def next_field(st):
    return next((f for f in ORDER if not resolved(st, f)), None)


def level(st):
    """Experience level once it is known (inferred or defaulted), else None."""
    return (st["fields"].get("experience_level") or {}).get("value")


def _set(field, value, source, raw="", **extra):
    if field in EVIDENCE:
        return {"type": "evidence_set", "payload": {"key": field, "value": value, "source": source, "raw": raw}}
    return {"type": "profile_field_set", "payload": {"field": field, "value": value, "source": source, "raw": raw, **extra}}


def _experience_event(st, evs):
    """Emit experience_level once both pieces of evidence are in (counting this batch)."""
    ev = {k: v.get("value") for k, v in st["evidence"].items()}
    for e in evs:
        if e["type"] == "evidence_set":
            ev[e["payload"]["key"]] = e["payload"]["value"]
    if "experience_level" in st["fields"] or not all(k in ev for k in EVIDENCE):
        return []
    lvl = infer_experience(ev.get("papers_reviewed"), ev.get("subarea_familiarity"))
    if lvl is None:
        return [_set("experience_level", DEFAULTS["experience_level"], "default")]
    return [_set("experience_level", lvl, "inferred", f"papers_reviewed={ev.get('papers_reviewed')}, "
                 f"subarea_familiarity={ev.get('subarea_familiarity')}")]


def process(st, text, check=None):
    """Apply the reviewer's reply to the pending question. Returns events to log.

    `check(field, text) -> bool|None` is the optional on-topic model check (see free_text_ok)."""
    p = st["pending"]
    if not p or st["closed"]:
        return []
    field, kind = p["field"], p["kind"]
    text = (text or "").strip()[:2000]
    evs, outcome = [], "unclear"
    if field in STRUCTURED:
        val = EXTRACT[field](tidy(text), True)
        if val is not None:
            evs.append(_set(field, val, "answer", text)); outcome = "answered"
        elif is_skip(text):
            evs.append(_set(field, DEFAULTS.get(field), "default", text)); outcome = "skipped"
    elif is_nothing(text):
        if field in NONE_OK:  # a sincere "nothing": a real answer, stored as "none" (not a skip, not a default)
            evs.append(_set(field, NONE_VALUE, "answer", text)); outcome = "answered"
        # elsewhere a bare "no" is unclear: left as "unclear", so it is asked once (then defaulted)
    elif is_skip(text):
        evs.append(_set(field, DEFAULTS[field], "default", text)); outcome = "skipped"
    else:
        picked = parse_menu(text, p["menu"]) if p.get("menu") else []  # menu picks are on topic by construction
        if picked or free_text_ok(field, text, check):
            evs.append(_set(field, text, "answer", text, **({"picked": picked} if picked else {}))); outcome = "answered"
    if outcome == "unclear" and kind == "followup":
        if field in STRUCTURED:
            evs.append(_set(field, DEFAULTS.get(field), "default", ""))
        else:  # second off-topic reply: an empty value, and the junk itself is not kept anywhere
            evs.append(_set(field, "", "default", "", reason="no_answer" if is_nothing(text) else "off_topic"))
        outcome = "defaulted"
    kept = "" if outcome in ("unclear", "defaulted") else text  # replies that answered nothing are not logged
    # Extract other fields the reviewer happened to mention. Never overwrite one already set.
    if outcome in ("answered", "unclear", "defaulted") and FIRST_PERSON.search(text) and not is_skip(text):
        taken = {e["payload"].get("field") or e["payload"].get("key") for e in evs}
        for f, fn in EXTRACT.items():
            if f == field or f in taken or resolved(st, f):
                continue
            v = fn(tidy(text), False)
            if v is not None:
                evs.append(_set(f, v, "extracted", text))
    evs += _experience_event(st, evs)
    return [{"type": "onboarding_answered", "payload": {"field": field, "kind": kind, "text": kept,
                                                          "outcome": outcome, "turn": st["turn"] + 1}}] + evs


def profile_view(st):
    """The eleven profile fields (None while unset), the evidence behind experience, and status."""
    return {"fields": {f: st["fields"].get(f) for f in FIELDS},
            "evidence": {k: st["evidence"].get(k) for k in EVIDENCE},
            "turn": st["turn"], "closed": st["closed"]}


def _close(st, reason):
    evs = []
    ev = {k: v.get("value") for k, v in st["evidence"].items()}
    defaulted = []
    for f in ORDER:
        if resolved(st, f):
            continue
        if f in EVIDENCE:
            evs.append(_set(f, None, "default")); ev[f] = None
        else:
            evs.append(_set(f, DEFAULTS[f], "default"))
        defaulted.append(f)
    if "experience_level" not in st["fields"]:
        lvl = infer_experience(ev.get("papers_reviewed"), ev.get("subarea_familiarity"))
        evs.append(_set("experience_level", lvl or DEFAULTS["experience_level"], "inferred" if lvl else "default"))
        if not lvl:
            defaulted.append("experience_level")
    evs.append({"type": "onboarding_closed", "payload": {"reason": reason, "defaulted": defaulted}})
    return evs


def next_step(st, reviewer_id):
    """(events to log, response). Idempotent: with a question already pending, the same one is returned."""
    if st["closed"]:
        return [], {"done": True, "reason": st["closed"].get("reason"), "turn": st["turn"]}
    if st["pending"]:
        return [], _ask_response(st, st["pending"], st["pending"].get("walkthrough"))
    field = next_field(st)
    if field is None or st["turn"] >= MAX_TURNS:
        evs = _close(st, "complete" if field is None else "cap")
        return evs, {"done": True, "reason": evs[-1]["payload"]["reason"], "turn": st["turn"]}
    kind = "followup" if field in st["asked"] else "question"
    q = {"field": field, "kind": kind, "turn": st["turn"] + 1,
         "question": FOLLOWUPS[field] if kind == "followup" else QUESTIONS[field]}
    evs = []
    low = level(st) == "low"
    if low and field in MENU_FIELDS:
        q["menu"] = menu_for(reviewer_id, field)
        q["question"] += " Here are the venue's own criteria, in no particular order. Pick any that apply, or say it in your words."
    show_walk = low and not st["walkthrough_shown"] and kind == "question"
    q["walkthrough"] = show_walk
    if show_walk:
        evs.append({"type": "walkthrough_shown", "payload": {}})
    evs.append({"type": "onboarding_asked", "payload": q})
    return evs, _ask_response(st, q, show_walk)


def _ask_response(st, q, show_walk):
    out = {"done": False, "field": q["field"], "kind": q["kind"], "question": q["question"],
           "turn": st["turn"], "max_turns": MAX_TURNS}
    if q.get("menu"):
        out["menu"] = q["menu"]
    if show_walk:
        out["walkthrough"] = walkthrough()
    last = st["last_answer"]
    if last and last.get("text"):  # the reviewer's own words, to be echoed back, not interpreted
        out["reflect"] = " ".join(last["text"].split()[:12])
    return out
