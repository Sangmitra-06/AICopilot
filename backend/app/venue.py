"""The venue's review criteria, read from ONE file: backend/definitions/venue_criteria.json.

The onboarding menu and the form walkthrough read only from here, so replacing the placeholder text with
the venue's official wording is a data change, not a code change. Descriptions are the venue's own words;
nothing in this module adds commentary to them.

File shape:
  {"source": {"venue": str, "cycle": str, "status": str},
   "criteria": [{"id": str, "label": str, "description": str, "menu": bool (optional, default true)}]}
`menu: false` keeps a form part (for example the summary box) in the walkthrough but out of the criteria menu.
"""
import json
import logging
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.environ.get("VENUE_CRITERIA_FILE") or os.path.join(BASE, "definitions", "venue_criteria.json")
log = logging.getLogger("copilot.venue")
_cache = {"stamp": None, "data": None}


def _validate(data):
    src = data.get("source")
    if not isinstance(src, dict) or not all(isinstance(src.get(k), str) for k in ("venue", "cycle", "status")):
        raise ValueError("source must have string fields venue, cycle and status")
    if not src["venue"].strip() or not src["status"].strip():
        raise ValueError("source.venue and source.status must not be empty")
    items = data.get("criteria")
    if not isinstance(items, list) or not items:
        raise ValueError("criteria must be a non-empty list")
    seen = set()
    for i, c in enumerate(items):
        if not isinstance(c, dict):
            raise ValueError(f"criteria[{i}] must be an object")
        for k in ("id", "label", "description"):
            if not isinstance(c.get(k), str) or not c[k].strip():
                raise ValueError(f"criteria[{i}] needs a non-empty string {k!r}")
        if c["id"] in seen:
            raise ValueError(f"duplicate criterion id: {c['id']}")
        seen.add(c["id"])
        if "menu" in c and not isinstance(c["menu"], bool):
            raise ValueError(f"criteria[{i}].menu must be true or false")
    return data


def load():
    """The validated file, re-read when it changes. Raises ValueError/OSError with the file path."""
    stamp = (PATH, os.path.getmtime(PATH))
    if _cache["stamp"] != stamp:
        try:
            with open(PATH, encoding="utf-8-sig") as f:
                data = _validate(json.load(f))
        except (ValueError, TypeError) as e:  # json.JSONDecodeError is a ValueError
            raise ValueError(f"{PATH}: {e}") from e
        _cache["stamp"], _cache["data"] = stamp, data
    return _cache["data"]


def source():
    return dict(load()["source"])


def parts():
    """Every form part, in the venue's order: [{id, label, description}]."""
    return [{"id": c["id"], "label": c["label"], "description": c["description"]} for c in load()["criteria"]]


def menu_items():
    """The parts offered in the criteria menu: [{id, label, description}]."""
    return [{"id": c["id"], "label": c["label"], "description": c["description"]}
            for c in load()["criteria"] if c.get("menu", True)]


def is_placeholder():
    return "placeholder" in load()["source"]["status"].lower()


def warn_if_placeholder():
    """Called at startup: say loudly in the logs when the criteria text is not the official wording."""
    s = source()
    if is_placeholder():
        log.warning("Venue criteria in %s are marked %r (%s, %s). The onboarding menu and form walkthrough "
                    "show this placeholder text until it is replaced with the official guidelines.",
                    PATH, s["status"], s["venue"], s["cycle"])
        return True
    return False
