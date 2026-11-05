"""The real backend with a scripted model, for the PDF-pane browser check. Usage: scripted_backend.py PORT

Everything is real (parsing, stripping of citation markers, the neutrality checks, the event log) except the model: its
replies are chosen from the reviewer's last message, and cite spans found by their text in the paper the prompt shows.
No network call is possible (the key is a dummy).
"""
import os
import re
import sys
import pathlib

os.environ.setdefault("OPENROUTER_API_KEY", "offline-no-model")
os.environ.setdefault("MODEL", "offline")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "backend"))

import uvicorn  # noqa: E402
from app import chatflow, main  # noqa: E402


def span_with(system, words):
    m = re.search(r"\[(p\d+-s\d+)\][^\n]*" + re.escape(words), system)
    return m.group(1) if m else "p9-s99"


def scripted(msgs):
    system, said = msgs[0]["content"], msgs[-1]["content"].lower()
    if "VIEW |" in system:
        return "NONE"
    m = re.match(r'describe the section "(.+)" for me', said)
    if m:   # the guided walk's short description of one section: sentences that cite that section's own passages
        title = next((t for t in re.findall(r"^## (.+)$", system, re.M) if t.lower() == m.group(1)), None)
        found = re.search(r"^## " + re.escape(title) + r"\n((?:\[p\d+-s\d+\][^\n]*\n?)+)", system, re.M) if title else None
        ids = re.findall(r"^\[(p\d+-s\d+)\]", found.group(1), re.M)[:2] if found else []
        if not ids:
            return "Nothing to describe here."
        return " ".join("This part of %s presents its text on page %d of the paper [%s]." % (title, k + 1, i)
                        for k, i in enumerate(ids))
    if "accuracy" in said:
        return "Table 2 reports accuracy on SST-2 and CoLA [%s]." % span_with(system, "Table 2")
    if "contribution" in said:
        return "The introduction lists a dataset and an analysis [%s]." % span_with(system, "Our contributions")
    if "training" in said:
        return "Training uses weak supervision [%s], with the setup described in the method [%s]." % (
            span_with(system, "weak supervision"), span_with(system, "Our contributions"))
    if "ghost" in said:
        return "That is described somewhere [p9-s99]."
    return "Sure, tell me more about what you are looking at."


chatflow._chat = scripted
uvicorn.run(main.app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
