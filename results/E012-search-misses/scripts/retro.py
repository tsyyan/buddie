"""E012 retro: the 0.3.2 search rules on the labelled samples of E006 and E008, offline, on the same snapshot bytes
the labellers read. For every labelled quote that 0.3.1 did not find on its snapshot (sealed verdict sha256), locate it
with 0.3.1 (scripts/check_031.py = check.py at d976963) and 0.3.2; a quote 0.3.2 finds and 0.3.1 did not is listed
with its blind label. A new find labelled AGENT_ALTERED / AGENT_ABSENT is an agent error the new rules hide.

Snapshots: /mnt/project-files/e006-blind-sample/sample_store/snapshots and /mnt/project-files/e008-blind-sample/snapshots
(not in git; sha256 in the experiments' verdicts_sealed.json). Writes retro.json.
"""
import json, os, sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import check_031 as old
from verbatim import check as new

LAB = Path(__file__).resolve().parents[3]
FILES = Path("/mnt/project-files")
SETS = {
    "E006": (LAB / "experiments/E006-blind-sample-v02", FILES / "e006-blind-sample/sample_store/snapshots"),
    "E008": (LAB / "experiments/E008-fresh-reports", FILES / "e008-blind-sample/snapshots"),
}
OK = {"FOUND", "FOUND_NORMALIZED"}

out = {}
for name, (exp, snaps) in SETS.items():
    items = {i["key"]: i for i in json.loads((exp / "sample_blind.json").read_text())["items"]}
    sealed = json.loads((exp / "verdicts_sealed.json").read_text())
    labels = {x["key"]: x["label"] for x in json.loads((exp / "blind_labels.json").read_text())}
    pages, rows, missing = {}, [], 0
    for key, it in items.items():
        sha = (sealed.get(key) or {}).get("sha256")
        if not sha or not (snaps / sha).exists():
            missing += 1
            continue
        if sha not in pages:
            data = (snaps / sha).read_bytes()
            pages[sha] = (old.Page(data, None), new.Page(data, None))
        po, pn = pages[sha]
        a, b = po.locate(it["quote"])["verdict"], pn.locate(it["quote"])
        if a not in OK:
            rows.append({"key": key, "label": labels.get(key), "v031": a, "v032": b["verdict"], "note": b.get("note"),
                         "tag": b.get("tag"), "repaired": pn.repaired or None})
    gained = [r for r in rows if r["v032"] in OK]
    out[name] = {"labelled": len(items), "no_snapshot": missing, "misses_031": len(rows),
                 "agent_errors_in_misses": sum(r["label"] in ("AGENT_ALTERED", "AGENT_ABSENT") for r in rows),
                 "found_by_032": gained,
                 "hidden_agent_errors": [r["key"] for r in gained if r["label"] in ("AGENT_ALTERED", "AGENT_ABSENT")],
                 "pages_repaired": sum(1 for _, p in pages.values() if p.repaired)}
    print(name, {k: v for k, v in out[name].items() if k != "found_by_032"}, flush=True)
    for r in gained:
        print("  ", r)
Path("retro.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
