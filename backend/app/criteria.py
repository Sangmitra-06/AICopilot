import glob, json, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.environ.get("CRITERIA_FILE") or os.path.join(BASE, "criteria.json")
DEFS = os.path.join(BASE, "definitions")
LEGACY = {"P": "summary", "S": "strengths", "W": "weaknesses", "Q": "comments"}
_cache = {"stamp": None, "data": None, "error": ""}


def val(x):
    s = str(x).strip()
    try:
        f = float(s)
        return str(int(f)) if f.is_integer() else str(f)
    except ValueError:
        return s


def _read():
    with open(PATH, encoding="utf-8-sig") as f:
        data = json.load(f)
    ids = set()
    for c in data["criteria"]:
        cid = c["id"]
        if cid in ids:
            raise ValueError(f"duplicate id: {cid}")
        ids.add(cid)
        c.setdefault("tab", c["name"])
        c.setdefault("type", "text")
        c.setdefault("definition", "")
        c.setdefault("scale", [])
        c.setdefault("required", True)
        c.setdefault("list", False)
        c.setdefault("style", "judge")
        fp = os.path.join(DEFS, cid + ".txt")
        if os.path.exists(fp):
            with open(fp, encoding="utf-8-sig") as g:
                txt = g.read().strip()
            if txt:
                c["definition"] = txt
        c["has_definition"] = bool(c["definition"].strip()) and "PASTE" not in c["definition"]
        c["scale"] = [{"value": val(x["value"]), "label": x.get("label", "")} for x in c["scale"]]
    data.setdefault("gate", True)
    data.setdefault("fact_gate", True)
    data.setdefault("allow_dispute", True)
    return data


def load():
    files = [PATH] + sorted(glob.glob(os.path.join(DEFS, "*.txt")))
    stamp = tuple((p, os.path.getmtime(p)) for p in files)
    if _cache["stamp"] != stamp:
        _cache["stamp"] = stamp
        try:
            _cache["data"] = _read()
            _cache["error"] = ""
        except Exception as e:
            _cache["error"] = f"{type(e).__name__}: {e}"
            print("[criteria] PROBLEM:", _cache["error"])
            if _cache["data"] is None:
                raise
    return {**_cache["data"], "error": _cache["error"]}


def items():
    return load()["criteria"]


def by_id():
    return {c["id"]: c for c in items()}


def fix(field):
    return LEGACY.get(field, field) if field else ""