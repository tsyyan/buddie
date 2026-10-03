"""E014: unseal and count. Run from this folder after the blind labels are committed: writes comparison.json.

Definitions as in E006-E013: checked = own page read with >= 1500 visible characters; false NOT_FOUND = NOT_FOUND on a
quote labelled IN_SOURCE, NOT_A_QUOTE or TRANSLATED by both labellers; agent error = AGENT_ALTERED or AGENT_ABSENT.
A disagreement where either label would make the NOT_FOUND false is counted separately (upper bound). Every checked
miss is in the sample, plus random controls among the finds, so rates are over all checked quotes.
"""
import hashlib, json, math
from collections import Counter
from pathlib import Path

FALSE = ("IN_SOURCE", "NOT_A_QUOTE", "TRANSLATED")
AGENT = ("AGENT_ALTERED", "AGENT_ABSENT")
OK = ("FOUND", "FOUND_NORMALIZED", "FOUND_IN_COPY")


def wilson(k, n, z=1.96):
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(100 * (c - h), 1), round(100 * (c + h), 1)]


summ = json.loads(Path("summary.json").read_text())
sample = json.loads(Path("sample_blind.json").read_text())
sb = Path("verdicts_sealed.json").read_bytes()
assert hashlib.sha256(sb).hexdigest() == sample["verdicts_sealed_sha256"], "sealed verdicts changed"
sealed = json.loads(sb)
a = {x["key"]: x for x in json.loads(Path("labels_A.json").read_text())}
b = {x["key"]: x for x in json.loads(Path("labels_B.json").read_text())}
keys = sorted(sealed)
assert set(a) == set(b) == set(keys)
lab = {k: a[k]["label"] if a[k]["label"] == b[k]["label"] else None for k in keys}
checked = summ["checked_e010"]
fam = {k: sealed[k]["family"] for k in keys}
sealed_file = {x["key"]: f'{x["system"]}/{x["task"]}' for x in sample["items"]}


def count(ks, n):
    false = [k for k in ks if sealed[k]["verdict"] == "NOT_FOUND" and lab[k] in FALSE]
    disputed = [k for k in ks if sealed[k]["verdict"] == "NOT_FOUND" and lab[k] is None
                and (a[k]["label"] in FALSE or b[k]["label"] in FALSE)]
    agent = [k for k in ks if lab[k] in AGENT]
    hidden = [k for k in ks if lab[k] in AGENT and sealed[k]["verdict"] in OK + ("NOT_A_QUOTE",)]
    return {"checked": n, "false_not_found": len(false), "false_not_found_pct": round(100 * len(false) / n, 2),
            "ci95": wilson(len(false), n), "disputed": len(disputed),
            "upper_with_disputed_pct": round(100 * (len(false) + len(disputed)) / n, 2),
            "agent_errors": len(agent), "agent_errors_pct": round(100 * len(agent) / n, 1),
            "agent_errors_ci95": wilson(len(agent), n), "hidden_agent_errors": hidden,
            "false_keys": false, "disputed_keys": disputed}


doc = {"tool": summ["tool"], "quotes": summ["quotes"], "checked": checked, "sample": len(keys),
       "agreement": {"same": sum(1 for k in keys if lab[k]), "n": len(keys)},
       "table": {f"{lab[k] or 'DISAGREE'}|{sealed[k]['verdict']}": n for (k, n) in []},
       "all": count(keys, checked),
       "by_family": {f: count([k for k in keys if fam[k] == f], summ["by_family"][f]["checked_e010"])
                     for f in summ["by_family"]}}
doc["table"] = {f"{l}|{v}": n for (l, v), n in sorted(Counter((lab[k] or "DISAGREE", sealed[k]["verdict"])
                                                               for k in keys).items())}
# post-hoc: by Search Arena primary_intent (intents.json); the checked count per intent comes from summary.json
intents = json.loads(Path("intents.json").read_text())
chk_int = Counter(intents[f] for f in summ["checked_files"])
doc["by_intent"] = {i: {"checked": n, "false_not_found": sum(1 for k in doc["all"]["false_keys"]
                                                             if intents[f"{sealed_file[k]}"] == i)}
                    for i, n in chk_int.most_common()}
real = [k for k in doc["all"]["false_keys"] if lab[k] in ("IN_SOURCE", "TRANSLATED")]
doc["false_not_found_real_quotes"] = {"n": len(real), "pct": round(100 * len(real) / checked, 2),
                                      "ci95": wilson(len(real), checked), "keys": real}
# 0.3.2 out of sample so far: E012 fresh (1 of 44, E013 recount) + this run
e12 = (1, 44)
doc["v032_out_of_sample"] = {"false_not_found": e12[0] + doc["all"]["false_not_found"], "checked": e12[1] + checked,
                             "ci95": wilson(e12[0] + doc["all"]["false_not_found"], e12[1] + checked),
                             "parts": {"E012": "1/44 (E013 recount.json)", "E014": f"{doc['all']['false_not_found']}/{checked}"}}
Path("comparison.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
print(json.dumps(doc, ensure_ascii=False, indent=1))
