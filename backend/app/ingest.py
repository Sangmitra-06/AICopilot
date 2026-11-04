import re, unicodedata
from collections import Counter
import pymupdf

NAMED = ["abstract", "limitations", "ethical considerations", "acknowledgments",
         "acknowledgements", "references", "appendix"]
HEADNUM = re.compile(r"^(\d{1,2}|[A-Z])(\.\d{1,2}){0,3}\.?\s+\S")
SECNUM = re.compile(r"^(\d{1,2}|[A-Z])(\.\d{1,2}){0,3}\.?$")
CAPTION = re.compile(r"^(Figure|Fig\.|Table)\s*\d+\s*[:.]")
CHUNK_MIN, CHUNK_MAX = 350, 800
INFO = {}
VOCAB = {}
PAGES = {}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKC", s).lower())


NAMEDN = {norm(x) for x in NAMED}


def build_vocab(pages):
    v = Counter()
    for pg in pages:
        for l in pg["lines"]:
            t = l["text"]
            if t.endswith("-"):
                t = t.rsplit(None, 1)[0] if " " in t else ""
            v.update(w.lower() for w in re.findall(r"[A-Za-z]+(?:-[A-Za-z]+)*", t))
    return v


def joined_text(buf, vocab):
    out = ""
    for l in buf:
        t = l["text"]
        if out:
            a = re.search(r"([A-Za-z]+)-$", out)
            b = re.match(r"([A-Za-z]+)", t)
            if a and b:
                x, y = a.group(1).lower(), b.group(1).lower()
                if vocab.get(x + "-" + y):
                    pass
                elif vocab.get(x + y):
                    out = out[:-1]
                elif vocab.get(x) and vocab.get(y):
                    pass
                else:
                    out = out[:-1]
                out += t
                continue
            out += " "
        out += t
    return out


def locate(span, quote):
    hay, needle = norm(span["text"]), norm(quote)
    i = hay.find(needle) if needle else -1
    if i < 0:
        return None
    j = i + len(needle) - 1
    prev, nums = 0, []
    for cum, n in span["segs"]:
        if cum > i and prev <= j and n is not None:
            nums.append(n)
        prev = cum
    return [min(nums), max(nums)] if nums else None


def join_spans(spans):
    out, prev = "", None
    for s in spans:
        t = s["text"]
        if prev is not None and s["bbox"][0] - prev["bbox"][2] > 1.5 \
                and not out.endswith(" ") and not t.startswith(" "):
            out += " "
        out += t
        prev = s
    return " ".join(out.split())


def find_columns(cands, W):
    margin = sorted((c for c in cands if c["x"] < .15 * W or c["x"] > .85 * W),
                    key=lambda c: c["x"])
    groups, cur = [], []
    for c in margin:
        if cur and c["x"] - cur[-1]["x"] > 8:
            groups.append(cur); cur = []
        cur.append(c)
    if cur:
        groups.append(cur)
    cols = []
    for g in groups:
        g = sorted(g, key=lambda c: c["y"])
        if len(g) < 8:
            continue
        diffs = [b["n"] - a["n"] for a, b in zip(g, g[1:])]
        if sum(1 for d in diffs if 1 <= d <= 3) / len(diffs) < .7:
            continue
        ys = sorted(b["y"] - a["y"] for a, b in zip(g, g[1:]))
        sp = ys[len(ys) // 2]
        if sp < 5:
            continue
        cols.append({"side": "L" if g[0]["x"] < .5 * W else "R", "spacing": sp,
                     "nums": [(c["n"], c["y"]) for c in g], "members": g})
    return cols


def assign(ln, cols, W, single):
    full = ln["x0"] < .42 * W and ln["x1"] > .58 * W
    side = "L" if (ln["x0"] + ln["x1"]) / 2 < .5 * W else "R"
    best = None
    for c in cols:
        if not (full or single) and c["side"] != side:
            continue
        for n, y in c["nums"]:
            d = abs(y - ln["y"])
            if d <= .55 * c["spacing"] and (best is None or d < best[0]):
                best = (d, n)
    return best[1] if best else None


def read_page(page):
    W = page.rect.width
    raw, cands = [], []
    for bi, b in enumerate(page.get_text("dict")["blocks"]):
        if b.get("type") != 0:
            continue
        for ln in b["lines"]:
            raw.append((bi, ln["spans"]))
            for sp in ln["spans"]:
                t = sp["text"].strip()
                if re.fullmatch(r"\d{1,4}", t):
                    x0, y0, x1, y1 = sp["bbox"]
                    cands.append({"n": int(t), "x": (x0 + x1) / 2, "y": (y0 + y1) / 2, "id": id(sp)})
    cols = find_columns(cands, W)
    drop = {c["id"] for col in cols for c in col["members"]}
    lines = []
    for bi, spans in raw:
        keep = [s for s in spans if id(s) not in drop and s["text"].strip()]
        if not keep:
            continue
        text = join_spans(keep)
        if not text:
            continue
        chars = sum(len(s["text"]) for s in keep) or 1
        bold = sum(len(s["text"]) for s in keep
                   if (s["flags"] & 16) or "bold" in s["font"].lower()) / chars
        y0, y1 = min(s["bbox"][1] for s in keep), max(s["bbox"][3] for s in keep)
        lines.append({"block": bi, "text": text, "y0": y0, "y1": y1, "y": (y0 + y1) / 2,
                      "x0": min(s["bbox"][0] for s in keep), "x1": max(s["bbox"][2] for s in keep),
                      "size": max(keep, key=lambda s: len(s["text"]))["size"],
                      "bold": bold, "num": None})
    lc = sum(1 for l in lines if l["x1"] < .53 * W)
    rc = sum(1 for l in lines if l["x0"] > .47 * W)
    single = len({c["side"] for c in cols}) < 2 and min(lc, rc) < 8
    for ln in lines:
        ln["num"] = assign(ln, cols, W, single)
    return {"W": W, "lines": lines, "cols": cols, "single": single}


def match_toc(pages, toc):
    pend = {}
    for _, title, pg_no in toc:
        pend.setdefault(pg_no, []).append(norm(title))
    hits = 0
    for pno, pg in enumerate(pages, 1):
        want, L, i = pend.get(pno, []), pg["lines"], 0
        while i < len(L):
            done = False
            for k in range(4):
                if i + k >= len(L):
                    break
                cat = norm("".join(l["text"] for l in L[i:i + k + 1]))
                if cat and cat in want:
                    for l in L[i:i + k + 1]:
                        l["toc_head"] = True
                    want.remove(cat); hits += 1; i += k + 1; done = True
                    break
            if not done:
                i += 1
    return hits


def font_heading(l, body):
    t = l["text"]
    if not 3 <= len(t) <= 100 or t.endswith((",", ";", ":")):
        return False
    big = body + .8 <= l["size"] <= body + 3.5
    return (l["bold"] >= .9 or big) and (bool(HEADNUM.match(t)) or big)


def make(sid, pno, pg, buf, section, body):
    W = pg["W"]
    x0, y0 = min(l["x0"] for l in buf), min(l["y0"] for l in buf)
    x1, y1 = max(l["x1"] for l in buf), max(l["y1"] for l in buf)
    ns = [l["num"] for l in buf if l["num"] is not None]
    approx = False
    if not ns:
        full = x0 < .42 * W and x1 > .58 * W
        side = "L" if (x0 + x1) / 2 < .5 * W else "R"
        ns = [n for c in pg["cols"] if full or pg["single"] or c["side"] == side
              for n, y in c["nums"] if y0 - 3 <= y <= y1 + 3]
        approx = bool(ns)
    sizes = sorted(l["size"] for l in buf)
    text = joined_text(buf, VOCAB)
    segs, cum = [], 0
    for l in buf:
        cum += len(norm(l["text"]))
        segs.append([cum, l["num"]])
    if CAPTION.match(text):
        kind = "caption"
    elif ns or not pg["cols"]:
        kind = "body"
    else:
        kind = "loose"
    return {"id": sid, "page": pno, "bbox": [x0, y0, x1, y1], "section": section,
            "text": text, "lines": [min(ns), max(ns)] if ns else None,
            "lines_approx": approx, "kind": kind, "segs": segs,
            "small": sizes[len(sizes) // 2] < body - .8}


def ingest(pdf_path: str):
    doc = pymupdf.open(pdf_path)
    pages = [read_page(p) for p in doc]
    VOCAB.clear(); VOCAB.update(build_vocab(pages))
    sizes = Counter()
    for pg in pages:
        for l in pg["lines"]:
            sizes[round(l["size"], 1)] += len(l["text"])
    body = sizes.most_common(1)[0][0] if sizes else 10.0
    toc = doc.get_toc(simple=True)
    hits = match_toc(pages, toc) if toc else 0
    use_toc = len(toc) >= 3 and hits >= .6 * len(toc)
    for pg in pages:
        for l in pg["lines"]:
            named = norm(l["text"]) in NAMEDN and (l["bold"] >= .9 or l["size"] >= body + .8)
            l["is_head"] = (l.get("toc_head", False) or named) if use_toc \
                else (named or font_heading(l, body))
    for pg in pages:
        L = pg["lines"]
        for i, l in enumerate(L):
            if l["is_head"] or not SECNUM.match(l["text"]):
                continue
            for j in (i - 1, i + 1):
                if 0 <= j < len(L) and L[j]["is_head"] and abs(L[j]["y"] - l["y"]) < 5:
                    l["is_head"] = True
                    break

    spans, heads, st = [], [], {"section": "Front matter", "head": []}

    def close(pno):
        if st["head"]:
            h = st["head"]
            if len(h) == 2 and abs(h[0]["y"] - h[1]["y"]) < 5:
                h = sorted(h, key=lambda l: l["x0"])
            st["section"] = " ".join(l["text"] for l in h)
            heads.append({"page": pno, "text": st["section"],
                          "nums": [l["num"] for l in h if l["num"]]})
            st["head"] = []

    for pno, pg in enumerate(pages, 1):
        buf, blk, k = [], None, 0
        for ln in pg["lines"] + [None]:
            end = ln is None
            if buf and (end or ln["block"] != blk or ln["is_head"]):
                spans.append(make(f"p{pno}-s{k}", pno, pg, buf, st["section"], body)); k += 1; buf = []
            if st["head"] and (end or not ln["is_head"] or
                               (ln["block"] != blk and not SECNUM.match(st["head"][-1]["text"]))):
                close(pno)
            if end:
                break
            blk = ln["block"]
            if ln["is_head"]:
                st["head"].append(ln); continue
            buf.append(ln)
            t = " ".join(l["text"] for l in buf)
            if len(t) >= CHUNK_MAX or (len(t) >= CHUNK_MIN and ln["text"].endswith((".", "?", "!"))):
                spans.append(make(f"p{pno}-s{k}", pno, pg, buf, st["section"], body)); k += 1; buf = []

    INFO.clear()
    INFO.update(mode="bookmarks" if use_toc else "fonts", toc=len(toc), hits=hits, body=body,
                pages=len(pages), num_pages=sum(1 for pg in pages if pg["cols"]),
                nonum=[i for i, pg in enumerate(pages, 1) if not pg["cols"]], headings=heads,
                numbers={n for pg in pages for c in pg["cols"] for n, _ in c["nums"]})
    return spans


def page_data(path, pno):
    k = (path, pno)
    if k not in PAGES:
        PAGES[k] = read_page(pymupdf.open(path)[pno - 1])
    return PAGES[k]


def page_plain(path, pno):
    return " ".join(l["text"] for l in page_data(path, pno)["lines"])


def add_span(path, pno, quote, n):
    pg = page_data(path, pno)
    parts = [(norm(l["text"]), l) for l in pg["lines"]]
    hay, needle = "".join(p for p, _ in parts), norm(quote)
    i = hay.find(needle) if needle else -1
    if i < 0:
        return None
    j, pos, used = i + len(needle) - 1, 0, []
    for p, l in parts:
        if pos + len(p) > i and pos <= j:
            used.append(l)
        pos += len(p)
    ns = [l["num"] for l in used if l["num"] is not None]
    return {"id": f"u{pno}-{n}", "page": pno,
            "bbox": [min(l["x0"] for l in used), min(l["y0"] for l in used),
                     max(l["x1"] for l in used), max(l["y1"] for l in used)],
            "section": "Added from PDF", "text": quote,
            "lines": [min(ns), max(ns)] if ns else None, "lines_approx": False,
            "kind": "added", "segs": [], "small": False}