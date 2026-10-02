"""E013 step 2 (offline): the stage-2 numbers of PLAN.md on verbatim 0.3.2, from the labels E008, E010, E011 and E012
already have (no new labelling). Run from the experiment directory after scripts/refetch.py: writes recount.json.

For each labelled quote the 0.3.2 verdict is the experiment's sealed verdict with what changed in the tool since:
  search   E008: 0.3.2 locates the quote on the snapshot the labellers read (/mnt/project-files/e008-blind-sample,
           same bytes as the sealed 0.2 verdict). E010, E011: on the page read again now (refetch.json); a change counts
           only when 0.3.1's search on the same bytes disagrees with 0.3.2, otherwise the page changed and the sealed
           verdict stays (listed as drift). Unread pages keep the sealed verdict. E012 was run with 0.3.2.
  doubts   the "unattributed" doubt is re-read from the paragraph with 0.3.2's report reader (a NOT_FOUND with a doubt
           is UNCERTAIN); other doubts (unread_link, other_link, thin_page, other_language) stay as sealed.
           A quote the reader cannot find in its paragraph alone (4 items) keeps its sealed doubts and kind.
  kind     0.3.2's report reader gives the quote a kind (title, boilerplate, example): a miss with a kind is NOT_A_QUOTE.

Labels: E008 the consensus of four blind labellers (blind_labels.json); E010-E012 a label counts where A and B agree,
items where they differ are DISAGREE and bound each rate. Every sample holds all checked misses plus random control
finds; no control find was an agent error, so rates are over all checked quotes of the experiment.
  false NOT_FOUND   NOT_FOUND on a quote labelled IN_SOURCE, NOT_A_QUOTE or TRANSLATED (strict, as E006-E012)
  soft alarm        UNCERTAIN on such a quote
  agent errors      AGENT_ALTERED / AGENT_ABSENT; flagged when the verdict is NOT_FOUND or UNCERTAIN, hidden otherwise
"""
import hashlib, json, math, os, sys
from collections import Counter
from pathlib import Path

from verbatim import check
from verbatim.report import from_markdown

HERE = Path(__file__).resolve().parents[1]
LAB = HERE.parents[1]
E008_SNAPS = Path("/mnt/project-files/e008-blind-sample/snapshots")
EXPS = {"E008": "E008-fresh-reports", "E010": "E010-not-a-quote", "E011": "E011-example-hints",
        "E012": "E012-search-misses"}
# which version's rules were fitted on which sample (README of verbatim, REPORT.md of each experiment)
FITTED = {"E008": "0.3.0 (NOT_A_QUOTE kinds, punctuation level)", "E010": "0.3.1 (example hints)",
          "E011": "0.3.2 (search: speech tag, [A]t / ___, mojibake)", "E012": None}
AGENT = {"AGENT_ALTERED", "AGENT_ABSENT"}
STRICT_FA = {"IN_SOURCE", "NOT_A_QUOTE", "TRANSLATED"}
FOUNDISH = {"FOUND", "FOUND_NORMALIZED", "FOUND_IN_COPY", "HIDDEN_ONLY"}
MISS = {"NOT_FOUND", "UNCERTAIN"}


def wilson(k, n, z=1.96):
    p, d = k / n, 1 + z * z / n
    c, h = p + z * z / (2 * n), z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round((c - h) / d, 4), round((c + h) / d, 4)]


def rate(keys, n, unsure=()):
    return {"k": len(keys), "k_with_disagreements": len(keys) + len(unsure), "n": n, "rate": round(len(keys) / n, 4),
            "ci95": wilson(len(keys), n), "keys": sorted(keys), "disagreements": sorted(unsure)}


def labels(name, d):
    if name == "E008":
        return {x["key"]: x["label"] for x in json.loads((d / "blind_labels.json").read_text())}
    a = {x["key"]: x["label"] for x in json.loads((d / "labels_A.json").read_text())}
    b = {x["key"]: x["label"] for x in json.loads((d / "labels_B.json").read_text())}
    return {k: a[k] if a[k] == b.get(k) else "DISAGREE" for k in a}


def reader(it):
    c = [c for c in from_markdown(it["paragraph"] + "\n")[0] if c["quote"] == it["quote"]]
    return c[0] if c else {}


def checked_n(name, d):
    if name == "E012":
        return json.loads((d / "comparison.json").read_text())["fresh"]["checked"]
    return json.loads((d / "comparison.json").read_text())["checked_quotes"]


refetch = json.loads((HERE / "refetch.json").read_text()) if (HERE / "refetch.json").exists() else {}
out, pooled = {}, {"rows": [], "n": 0}
for name, sub in EXPS.items():
    d = LAB / "experiments" / sub
    sample = json.loads((d / "sample_blind.json").read_text())
    raw = (d / "verdicts_sealed.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == sample["verdicts_sealed_sha256"], name
    sealed, lab, n = json.loads(raw), labels(name, d), checked_n(name, d)
    rows, pages = [], {}
    for it in sample["items"]:
        k, s = it["key"], sealed[it["key"]]
        if s["verdict"] in ("NO_SOURCE", "SOURCE_UNAVAILABLE"):
            continue
        base = s.get("miss") if s["verdict"] == "NOT_A_QUOTE" else s["verdict"]
        row = {"key": k, "label": lab[k], "then": s["verdict"]}
        if name == "E008":
            sha = s["sha256"]
            if sha not in pages:
                pages[sha] = check.Page((E008_SNAPS / sha).read_bytes(), None)
            a, b = (base if base not in MISS else "NOT_FOUND"), pages[sha].locate(it["quote"])["verdict"]
        elif name in ("E010", "E011"):
            r = refetch.get(name, {}).get(k, {})
            a, b = r.get("v031_now"), r.get("v032_now")
            if a is None:
                row["page"] = "unread now"
        else:
            a = b = None
        if a is not None:
            if base in MISS and b in FOUNDISH:
                if a in FOUNDISH:
                    row["page"] = "changed: found by 0.3.1 too"
                else:
                    base, row["search"] = b, "found by 0.3.2 only"
            elif base in FOUNDISH and b not in FOUNDISH:
                if a in FOUNDISH:
                    base, row["search"] = "NOT_FOUND", "lost by 0.3.2"
                else:
                    row["page"] = "changed: not found by 0.3.1 either"
        c = reader(it)
        if not c and name != "E012":
            row["reader"] = "quote not read from the paragraph alone: sealed doubts and kind kept"
        if base in MISS and name != "E012" and c:
            doubts = [x for x in (s.get("doubts") or []) if x != "unattributed"]
            doubts += ["unattributed"] if c.get("attributed") is False else []
            if base == "UNCERTAIN" and not (s.get("doubts") or []):
                doubts += ["sealed"]  # UNCERTAIN for a reason not stored: keep it
            base = "UNCERTAIN" if doubts else "NOT_FOUND"
        kind = c.get("not_quote") if name != "E012" and c else s.get("not_quote")
        row["v032"] = "NOT_A_QUOTE" if base in MISS and kind else base
        if row["v032"] == "NOT_A_QUOTE":
            row.update(kind=kind, miss=base)
        rows.append(row)

    def summarize(rows, n):
        fa = [r["key"] for r in rows if r["v032"] == "NOT_FOUND" and r["label"] in STRICT_FA]
        fa_d = [r["key"] for r in rows if r["v032"] == "NOT_FOUND" and r["label"] == "DISAGREE"]
        fa_then = [r["key"] for r in rows if r["then"] == "NOT_FOUND" and r["label"] in STRICT_FA]
        soft = [r["key"] for r in rows if r["v032"] == "UNCERTAIN" and r["label"] in STRICT_FA]
        ag = [r for r in rows if r["label"] in AGENT]
        ag_d = [r["key"] for r in rows if r["label"] == "DISAGREE"]
        return {"checked": n, "false_not_found": rate(fa, n, fa_d), "false_not_found_then": rate(fa_then, n, fa_d),
                "soft_alarms_uncertain": len(soft),
                "agent_errors": rate([r["key"] for r in ag], n, ag_d),
                "agent_errors_flagged": sum(r["v032"] in MISS for r in ag),
                "agent_errors_not_found": sum(r["v032"] == "NOT_FOUND" for r in ag),
                "agent_errors_hidden": sorted(r["key"] for r in ag if r["v032"] not in MISS),
                "agent_errors_hidden_then": sorted(r["key"] for r in ag if r["then"] not in MISS),
                "verdicts": dict(Counter(r["v032"] for r in rows)),
                "changed": [r for r in rows if r["v032"] != r["then"]]}

    out[name] = dict(summarize(rows, n), fitted_here=FITTED[name], tool_then=sample.get("tool"),
                     pages=[{"key": r["key"], "page": r["page"]} for r in rows if "page" in r])
    pooled["rows"] += [dict(r, key=f"{name}/{r['key']}") for r in rows]
    pooled["n"] += n
    o = out[name]
    print(name, "n", n, "falseNF", o["false_not_found"]["k"], "then", o["false_not_found_then"]["k"],
          "agent", o["agent_errors"]["k"], "hidden", o["agent_errors_hidden"], "changed", len(o["changed"]),
          "pages", len(o["pages"]), flush=True)

allrows, alln = pooled["rows"], pooled["n"]
fa = [r["key"] for r in allrows if r["v032"] == "NOT_FOUND" and r["label"] in STRICT_FA]
fa_d = [r["key"] for r in allrows if r["v032"] == "NOT_FOUND" and r["label"] == "DISAGREE"]
ag = [r["key"] for r in allrows if r["label"] in AGENT]
oos = json.loads((LAB / "experiments/E010-not-a-quote/comparison.json").read_text())["false_not_found_of_checked"]["v0.3"]
oos11 = json.loads((LAB / "experiments/E011-example-hints/comparison.json").read_text())["false_not_found_of_checked"]["v0.3.1"]
oos12 = out["E012"]["false_not_found"]
k_oos = oos["k"] + oos11["k"] + oos12["k"]
n_oos = oos["n"] + oos11["n"] + oos12["n"]
out["pooled_032"] = {"checked": alln, "false_not_found": rate(fa, alln, fa_d), "agent_errors": rate(ag, alln),
                     "note": "in-sample for each version's fitted rules (FITTED); the out-of-sample row is below"}
out["out_of_sample"] = {
    "note": "each version measured on reports it was not fitted on, before the next fix: 0.3.0 on E010, 0.3.1 on E011, "
            "0.3.2 on E012 fresh (from each experiment's comparison.json)",
    "rows": {"0.3.0@E010": [oos["k"], oos["n"]], "0.3.1@E011": [oos11["k"], oos11["n"]],
             "0.3.2@E012": [oos12["k"], oos12["n"]]},
    "false_not_found": {"k": k_oos, "n": n_oos, "rate": round(k_oos / n_oos, 4), "ci95": wilson(k_oos, n_oos)},
    "only_032": {"k": oos12["k"], "n": oos12["n"], "ci95": wilson(oos12["k"], oos12["n"])}}
print("pooled", out["pooled_032"]["false_not_found"]["k"], alln, "agent", len(ag), "oos", k_oos, n_oos)
(HERE / "recount.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
