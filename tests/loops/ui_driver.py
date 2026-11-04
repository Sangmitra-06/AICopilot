"""A small model of how App.jsx reacts to a bare yes/no, so tests can run the
real chat.classify output through the same stage changes the UI makes.

Mirrors the bare-reply cases of App.jsx send(). Returns (next_stage, asked_something_new).
"""
TERMINAL = {"closed", "drafting"}

STEP = {
    "add_more": ("ask", True),          # more(c)
    "nothing_to_add": ("offer", True),  # offerClose(c)
    "move_on": ("closed", False),       # finishPart()
    "stay": ("stayed", True),           # more(c, true): buttons, no yes/no question
    "draft_now": ("drafting", False),   # draftAll()
}


def ui_step(stage, intent):
    return STEP.get(intent, (stage, False))  # 'unclear' and anything else: buttons only


def repeat_reply(classify, text, stage, turns=8):
    """Type the same bare reply `turns` times. Returns [(stage, asked_new_question)]."""
    seq = []
    for _ in range(turns):
        it = classify(text, "weaknesses", "", stage)
        stage, asked = ui_step(stage, it["intent"])
        seq.append((stage, asked))
        if stage in TERMINAL:
            break
    return seq
