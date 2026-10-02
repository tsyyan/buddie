"""E005: compare blind labels (blind_labels.json, committed before the original labels were read) with E004's
sample_labeled.json. Post-comparison corrections live in REVISIONS with the evidence; blind_labels.json is never edited.
Run from this directory: python compare.py  ->  comparison.json"""
import json
from collections import Counter

ORIG = json.load(open("../E004-deep-research-quotes/sample_labeled.json"))
BLIND = json.load(open("blind_labels.json"))
REVISIONS = {  # key: (new label, sub, evidence) -- found while checking the disagreements
    "openai/88/L38.1": ("TOOL_FALSE_ALARM", "url-parens",
                        "the report cites en.wikipedia.org/wiki/One_Hundred_Years_of_Solitude_(TV_series); verbatim cuts the URL "
                        "at '(' and fetched the novel's article. The TV-series article has the quote verbatim (Variety, Aramide Tinubu)."),
    "perple/79/L41.3": ("UNVERIFIABLE", None,
                        "the quote's own footnote [^1_14] is IMDb, which has 0 visible chars; transreads is [^1_15], a different sentence"),
    "openai/52/L25.6": ("NOT_A_QUOTE", "uncited-maxim",
                        "no link of its own: the 1989 letter link closes an earlier sentence. The words are exact Buffett (1988 letter)."),
}
COARSE = {"NOT_IN_SOURCE": "AGENT", "WRONG_SOURCE": "AGENT", "ALTERED_MEANING": "AGENT", "ALTERED_REWORDED": "AGENT",
          "ALTERED_MINOR": "AGENT", "AGENT_ABSENT": "AGENT", "AGENT_ALTERED": "AGENT",
          "TRANSLATED": "TRANSLATED", "NOT_ATTRIBUTED": "NOT_A_QUOTE", "NOT_A_QUOTE": "NOT_A_QUOTE",
          "TOOL": "TOOL_OR_UNVERIFIABLE", "TOOL_FALSE_ALARM": "TOOL_OR_UNVERIFIABLE", "UNVERIFIABLE": "TOOL_OR_UNVERIFIABLE"}
SERIOUS_ORIG = {"NOT_IN_SOURCE", "WRONG_SOURCE", "ALTERED_MEANING", "ALTERED_REWORDED"}


def kappa(a, b):
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / n / n
    return round((po - pe) / (1 - pe), 3), round(po, 3)


orig = {x["key"]: x["label"] for x in ORIG}
blind = {x["key"]: x for x in BLIND}
revised = {k: (REVISIONS[k][0], REVISIONS[k][1]) if k in REVISIONS else (v["label"], v["sub"]) for k, v in blind.items()}
keys = [x["key"] for x in ORIG]
assert set(keys) == set(blind) and len(keys) == 58


def summary(lab):
    c = Counter(lab[k][0] if isinstance(lab[k], tuple) else lab[k] for k in keys)
    return dict(sorted(c.items()))


def agent_errors(lab):
    return sum(COARSE[(lab[k][0] if isinstance(lab[k], tuple) else lab[k])] == "AGENT" for k in keys)


b_lab = {k: blind[k]["label"] for k in keys}
r_lab = {k: revised[k][0] for k in keys}
serious = lambda lab, sub: sum(lab[k] == "AGENT_ABSENT" or (lab[k] == "AGENT_ALTERED" and sub[k] == "material") for k in keys)
out = {
    "n": 58,
    "original": {"labels": summary(orig), "agent_errors": agent_errors(orig),
                 "serious": sum(orig[k] in SERIOUS_ORIG for k in keys)},
    "blind": {"labels": summary(b_lab), "agent_errors": agent_errors(b_lab),
              "serious": serious(b_lab, {k: blind[k]["sub"] for k in keys})},
    "revised": {"labels": summary(r_lab), "agent_errors": agent_errors(r_lab),
                "serious": serious(r_lab, {k: revised[k][1] for k in keys})},
    "agreement": {},
    "disagreements": [],
}
for name, lab in (("blind", b_lab), ("revised", r_lab)):
    a = [COARSE[orig[k]] for k in keys]
    b = [COARSE[lab[k]] for k in keys]
    k4, p4 = kappa(a, b)
    k2, p2 = kappa([x == "AGENT" for x in a], [x == "AGENT" for x in b])
    out["agreement"][name] = {"coarse4_kappa": k4, "coarse4_agree": p4, "agent_vs_not_kappa": k2, "agent_vs_not_agree": p2}
for k in keys:
    if COARSE[orig[k]] != COARSE[r_lab[k]] or k in REVISIONS:
        out["disagreements"].append({"key": k, "original": orig[k], "blind": blind[k]["label"], "revised": r_lab[k],
                                     "note": REVISIONS[k][2] if k in REVISIONS else blind[k]["note"]})
json.dump(out, open("comparison.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in out.items() if k != "disagreements"}, ensure_ascii=False, indent=1))
print(len(out["disagreements"]), "disagreements")
