"""The owner's blind audit (PROTOCOL 2026-11-02) joined with the key of the sheet it was read from: agreement with the
judge per outcome, and per arm or condition, as GitHub notices (the key stays in the run; nothing here names an arm
before the join).

    python audit_report.py --owner audit/audit_owner_api.csv --key data/judged/audit_key.json --by arm --title API
    python audit_report.py --owner audit/audit_owner_product.csv --key product-data/judged/audit_key.json \
        --by condition --title product
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--by", required=True, help="arm (API) or condition (product)")
    ap.add_argument("--title", required=True)
    a = ap.parse_args(argv)
    key = {k["row"]: k for k in json.loads(Path(a.key).read_text(encoding="utf-8"))}
    rows = list(csv.DictReader(open(a.owner, encoding="utf-8", newline="")))
    missing = [r["row"] for r in rows if int(r["row"]) not in key]
    if missing:
        print(f"::error title=BDX-003 audit {a.title}::rows not in the key: {missing[:10]}")
        return 1
    agree = Counter()
    per_outcome = defaultdict(Counter)
    per_group = defaultdict(Counter)
    off = []
    for r in rows:
        k = key[int(r["row"])]
        group = f"{k.get('model', '')} {k[a.by]}".strip()
        same = r["owner_outcome"] == r["auto_outcome"]
        agree[same] += 1
        per_outcome[r["auto_outcome"]][same] += 1
        per_group[group][same] += 1
        if not same:
            off.append(f"row {r['row']} {group}: judge {r['auto_outcome']}, owner {r['owner_outcome']}")
    n = len(rows)
    lines = [f"{n} rows read; agree {agree[True]} ({agree[True] / n:.2f}), disagree {agree[False]}",
             "by judge outcome: " + "; ".join(f"{o} {c[True]}/{c[True] + c[False]}" for o, c in sorted(per_outcome.items())),
             f"by {a.by}: " + "; ".join(f"{g} {c[True]}/{c[True] + c[False]}" for g, c in sorted(per_group.items())),
             "disagreements: " + " || ".join(off)]
    for i, line in enumerate(lines, 1):
        print(f"::notice title=BDX-003 audit {a.title} {i}::{line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
