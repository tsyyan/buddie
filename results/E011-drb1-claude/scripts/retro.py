"""E011: what the 0.3.1 hints change on the earlier blind samples, E008 and E010 (run in data/, needs report_030.py).

Each labelled item's report paragraph is read as a one-block report under 0.3.0 (report_030) and 0.3.1 rules; an item
whose quote gets a kind only under 0.3.1 and whose verdict was a miss (NOT_FOUND / UNCERTAIN) would turn NOT_A_QUOTE.
E010 is where the hints came from (in sample); E008 was read when 0.3.0 was written but not for these hints.
E008 labels are the consensus of blind_labels.json; E010 counts an item only when labellers A and B agree.
"""
import json, os, sys
from pathlib import Path

sys.path.insert(0, os.getcwd())
import report_030
from verbatim import report

EXP = Path(__file__).resolve().parents[2]
AGENT = ("AGENT_ALTERED", "AGENT_ABSENT")


def kinds(item):
    def kind(mod):
        cl = [c for c in mod.from_markdown(item["paragraph"] + "\n")[0] if c["quote"] == item["quote"]]
        return cl[0].get("not_quote") if cl else "?"
    return kind(report_030), kind(report)


def labels(exp):
    d = EXP / exp
    if exp.startswith("E010"):
        a = {x["key"]: x["label"] for x in json.load(open(d / "labels_A.json"))}
        b = {x["key"]: x["label"] for x in json.load(open(d / "labels_B.json"))}
        return {k: a[k] if a[k] == b.get(k) else "DISAGREE" for k in a}
    return {x["key"]: x["label"] for x in json.load(open(d / "blind_labels.json"))}


out = {}
for exp in ("E008-fresh-reports", "E010-not-a-quote"):
    d = EXP / exp
    items = json.load(open(d / "sample_blind.json"))["items"]
    sealed = json.load(open(d / "verdicts_sealed.json"))
    lab = labels(exp)
    new, lost = [], []
    for it in items:
        k030, k031 = kinds(it)
        v = sealed[it["key"]]["verdict"]
        miss = v in ("NOT_FOUND", "UNCERTAIN") or (v == "NOT_A_QUOTE" and sealed[it["key"]].get("miss"))
        if k031 and k031 != "?" and not k030 and miss:
            new.append({"key": it["key"], "verdict": v, "label": lab.get(it["key"])})
        if k030 and not k031:
            lost.append(it["key"])
    by = {}
    for n in new:
        by[n["label"]] = by.get(n["label"], 0) + 1
    out[exp[:4]] = {"items": len(items), "agent_errors": sum(lab.get(i["key"]) in AGENT for i in items),
                    "newly_not_a_quote": len(new), "labels": by, "items_new": new, "kind_lost": lost}
print(json.dumps(out, indent=1))
Path("retro.json").write_text(json.dumps(out, indent=1) + "\n")
