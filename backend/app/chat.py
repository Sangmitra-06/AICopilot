import json, re
from . import criteria
from .llm import _chat

DONE = re.compile(r"^\s*(nothing( else| more)?( to add)?|none|that'?s (all|it)( for (now|this))?|i'?m (done|good|finished)|done|"
                  r"no more|enough|all good|move on|next( part)?|skip( this| it)?|pass|no comment)\W*$", re.I)
DK = re.compile(r"^\s*(i don'?t know|idk|dunno|not sure|no idea|i'?m not sure|unsure|what do you mean|huh)\W*$", re.I)
YES = re.compile(r"^\s*(yes|yeah|yep|yup|y|sure|ok(ay)?|alright|please|go on|go ahead|add more|more)\W*$", re.I)
NO = re.compile(r"^\s*(no|nope|nah|n|not (really|yet))\W*$", re.I)
ALLOWED = {"answer", "done", "dontknow", "question", "goto", "other"}

# A bare yes/no only means something relative to the question just asked, so it is
# resolved here by stage. Anything not listed answers nothing at that stage.
#   confirm: "Anything to add?"   offer: "Move on?"   ask: an open question
#   draft: "Draft my review?"     stayed: the reviewer already declined to move on
BARE = {
    ("confirm", "yes"): "add_more", ("confirm", "no"): "nothing_to_add",
    ("offer", "yes"): "move_on", ("offer", "no"): "stay",
    ("ask", "no"): "nothing_to_add",
    ("draft", "yes"): "draft_now",
}


def bare(stage, polarity):
    return BARE.get((stage, polarity), "unclear")

INTENT_SYS = """You label one message from a paper reviewer who is being asked questions about one part of a review form.
Return JSON {"intent": "answer"|"done"|"dontknow"|"question"|"goto"|"other", "goto": str|null}.
answer: the reviewer states their own view, description, or point for this part (even if short or hedged).
done: nothing more to add, wants to move on, or has no comment.
dontknow: unsure, or asks what the question means.
question: asks something about the paper itself (a fact, where something is, what a term means) that is not their own view.
goto: wants to talk about a different part of the form. Put that part's id in "goto". Use "draft" if they want to see or draft the review.
other: anything else (greetings, thanks, off-topic).
You are given the assistant's last question and the stage of the conversation. Read the message in that context.
If a message mixes a view with a question or with a refusal (for example "no, I think it is fine"), label it answer, because the view should be saved.
Never judge whether an answer is good, complete, or enough. Only say what the reviewer is doing with the message."""


def lookup():
    m = {"draft": "draft", "review": "draft", "the review": "draft"}
    for c in criteria.items():
        for k in (c["id"], c["name"], c["tab"]):
            m[k.lower()] = c["id"]
    return m


def classify(text, cid, last_q, stage=""):
    t = (text or "").strip()
    if DONE.match(t):
        return {"intent": "done", "goto": None, "via": "rule"}
    if DK.match(t):
        return {"intent": "dontknow", "goto": None, "via": "rule"}
    if YES.match(t):
        return {"intent": bare(stage, "yes"), "goto": None, "via": "rule"}
    if NO.match(t):
        return {"intent": bare(stage, "no"), "goto": None, "via": "rule"}
    parts = "\n".join(f"{c['id']}: {c['name']}" for c in criteria.items())
    cur = criteria.by_id().get(cid, {}).get("name", "(none yet)")
    user = (f"Current part: {cur}\nStage of the conversation: {stage or '(none)'}\n"
            f"The assistant's last question: {last_q or '(none)'}\n"
            f"Parts of the form:\n{parts}\nReviewer's message: {t}")
    try:
        j = json.loads(_chat([{"role": "system", "content": INTENT_SYS}, {"role": "user", "content": user}]))
        intent = j.get("intent")
        if intent not in ALLOWED:
            raise ValueError("bad intent")
        goto = None
        if intent == "goto":
            goto = lookup().get(str(j.get("goto") or "").strip().lower())
            if not goto:
                intent = "other"
        return {"intent": intent, "goto": goto, "via": "model"}
    except Exception as e:
        print("[intent] model failed:", repr(e)[:200])
        # Fail safe: an unreadable message is never guessed to be an answer, because answers are saved.
        return {"intent": "unread", "goto": None, "via": "fallback"}