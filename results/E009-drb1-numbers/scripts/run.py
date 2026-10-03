"""E009 step 3. Run in data/ after fetch.py: verbatim.numbers verdict for every number of the 100 sampled sentences.

Each number is looked for on every readable snapshot of every URL its sentence cites (a reader checks the sentence's
sources, not one of them); the best verdict wins (FOUND > FOUND_NORMALIZED > FOUND_ROUNDED > NO_CONTEXT > NOT_FOUND).
No readable snapshot of any cited URL: SOURCE_UNAVAILABLE. Writes results.json.
"""
import json

from verbatim import __version__
from verbatim.check import readable
from verbatim.numbers import NumberPage, check_sentence
from verbatim.store import Store, canonical_url

RANK = ["FOUND", "FOUND_NORMALIZED", "FOUND_ROUNDED", "NO_CONTEXT", "NOT_FOUND", "SOURCE_UNAVAILABLE"]
st = Store("store")
index = st.index()
cache = {}


def pages(url):
    u = canonical_url(url)
    if u not in cache:
        cache[u] = []
        for e in index.get(u, []):
            r = readable(st, e, u)
            if not isinstance(r, dict):
                cache[u].append((e, NumberPage(r[1].visible)))
    return cache[u]


out = []
for x in json.load(open("sample.json"))["items"]:
    best = None
    for url in x["urls"]:
        for e, pg in pages(url):
            res = check_sentence(x["sentence"], None, pg)
            for r in res:
                r.update(url=canonical_url(url), sha256=e["sha256"], via=e.get("via") or "direct")
            best = res if best is None else [min(a, b, key=lambda r: RANK.index(r["verdict"])) for a, b in zip(best, res)]
    if best is None:
        best = check_sentence(x["sentence"], None)
    for k, r in enumerate(best, 1):
        r["key"] = f"{x['key']}.{k}"
    out.append({"key": x["key"], "system": x["system"], "task": x["task"], "numbers": best})
json.dump({"tool": f"verbatim {__version__} + numbers (E009)", "items": out}, open("results.json", "w"),
          ensure_ascii=False, indent=1)
from collections import Counter
print(Counter(r["verdict"] for o in out for r in o["numbers"]))
