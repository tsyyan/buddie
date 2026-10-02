"""E010: two blind labellings (labels_A.json, labels_B.json, committed before unsealing) against verbatim 0.3's sealed
verdicts (verdicts_sealed.json, sha256 checked against sample_blind.json). Run from this directory:
python compare.py -> comparison.json

A label counts where A and B agree; items where they differ are listed for a human (rule 8) and bound each rate: the
low end counts none of them against verbatim, the high end all of them.

What is measured, on checked quotes (own page read, >= 1500 visible characters):
  false NOT_FOUND     NOT_FOUND on a quote labelled IN_SOURCE, NOT_A_QUOTE or TRANSLATED (strict, as E006/E008)
  before 0.3          the same, counting NOT_A_QUOTE verdicts as the miss they were ("miss") and punctuation finds as
                      NOT_FOUND (what 0.2 gave them; a doubt could have made some of them UNCERTAIN, so this is an
                      upper bound of 0.2's false NOT_FOUND)
  hidden errors       NOT_A_QUOTE verdicts on quotes labelled AGENT_ALTERED / AGENT_ABSENT: agent errors the filter hides
  punctuation finds   labelled IN_SOURCE (right) or AGENT_* (an error the new matching hides)
"""
import hashlib, json, math
from collections import Counter

sample = json.load(open("sample_blind.json"))
raw = open("verdicts_sealed.json", "rb").read()
assert hashlib.sha256(raw).hexdigest() == sample["verdicts_sealed_sha256"], "sealed verdicts do not match the sample"
verdicts = json.loads(raw)
A = {x["key"]: x["label"] for x in json.load(open("labels_A.json"))}
B = {x["key"]: x["label"] for x in json.load(open("labels_B.json"))}
assert set(A) == set(B) == set(verdicts), "both labellers label every item"
AGENT = {"AGENT_ALTERED", "AGENT_ABSENT"}
STRICT_FA = {"IN_SOURCE", "NOT_A_QUOTE", "TRANSLATED"}
OK = {"FOUND", "FOUND_NORMALIZED", "FOUND_IN_COPY"}
pool = sample["pool"]
checked = pool["checked_misses_and_punctuation_finds"] + pool["checked_finds"]
keys = sorted(verdicts)
label = {k: A[k] if A[k] == B[k] else "DISAGREE" for k in keys}
disagree = [k for k in keys if label[k] == "DISAGREE"]


def wilson(k, n, z=1.96):
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round((c - h) / d, 4), round((c + h) / d, 4)]


def rate(ks, n, unsure=()):
    lo, hi = len(ks), len(ks) + len(unsure)
    return {"k": lo, "k_with_disagreements": hi, "n": n, "rate": round(lo / n, 4) if n else None,
            "rate_with_disagreements": round(hi / n, 4) if n else None, "ci95": wilson(lo, n), "keys": ks,
            "disagreements": list(unsure)}


def old(k):
    """The verdict 0.2 would have given (see module docstring)."""
    v = verdicts[k]
    if v["verdict"] == "NOT_A_QUOTE":
        return v["miss"]
    if v.get("note") == "punctuation":
        return "NOT_FOUND"
    return v["verdict"]


def false_nf(verdict_of):
    nf = [k for k in keys if verdict_of(k) == "NOT_FOUND"]
    return rate([k for k in nf if label[k] in STRICT_FA], checked, [k for k in nf if label[k] == "DISAGREE"])


table = {}
for k in keys:
    table.setdefault(label[k], Counter())[verdicts[k]["verdict"]] += 1
naq = [k for k in keys if verdicts[k]["verdict"] == "NOT_A_QUOTE"]
punct = [k for k in keys if verdicts[k].get("note") == "punctuation"]
agents = [k for k in keys if label[k] in AGENT]
ctl = [k for k in keys if verdicts[k]["verdict"] in OK and verdicts[k].get("note") != "punctuation"]
out = {
    "n": len(keys), "checked_quotes": checked, "pool": pool,
    "agreement": {"same": len(keys) - len(disagree), "n": len(keys), "disagreements": disagree,
                  "pairs": {k: [A[k], B[k]] for k in disagree}},
    "verdicts": dict(Counter(verdicts[k]["verdict"] for k in keys)),
    "labels": dict(Counter(label[k] for k in keys)),
    "table": {k: dict(v) for k, v in sorted(table.items())},
    "false_not_found_of_checked": {"v0.3": false_nf(lambda k: verdicts[k]["verdict"]), "before_0.3": false_nf(old)},
    "not_a_quote": {"n": len(naq), "by_kind": dict(Counter(verdicts[k]["not_quote"] for k in naq)),
                    "labels": dict(Counter(label[k] for k in naq)),
                    "hidden_agent_errors": [k for k in naq if label[k] in AGENT],
                    "agent_errors_in_sample": len(agents)},
    "not_a_quote_left_in_not_found": [k for k in keys if verdicts[k]["verdict"] == "NOT_FOUND"
                                      and label[k] == "NOT_A_QUOTE"],
    "punctuation_finds": {"n": len(punct), "labels": dict(Counter(label[k] for k in punct))},
    "controls": {"n": len(ctl), "labels": dict(Counter(label[k] for k in ctl))},
}
open("comparison.json", "w").write(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
print(json.dumps({k: out[k] for k in ("agreement", "verdicts", "labels", "not_a_quote", "punctuation_finds",
                                      "controls")}, ensure_ascii=False, indent=1))
for name, r in out["false_not_found_of_checked"].items():
    print(name, r["k"], "-", r["k_with_disagreements"], "of", r["n"], r["rate"], r["ci95"])
