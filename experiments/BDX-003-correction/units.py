"""Build the experiment's units from the blind-labelled samples of E008 and E011.

A unit is one quotation in one report paragraph, with its source link and the blind label: ERROR (the agent altered
the quote or it is absent from the source) or OK (in the source). NOT_A_QUOTE, UNVERIFIABLE and TRANSLATED items
are left out. E011 has two labellers; only items they agree on are used. E010 is not used: its report text may not
be redistributed (results/README.md).

    python units.py --out data/units.json
"""
from __future__ import annotations

import argparse
from collections import Counter

from common import ERROR_LABELS, OK_LABELS, SETS, read_json, write_json


def labels_for(name: str) -> dict[str, dict]:
    d = SETS[name]
    if name == "E008":
        return {x["key"]: x for x in read_json(d / "blind_labels.json")}
    a = {x["key"]: x for x in read_json(d / "labels_A.json")}
    b = {x["key"]: x for x in read_json(d / "labels_B.json")}
    return {k: a[k] for k in a if k in b and a[k]["label"] == b[k]["label"]}


def build() -> list[dict]:
    units = []
    for name, d in SETS.items():
        sample = {x["key"]: x for x in read_json(d / "sample_blind.json")["items"]}
        sealed = read_json(d / "verdicts_sealed.json")
        for key, lab in sorted(labels_for(name).items()):
            if lab["label"] not in ERROR_LABELS | OK_LABELS or key not in sample:
                continue
            item = sample[key]
            url = lab.get("own_url") or (item["urls"] or [None])[0]
            if not url:
                continue
            v = sealed.get(key) or {}
            same_page = (v.get("url") or "").split("#", 1)[0] == url.split("#", 1)[0]
            units.append({
                "id": f"{name}:{key}", "set": name, "system": item["system"], "task": item["task"],
                "quote": item["quote"], "paragraph": item["paragraph"], "url": url,
                "gold": "ERROR" if lab["label"] in ERROR_LABELS else "OK", "label": lab["label"],
                "evidence": lab.get("evidence"),  # judge-only: never shown to a model
                "labelled_sha256": v.get("sha256") if same_page else None,
            })
    return units


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    units = build()
    write_json(a.out, {"schema": "bdx-003/units-v1", "units": units})
    print(len(units), "units", dict(Counter((u["set"], u["gold"]) for u in units)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
