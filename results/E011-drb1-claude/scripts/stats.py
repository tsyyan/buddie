"""E011: quotes of >= 6 words and their verdicts from results.json (as E008 scripts/stats.py).

checked = the quote's page was read (any access method) and has at least 1500 visible characters.
"""
import collections, json

T = collections.defaultdict(collections.Counter)
for o in json.load(open("results.json")):
    for c in o["claims"]:
        t = T[o["system"]]
        t["quotes"] += 1
        if c["verdict"] in ("SOURCE_UNAVAILABLE", "NO_SOURCE") or c.get("page_chars", 0) < 1500:
            t["unchecked"] += 1
            continue
        t["checked"] += 1
        t[c["verdict"]] += 1
        if c.get("provenance") not in (None, "publisher") or c.get("via") not in (None, "direct"):
            t["via_" + str(c.get("via")).split()[0].split("-")[0]] += 1
for m, t in sorted(T.items()):
    print(m, dict(t))
