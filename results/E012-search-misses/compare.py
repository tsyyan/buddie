"""E012: put the three measurements together. Run from this folder after scripts/retro.py, scripts/e011.py,
scripts/run.py and the blind labels: writes comparison.json.

1. retro.json   - E006 and E008 labelled samples, 0.3.1 vs 0.3.2 on the labellers' own snapshot bytes
2. e011.json    - E011's 34 checked misses re-read now, 0.3.1 vs 0.3.2 on the same bytes
3. summary.json + labels_A/B.json + verdicts_sealed.json - fresh DRB I reports: every miss of 0.3.2, blind labels
"""
import hashlib, json
from collections import Counter
from pathlib import Path

retro = json.loads(Path("retro.json").read_text())
e011 = json.loads(Path("e011.json").read_text())
summ = json.loads(Path("summary.json").read_text())
sealed_bytes = Path("verdicts_sealed.json").read_bytes()
sample = json.loads(Path("sample_blind.json").read_text())
assert hashlib.sha256(sealed_bytes).hexdigest() == sample["verdicts_sealed_sha256"]
sealed = json.loads(sealed_bytes)
a = {x["key"]: x["label"] for x in json.loads(Path("labels_A.json").read_text())}
b = {x["key"]: x["label"] for x in json.loads(Path("labels_B.json").read_text())}
agree = [k for k in sealed if a[k] == b[k]]
table = Counter((a[k] if a[k] == b[k] else "DISAGREE", sealed[k]["verdict"]) for k in sealed)
AGENT = ("AGENT_ALTERED", "AGENT_ABSENT")
doc = {
    "retro": {name: {k: v for k, v in r.items() if k != "found_by_032"} | {"found_by_032": [x["key"] for x in r["found_by_032"]]}
              for name, r in retro.items()},
    "retro_agent_errors_hidden": sum(len(r["hidden_agent_errors"]) for r in retro.values()),
    "retro_agent_errors_in_misses": sum(r["agent_errors_in_misses"] for r in retro.values()),
    "e011": {k: v for k, v in e011.items() if k != "rows"} | {
        "agent_errors_read_now": sum(1 for r in e011["rows"] if "AGENT_" in r["label"] and "unread" not in r),
        "false_not_found_031": ["F001", "F031", "F064", "F074"]},
    "fresh": {"quotes": summ["quotes"], "checked": summ["checked"], "verdicts_032": summ["verdicts_032"],
              "found_by_032_only": len(summ["found_by_032_only"]), "blind_misses": len(sealed),
              "agreement": {"same": len(agree), "n": len(sealed)},
              "table": {f"{l}|{v}": n for (l, v), n in sorted(table.items())},
              "in_source_misses": [k for k in agree if a[k] == "IN_SOURCE"],
              "agent_errors": [k for k in agree if a[k] in AGENT]},
}
Path("comparison.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
print(json.dumps(doc, ensure_ascii=False, indent=1))
