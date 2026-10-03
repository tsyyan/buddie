"""E009: two blind labellings (labels_A.json, labels_B.json, committed before unsealing) against the sealed verdicts of
verbatim.numbers (verdicts_sealed.json, sha256 checked against sample_blind.json). Run from this directory:
python compare.py -> comparison.json

The unit is a number of a cited sentence (100 random sentences, 25 per system, all their numbers). A label counts
where A and B agree; numbers where they differ are listed for a human (README rule 8) and bound each rate: the low end
counts none of them, the high end all of them.

audit/06 §3.A decision rule: numbers become the second claim type of verbatim if a number of the report is not in its
source (WRONG_VALUE or ABSENT) in >= 10 % of checkable numbers while the tool's false alarms stay <= 5 %.
  checkable       labelled IN_SOURCE, WRONG_VALUE, ABSENT or DERIVED (own source readable, number claimed from it)
  agent errors    WRONG_VALUE + ABSENT, share of checkable
  false alarm     the tool says NOT_FOUND on a number labelled IN_SOURCE (share of checkable); NO_CONTEXT is reported
                  apart (value on the page, far from the sentence's words), DERIVED apart (not on the page by nature)
  caught          agent errors the tool flags (NOT_FOUND or NO_CONTEXT); missed = errors it calls FOUND*
"""
import hashlib, json, math
from collections import Counter

sample = json.load(open("sample_blind.json"))
raw = open("verdicts_sealed.json", "rb").read()
assert hashlib.sha256(raw).hexdigest() == sample["verdicts_sealed_sha256"], "sealed verdicts do not match the sample"
verdicts = json.loads(raw)
A = {x["key"]: x for x in json.load(open("labels_A.json"))}
B = {x["key"]: x for x in json.load(open("labels_B.json"))}
assert set(A) == set(B) == set(verdicts), "both labellers label every number"
system = {n["key"]: x["system"] for x in sample["items"] for n in x["numbers"]}
keys = sorted(verdicts, key=lambda k: (k.split(".")[0], int(k.split(".")[1])))
label = {k: A[k]["label"] if A[k]["label"] == B[k]["label"] else "DISAGREE" for k in keys}
disagree = [k for k in keys if label[k] == "DISAGREE"]
CHECKABLE = {"IN_SOURCE", "WRONG_VALUE", "ABSENT", "DERIVED"}
ERROR = {"WRONG_VALUE", "ABSENT"}
FOUND = {"FOUND", "FOUND_NORMALIZED", "FOUND_ROUNDED"}
FLAG = {"NOT_FOUND", "NO_CONTEXT"}


def wilson(k, n, z=1.96):
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 3), round(c + h, 3)]


def maybe(k, test_a, test_b=None):
    """Whether a disagreeing number could count: either labeller's label passes."""
    test_b = test_b or test_a
    return test_a(A[k]["label"]) or test_b(B[k]["label"])


def rates(ks):
    agreed = [k for k in ks if label[k] != "DISAGREE"]
    dis = [k for k in ks if label[k] == "DISAGREE"]
    chk = [k for k in agreed if label[k] in CHECKABLE]
    chk_hi = chk + [k for k in dis if maybe(k, lambda l: l in CHECKABLE)]
    err = [k for k in chk if label[k] in ERROR]
    err_hi = err + [k for k in dis if maybe(k, lambda l: l in ERROR)]
    fa = [k for k in chk if label[k] == "IN_SOURCE" and verdicts[k]["verdict"] == "NOT_FOUND"]
    fa_hi = fa + [k for k in dis if verdicts[k]["verdict"] == "NOT_FOUND" and maybe(k, lambda l: l == "IN_SOURCE")]
    nc = [k for k in chk if label[k] == "IN_SOURCE" and verdicts[k]["verdict"] == "NO_CONTEXT"]
    der = [k for k in chk if label[k] == "DERIVED"]
    caught = [k for k in err if verdicts[k]["verdict"] in FLAG]
    missed = [k for k in err if verdicts[k]["verdict"] in FOUND]
    return {
        "numbers": len(ks), "agreed": len(agreed), "disagree": len(dis),
        "labels": dict(Counter(label[k] for k in ks).most_common()),
        "checkable": len(chk), "checkable_with_disagreements": len(chk_hi),
        "agent_errors": len(err), "agent_errors_high": len(err_hi),
        "agent_error_rate": round(len(err) / len(chk), 3) if chk else None,
        "agent_error_rate_ci95": wilson(len(err), len(chk)),
        "agent_error_rate_high": round(len(err_hi) / len(chk_hi), 3) if chk_hi else None,
        "false_not_found": len(fa), "false_not_found_high": len(fa_hi),
        "false_not_found_rate": round(len(fa) / len(chk), 3) if chk else None,
        "false_not_found_rate_ci95": wilson(len(fa), len(chk)),
        "false_not_found_rate_high": round(len(fa_hi) / len(chk_hi), 3) if chk_hi else None,
        "in_source_no_context": len(nc), "derived": len(der),
        "derived_tool": dict(Counter(verdicts[k]["verdict"] for k in der)),
        "errors_caught": len(caught), "errors_missed_as_found": len(missed),
        "errors_unavailable_to_tool": len([k for k in err if verdicts[k]["verdict"] == "SOURCE_UNAVAILABLE"]),
        "keys": {"false_not_found": fa, "in_source_no_context": nc, "agent_errors": err, "missed": missed},
    }


# Numbers whose own footnote E009 did not resolve: Gemini footnotes after a space ("in 2019 16,") are not read by
# sentences.py, so these sentences were checked against a later footnote's URL (both labellers' notes on S003, S007,
# S011). An ABSENT there is our attribution error, not the agent's; "adjusted" leaves these sentences out.
ATTRIBUTION = {"S003", "S007", "S011"}
kinds = {k: verdicts[k]["kind"] for k in keys}
out = {
    "tool": sample["tool"],
    "agreement": {"numbers": len(keys), "agree": len(keys) - len(disagree),
                  "kappa": None},
    "confusion": {f"{lab} / {v}": n for (lab, v), n in
                  sorted(Counter((label[k], verdicts[k]["verdict"]) for k in keys).items())},
    "all": rates(keys),
    "by_system": {s: rates([k for k in keys if system[k] == s]) for s in sorted(set(system.values()))},
    "by_kind": {"values (percent, money, value)": rates([k for k in keys if kinds[k] in ("percent", "money", "value")]),
                "dates and years": rates([k for k in keys if kinds[k] in ("year", "date", "month")])},
    "adjusted": {k: v for k, v in rates([k for k in keys if k.split(".")[0] not in ATTRIBUTION]).items() if k != "keys"},
    "tool_not_found": {
        "total": sum(verdicts[k]["verdict"] == "NOT_FOUND" for k in keys),
        "by_label": dict(Counter(label[k] for k in keys if verdicts[k]["verdict"] == "NOT_FOUND").most_common()),
        "note": "NOT_FOUND on a page both labellers call UNVERIFIABLE: verbatim took a gate, JS shell, redirect or "
                "a page updated since for readable text",
    },
    "disagree": [{"key": k, "A": A[k]["label"], "B": B[k]["label"], "tool": verdicts[k]["verdict"],
                  "text": verdicts[k]["text"]} for k in disagree],
}
la, lb = [A[k]["label"] for k in keys], [B[k]["label"] for k in keys]
po = sum(a == b for a, b in zip(la, lb)) / len(keys)
ca, cb = Counter(la), Counter(lb)
pe = sum(ca[x] * cb[x] for x in set(ca) | set(cb)) / len(keys) ** 2
out["agreement"]["kappa"] = round((round(po, 3) - round(pe, 3)) / (1 - round(pe, 3)), 3)
a = out["all"]
out["decision"] = {
    "rule": "agent errors >= 10 % of checkable numbers and false NOT_FOUND <= 5 % (audit/06 §3.A)",
    "agent_errors_ge_10pct": a["agent_error_rate"] is not None and a["agent_error_rate"] >= 0.10,
    "false_alarms_le_5pct": a["false_not_found_rate_high"] is not None and a["false_not_found_rate_high"] <= 0.05,
}
json.dump(out, open("comparison.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: out[k] for k in ("agreement", "decision")}, ensure_ascii=False, indent=1))
print(json.dumps({k: v for k, v in a.items() if k != "keys"}, ensure_ascii=False, indent=1))
