"""Table 1 of REPORT.md from data/results.json: quotes of >= 6 words per system and their verdicts."""
import collections, json

T = collections.defaultdict(collections.Counter)
for o in json.load(open("results.json")):
    for c in o["claims"]:
        if len(c["quote"].split()) < 6:
            continue
        t = T[o["system"]]
        t["quotes"] += 1
        if c["verdict"] == "SOURCE_UNAVAILABLE" or c.get("page_chars", 0) < 1500:
            t["unchecked"] += 1
            continue
        t["checked"] += 1
        t["found" if c["verdict"] in ("FOUND", "FOUND_NORMALIZED") else c["verdict"].lower()] += 1
for m, t in sorted(T.items()):
    print(m, dict(t))
