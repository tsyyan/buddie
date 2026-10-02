"""E006: blind labels (blind_labels.json, commit c04908e) against verbatim v0.2's sealed verdicts (verdicts_sealed.json,
sha256 checked against sample_blind.json). Run from this directory: python compare.py -> comparison.json"""
import hashlib, json
from collections import Counter, defaultdict

sample = json.load(open("sample_blind.json"))
raw = open("verdicts_sealed.json", "rb").read()
assert hashlib.sha256(raw).hexdigest() == sample["verdicts_sealed_sha256"]
verdicts = json.loads(raw)
labels = {x["key"]: x for x in json.load(open("blind_labels.json"))}
AGENT = {"AGENT_ALTERED", "AGENT_ABSENT"}
STRICT_FA = {"TOOL_FALSE_ALARM", "NOT_A_QUOTE", "TRANSLATED"}
NF_SHARE = (86, 453)  # NOT_FOUND / checked quotes of >= 6 words, E004 REPORT.md after v0.2 + E005 fixes

table = defaultdict(Counter)
doubts = defaultdict(Counter)
for k, lab in labels.items():
    v = verdicts[k]
    table[lab["label"]][v["verdict"]] += 1
    for d in v.get("doubts") or []:
        doubts[d][lab["label"]] += 1
nf = [k for k in labels if verdicts[k]["verdict"] == "NOT_FOUND"]
unc = [k for k in labels if verdicts[k]["verdict"] == "UNCERTAIN"]
strict = [k for k in nf if labels[k]["label"] in STRICT_FA]
unver = [k for k in nf if labels[k]["label"] == "UNVERIFIABLE"]
agent = [k for k in labels if labels[k]["label"] in AGENT]
share = NF_SHARE[0] / NF_SHARE[1]
out = {
    "n": len(labels),
    "verdicts": dict(Counter(verdicts[k]["verdict"] for k in labels)),
    "labels": dict(Counter(l["label"] for l in labels.values())),
    "table": {k: dict(v) for k, v in table.items()},
    "doubts": {k: dict(v) for k, v in doubts.items()},
    "not_found": {"n": len(nf), "agent_errors": len(nf) - len(strict) - len(unver),
                  "false_alarm_strict": sorted(strict), "unverifiable": sorted(unver)},
    "false_alarm_rate_of_not_found": {"strict": round(len(strict) / len(nf), 3),
                                      "with_unverifiable": round((len(strict) + len(unver)) / len(nf), 3)},
    "false_alarm_rate_of_checked": {"strict": round(len(strict) / len(nf) * share, 4),
                                    "with_unverifiable": round((len(strict) + len(unver)) / len(nf) * share, 4),
                                    "not_found_share_used": f"{NF_SHARE[0]}/{NF_SHARE[1]}"},
    "agent_errors": {"n": len(agent), "not_found": sum(verdicts[k]["verdict"] == "NOT_FOUND" for k in agent),
                     "uncertain": sorted(k for k in agent if verdicts[k]["verdict"] == "UNCERTAIN")},
}
json.dump(out, open("comparison.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
