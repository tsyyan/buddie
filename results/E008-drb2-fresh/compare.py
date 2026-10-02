"""E008: blind labels (blind_labels.json, committed before unsealing) against verbatim's sealed verdicts
(verdicts_sealed.json from branch e008-sealed-verdicts, sha256 checked against sample_blind.json).
Run from this directory: python compare.py -> comparison.json

Every checked miss is labelled, so rates over checked quotes are counted, not extrapolated. The CONTROLS random finds
estimate how many agent errors a find hides (recall denominator).
"""
import hashlib, json, math
from collections import Counter, defaultdict

sample = json.load(open("sample_blind.json"))
raw = open("verdicts_sealed.json", "rb").read()
assert hashlib.sha256(raw).hexdigest() == sample["verdicts_sealed_sha256"], "sealed verdicts do not match the sample"
verdicts = json.loads(raw)
labels = {x["key"]: x for x in json.load(open("blind_labels.json"))}
assert set(labels) == set(verdicts), "every item needs exactly one label"
AGENT = {"AGENT_ALTERED", "AGENT_ABSENT"}
STRICT_FA = {"IN_SOURCE", "NOT_A_QUOTE", "TRANSLATED"}  # NOT_FOUND on these is a false alarm
OK = {"FOUND", "FOUND_NORMALIZED", "FOUND_IN_COPY"}
pool = sample["pool"]
checked = pool["checked_misses"] + pool["checked_finds"]


def wilson(k, n, z=1.96):
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round((c - h) / d, 4), round((c + h) / d, 4)]


def rate(k, n):
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None, "ci95": wilson(k, n)}


table = defaultdict(Counter)
doubts = defaultdict(Counter)
by_system = defaultdict(lambda: defaultdict(Counter))
system = {s["key"]: s["system"] for s in sample["items"]}
for k, lab in labels.items():
    v = verdicts[k]["verdict"]
    table[lab["label"]][v] += 1
    by_system[system[k]][lab["label"]][v] += 1
    for d in verdicts[k].get("doubts") or []:
        doubts[d][lab["label"]] += 1
keys = sorted(labels)
nf = [k for k in keys if verdicts[k]["verdict"] == "NOT_FOUND"]
unc = [k for k in keys if verdicts[k]["verdict"] == "UNCERTAIN"]
ctl = [k for k in keys if verdicts[k]["verdict"] in OK]
strict = [k for k in nf if labels[k]["label"] in STRICT_FA]
unver = [k for k in nf if labels[k]["label"] == "UNVERIFIABLE"]
agent_nf = [k for k in nf if labels[k]["label"] in AGENT]
agent_unc = [k for k in unc if labels[k]["label"] in AGENT]
agent_ctl = [k for k in ctl if labels[k]["label"] in AGENT]
ok_ctl = [k for k in ctl if labels[k]["label"] == "IN_SOURCE"]
# agent errors hidden among all checked finds, scaled from the random controls
hidden = len(agent_ctl) / len(ctl) * pool["checked_finds"] if ctl else 0.0
total_agent = len(agent_nf) + len(agent_unc) + hidden
out = {
    "n": len(labels), "checked_quotes": checked, "pool": pool,
    "verdicts": dict(Counter(verdicts[k]["verdict"] for k in keys)),
    "labels": dict(Counter(labels[k]["label"] for k in keys)),
    "table": {k: dict(v) for k, v in sorted(table.items())},
    "by_system": {m: {k: dict(v) for k, v in t.items()} for m, t in sorted(by_system.items())},
    "doubts": {k: dict(v) for k, v in sorted(doubts.items())},
    "not_found": {"n": len(nf), "agent_errors": len(agent_nf), "false_alarm_strict": strict, "unverifiable": unver},
    "false_not_found_of_checked": {"strict": rate(len(strict), checked),
                                   "with_unverifiable": rate(len(strict) + len(unver), checked)},
    "false_not_found_of_not_found": {"strict": rate(len(strict), len(nf)),
                                     "with_unverifiable": rate(len(strict) + len(unver), len(nf))},
    "controls": {"n": len(ctl), "in_source": len(ok_ctl), "agent_errors": agent_ctl,
                 "other": sorted(k for k in ctl if k not in ok_ctl and k not in agent_ctl)},
    "recall": {"agent_errors_in_misses": len(agent_nf) + len(agent_unc),
               "agent_errors_hidden_in_finds_est": round(hidden, 1),
               "not_found": round(len(agent_nf) / total_agent, 3) if total_agent else None,
               "not_found_or_uncertain": round((len(agent_nf) + len(agent_unc)) / total_agent, 3) if total_agent else None,
               "uncertain_agent_errors": agent_unc},
}
json.dump(out, open("comparison.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: out[k] for k in ("n", "verdicts", "labels", "table", "not_found", "false_not_found_of_checked",
                                      "controls", "recall")}, ensure_ascii=False, indent=1))
