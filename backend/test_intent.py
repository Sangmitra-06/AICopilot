import sys, requests

BASE = "http://127.0.0.1:8000"
PID = sys.argv[1] if len(sys.argv) > 1 else "b9215eb531"
cases = [("nothing else", "summary", "confirm"), ("idk", "summary", "ask"), ("sure", "summary", "confirm"),
         ("no", "strengths", "confirm"), ("no", "strengths", "offer"),
         ("no, I think it's fine", "weaknesses", "confirm"),
         ("nothing else matters here", "weaknesses", "ask"),
         ("yes, and also the baselines are weak", "weaknesses", "confirm"),
         ("wait, what did they say about ethics?", "weaknesses", "ask"),
         ("How many participants did they use per region?", "weaknesses", "ask"),
         ("I think five participants per region seems low", "weaknesses", "ask"),
         ("let's do soundness", "summary", "ask"), ("can we draft it now?", "strengths", "ask"),
         ("thanks!", "summary", "ask")]
for text, cid, stage in cases:
    r = requests.post(BASE + "/intent", json={"paper_id": PID, "text": text, "criterion": cid,
                                              "last_q": "", "stage": stage}, timeout=120)
    j = r.json()
    print(f"{text!r:50} [{stage:7}] -> {j['intent']:9} goto={j['goto']} via={j['via']}")