import sys, requests

BASE = "http://127.0.0.1:8000"
PID = sys.argv[1] if len(sys.argv) > 1 else "b9215eb531"
cases = ["I think five participants per region seems low",
         "The writing is hard to follow",
         "I didn't understand how the gold answers were built",
         "The abstract is confusing",
         "The evaluation relies on an LLM judge",
         "I like the overall idea",
         "Interesting choice of regions"]
for t in cases:
    r = requests.post(BASE + "/help/plan", json={"paper_id": PID, "criterion": "weaknesses", "text": t}, timeout=120)
    print(f"{t!r:58} -> {r.json()}")