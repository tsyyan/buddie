"""E011: two blind labellings (labels_A.json, labels_B.json, committed before unsealing) against verbatim 0.3.1's sealed
verdicts (verdicts_sealed.json, sha256 checked against sample_blind.json). Run from this directory:
python compare.py -> comparison.json

A label counts where A and B agree; items where they differ are listed for a human (rule 8) and bound each rate.
Each sealed verdict carries the quote's kind under 0.3.1 (not_quote_031) and 0.3.0 (not_quote_030). A NOT_A_QUOTE
verdict whose kind exists only under 0.3.1 comes from the E010 hints (scripts/run.py); under 0.3.0 it keeps its "miss".

On checked quotes (own page read, >= 1500 visible characters):
  false NOT_FOUND   NOT_FOUND on a quote labelled IN_SOURCE, NOT_A_QUOTE or TRANSLATED (strict, as E006-E010),
                    for 0.3.1 and for 0.3.0
  hints             NOT_A_QUOTE verdicts made by the hints: right (labelled NOT_A_QUOTE) or hiding an agent error
                    (AGENT_ALTERED / AGENT_ABSENT), against all agent errors in the sample
  filter            the same for every NOT_A_QUOTE verdict (0.3.0 rules included)
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


def hinted(k):
    v = verdicts[k]
    return v["verdict"] == "NOT_A_QUOTE" and v.get("not_quote_031") and not v.get("not_quote_030")


def v030(k):
    """The verdict 0.3.0 gives: a NOT_A_QUOTE made by the hints keeps its miss."""
    return verdicts[k]["miss"] if hinted(k) else verdicts[k]["verdict"]


def false_nf(verdict_of):
    nf = [k for k in keys if verdict_of(k) == "NOT_FOUND"]
    return rate([k for k in nf if label[k] in STRICT_FA], checked, [k for k in nf if label[k] == "DISAGREE"])


def judged(ks):
    return {"n": len(ks), "labels": dict(Counter(label[k] for k in ks)),
            "hidden_agent_errors": [k for k in ks if label[k] in AGENT],
            "right": [k for k in ks if label[k] == "NOT_A_QUOTE"]}


table = {}
for k in keys:
    table.setdefault(label[k], Counter())[verdicts[k]["verdict"]] += 1
naq = [k for k in keys if verdicts[k]["verdict"] == "NOT_A_QUOTE"]
hints = [k for k in naq if hinted(k)]
agents = [k for k in keys if label[k] in AGENT]
ctl = [k for k in keys if verdicts[k]["verdict"] in OK and verdicts[k].get("note") != "punctuation"]
out = {
    "n": len(keys), "checked_quotes": checked, "pool": pool,
    "agreement": {"same": len(keys) - len(disagree), "n": len(keys), "disagreements": disagree,
                  "pairs": {k: [A[k], B[k]] for k in disagree}},
    "verdicts": dict(Counter(verdicts[k]["verdict"] for k in keys)),
    "labels": dict(Counter(label[k] for k in keys)),
    "table": {k: dict(v) for k, v in sorted(table.items())},
    "false_not_found_of_checked": {"v0.3.1": false_nf(lambda k: verdicts[k]["verdict"]), "v0.3.0": false_nf(v030)},
    "agent_errors_in_sample": len(agents),
    "hints": judged(hints),
    "filter": dict(judged(naq), by_kind=dict(Counter(verdicts[k]["not_quote"] for k in naq))),
    "not_a_quote_left_in_not_found": [k for k in keys if verdicts[k]["verdict"] == "NOT_FOUND"
                                      and label[k] == "NOT_A_QUOTE"],
    "controls": {"n": len(ctl), "labels": dict(Counter(label[k] for k in ctl))},
}
open("comparison.json", "w").write(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
print(json.dumps({k: out[k] for k in ("agreement", "verdicts", "labels", "agent_errors_in_sample", "hints", "filter",
                                      "not_a_quote_left_in_not_found", "controls")}, ensure_ascii=False, indent=1))
for name, r in out["false_not_found_of_checked"].items():
    print(name, r["k"], "-", r["k_with_disagreements"], "of", r["n"], r["rate"], r["ci95"])
