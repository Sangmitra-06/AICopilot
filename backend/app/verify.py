import re

BANNED = re.compile(r"\b(key|crucial|important|importantly|notably|strong|weak|impressive|"
                    r"novel|compelling|convincing|solid|flawed|promising)\b", re.I)
NUM = re.compile(r"\d+(?:\.\d+)?")


def norm(s):
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("−", "-").replace("–", "-").replace("—", "-")
    return re.sub(r"[\s\-]+", "", s).lower()


def verify(exp, by_id, page_norm=None):
    errs = []
    for i, s in enumerate(exp.sentences):
        if BANNED.search(re.sub(r'"[^"]*"', "", s.text)):
            errs.append(f"sentence {i}: evaluative wording. Describe, don't rank.")
        if s.kind == "background":
            continue
        if s.kind == "authors_claim" and not re.search(r"\b(authors?|paper|they)\b", s.text, re.I):
            errs.append(f"sentence {i}: authors' framing must be attributed to them")
        if s.source == "image":
            if not s.page:
                errs.append(f"sentence {i}: image source needs the page number")
            continue
        if s.source == "pdf":
            if not s.page or not s.quote:
                errs.append(f"sentence {i}: pdf source needs page and an exact quote")
            elif page_norm is None:
                errs.append(f"sentence {i}: pdf pages are not available; use text spans only")
            elif len(s.quote.split()) > 25:
                errs.append(f"sentence {i}: quote too long, use the shortest exact snippet")
            elif norm(s.quote) not in page_norm(s.page):
                errs.append(f"sentence {i}: quote not found on page {s.page}; copy the words exactly")
            else:
                for n in NUM.findall(s.text):
                    if n not in s.quote:
                        errs.append(f"sentence {i}: number {n} is not in the quote")
            continue
        if not s.span_ids:
            errs.append(f"sentence {i}: {s.kind} needs span_ids"); continue
        bad = [x for x in s.span_ids if x not in by_id]
        if bad:
            errs.append(f"sentence {i}: unknown span ids {bad}"); continue
        src = norm(" ".join(by_id[x]["text"] for x in s.span_ids))
        if not s.quote:
            errs.append(f"sentence {i}: add a short exact quote from the cited span")
        elif len(s.quote.split()) > 25:
            errs.append(f"sentence {i}: quote too long, use the shortest exact snippet")
        elif norm(s.quote) not in src:
            errs.append(f"sentence {i}: quote is not verbatim from the cited span")
        for n in NUM.findall(s.text):
            if n not in src:
                errs.append(f"sentence {i}: number {n} not in cited span")
    return errs