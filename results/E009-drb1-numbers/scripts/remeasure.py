"""E009 step 4 (NEXT №42). Run in data/ after fetch.py: the 100 sampled sentences again, with the verbatim on
PYTHONPATH, against the labels A and B (no new labelling: the labels are about the reports and the cited pages).

Writes results_<verbatim version>.json and summary_<verbatim version>.json. Sentence URLs come from
`verbatim.numbers.cites` when this verbatim has it (0.3.4: Gemini footnotes after a space), else from sample.json.
A verbatim without the new gate checks run on the same snapshots is the baseline: the snapshots were taken again on
2026-10-03 (data/ of 2026-10-02 is not in git), so the 2026-10-02 verdicts are not comparable page for page.
"""
import json, re, sys
from collections import Counter
from pathlib import Path

from verbatim import __version__
from verbatim import numbers as nb
from verbatim.check import readable
from verbatim.store import Store, canonical_url

HERE = Path(__file__).resolve().parents[1]
RANK = getattr(nb, "RANK", ["FOUND", "FOUND_NORMALIZED", "FOUND_ROUNDED", "NO_CONTEXT", "NOT_FOUND", "SOURCE_UNAVAILABLE"])
A = {x["key"]: x for x in json.load(open(HERE / "labels_A.json"))}
B = {x["key"]: x for x in json.load(open(HERE / "labels_B.json"))}
label = {k: A[k]["label"] if A[k]["label"] == B[k]["label"] else "DISAGREE" for k in A}
ATTRIBUTION = {"S003", "S007", "S011"}  # checked against another footnote's URL on 2026-10-02 (REPORT, limitation 1)
st = Store("store")
index = st.index()
cache, gates = {}, {}

articles = {}
for m in ("gemini-2.5-pro-deepresearch",):
    for line in open(m + ".jsonl"):
        r = json.loads(line)
        articles[(m, r["id"])] = r["article"]


def urls_of(x):
    if hasattr(nb, "cites") and x["system"].startswith("gemini"):
        return nb.cites(x["sentence"], nb.note_sources(articles[(x["system"], x["task"])]), True)
    return x["urls"]


def pages(url):
    u = canonical_url(url)
    if u not in cache:
        cache[u] = []
        for e in index.get(u, []):
            r = readable(st, e, u)
            if isinstance(r, dict):
                gates.setdefault(u, []).append(r["error"][:120])
            else:
                cache[u].append((e, nb.NumberPage(r[1].visible, *([nb.page_doubts(e, u)] if hasattr(nb, "page_doubts") else []))))
    return cache[u]


out, verdict = [], {}
for x in json.load(open("sample.json"))["items"]:
    urls, best = urls_of(x), None
    for url in urls:
        for e, pg in pages(url):
            res = nb.check_sentence(x["sentence"], None, pg)
            for r in res:
                r.update(url=canonical_url(url), sha256=e["sha256"], via=e.get("via") or "direct")
            best = res if best is None else [min(a, b, key=lambda r: RANK.index(r["verdict"])) for a, b in zip(best, res)]
    if best is None:
        best = nb.check_sentence(x["sentence"], None)
    for k, r in enumerate(best, 1):
        r["key"] = f"{x['key']}.{k}"
        verdict[r["key"]] = r["verdict"]
    out.append({"key": x["key"], "system": x["system"], "urls": urls, "numbers": best})
json.dump({"tool": f"verbatim {__version__}", "items": out}, open(f"results_{__version__}.json", "w"),
          ensure_ascii=False, indent=1)

CHECKABLE, ERROR = {"IN_SOURCE", "WRONG_VALUE", "ABSENT", "DERIVED"}, {"WRONG_VALUE", "ABSENT"}
FOUND, FLAG = {"FOUND", "FOUND_NORMALIZED", "FOUND_ROUNDED"}, {"NOT_FOUND", "NO_CONTEXT"}


def rates(keys):
    chk = [k for k in keys if label[k] in CHECKABLE]
    err = [k for k in chk if label[k] in ERROR]
    nf = [k for k in keys if verdict[k] == "NOT_FOUND"]
    return {
        "numbers": len(keys), "checkable": len(chk), "agent_errors": len(err),
        "false_not_found": [k for k in chk if label[k] == "IN_SOURCE" and verdict[k] == "NOT_FOUND"],
        "in_source_no_context": [k for k in chk if label[k] == "IN_SOURCE" and verdict[k] == "NO_CONTEXT"],
        "in_source_unavailable": [k for k in chk if label[k] == "IN_SOURCE" and verdict[k] == "SOURCE_UNAVAILABLE"],
        "errors_caught": len([k for k in err if verdict[k] in FLAG]),
        "errors_missed_as_found": [k for k in err if verdict[k] in FOUND],
        "errors_unavailable_to_tool": [k for k in err if verdict[k] == "SOURCE_UNAVAILABLE"],
        "not_found": len(nf),
        "not_found_by_label": dict(Counter(label[k] for k in nf).most_common()),
        "unverifiable_not_found": [k for k in keys if label[k] == "UNVERIFIABLE" and verdict[k] == "NOT_FOUND"],
        "unverifiable_flagged": [k for k in keys if label[k] == "UNVERIFIABLE" and verdict[k] in FLAG],
        "unverifiable_found": [k for k in keys if label[k] == "UNVERIFIABLE" and verdict[k] in FOUND],
        "uncertain": [k for k in keys if verdict[k] == "UNCERTAIN"],  # 0.3.6 (NEXT №66)
        "errors_uncertain": [k for k in err if verdict[k] == "UNCERTAIN"],
    }


keys = sorted(verdict, key=lambda k: (k[:4], int(k.split(".")[1])))
years = [k for k in keys if next(r for o in out for r in o["numbers"] if r["key"] == k)["kind"] == "year"]
summary = {
    "tool": f"verbatim {__version__}",
    "all": rates(keys),
    "adjusted": rates([k for k in keys if k[:4] not in ATTRIBUTION]),
    "years": rates(years),
    "confusion": {f"{l} / {v}": n for (l, v), n in sorted(Counter((label[k], verdict[k]) for k in keys).items())},
    "unreadable_snapshots": {u: g for u, g in sorted(gates.items())},
}
json.dump(summary, open(f"summary_{__version__}.json", "w"), ensure_ascii=False, indent=1)
for part in ("all", "adjusted", "years"):
    s = summary[part]
    print(part, {k: (len(v) if isinstance(v, list) else v) for k, v in s.items()})
