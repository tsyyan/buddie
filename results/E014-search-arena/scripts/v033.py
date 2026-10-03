"""NEXT №41: verbatim 0.3.3 (footnote markers inside quotes dropped) on the E014 sample. Run in data/ after
get_dataset.py, with the lab checkout's components/verbatim on the path and 0.3.2 report.py at OLD (git show
cceceee:components/verbatim/verbatim/report.py > report_032.py).

The E014 sample (seed 2031) is rebuilt with 0.3.2 extraction exactly as run.py did (checked against summary.json),
then every sampled quote is extracted again by 0.3.3: only quotes whose text or links change can change verdict.
Those are checked again, 0.3.2 and 0.3.3 text in one call on the same fresh snapshot (store-041/), and joined with
the E014 labels. Writes ../v033.json.
"""
import hashlib, json, os, random, sys, importlib.util
from math import sqrt
from pathlib import Path

from verbatim.access import parse
from verbatim.check import check_claims
from verbatim.report import from_markdown as new_md
from verbatim.store import Store

OLD = os.environ.get("OLD", "report_032.py")
spec = importlib.util.spec_from_file_location("report_032", OLD)
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
SEED, MIN_WORDS, PER_REPORT, PER_FAMILY = 2031, 6, 3, 200
FAMILIES = {"perplexity": "sonar", "openai": "gpt-4o", "google": "gemini"}


def family(model):
    if model.endswith("wo-search"):
        return None
    return next((f for f, p in FAMILIES.items() if model.startswith(p)), None)


def wilson(k, n, z=1.96):
    p, d = k / n, 1 + z * z / n
    c, h = (p + z * z / (2 * n)) / d, z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(100 * (c - h), 1), round(100 * (c + h), 1)]


pool = {f: [] for f in FAMILIES}
for path in sorted(Path("md").glob("*/*.md")):
    f = family(path.parent.name)
    claims = [c for c in old.from_markdown(path.read_text())[0] if c["urls"] and len(c["quote"].split()) >= MIN_WORDS]
    if f and claims:
        pool[f].append((path, claims))
random.seed(SEED)
sample = []
for f, reps in pool.items():
    random.shuffle(reps)
    n = 0
    for path, claims in reps:
        if n >= PER_FAMILY:
            break
        take = claims[:min(PER_REPORT, PER_FAMILY - n)]
        sample.append((f, path, take))
        n += len(take)
summ = json.loads(Path("../summary.json").read_text())
assert {str(p.relative_to("md")): hashlib.sha256(p.read_bytes()).hexdigest() for _, p, _ in sample} == summ["sampled_sha256"]

items = json.loads(Path("../sample_blind.json").read_text())["items"]
labels = {k: {x["key"]: x["label"] for x in json.loads(Path(f"../labels_{k}.json").read_text())} for k in "AB"}
sealed = json.loads(Path("../verdicts_sealed.json").read_text())
st, rows, total = Store("store-041"), [], 0
for f, path, claims in sample:
    new = {c["id"]: c for c in new_md(path.read_text())[0]}
    for c in claims:
        total += 1
        n = new.get(c["id"])
        if n and n["quote"] == c["quote"] and n["urls"] == c["urls"]:
            continue
        key = next((it["key"] for it in items if it["task"] == path.name and it["line"] == c["line"]
                    and it["quote"] == c["quote"]), None)
        o, v = check_claims([dict(c), dict(n, id=c["id"] + "+")], st, fetch=True, access=parse("default"),
                            defer=("archive",))
        rows.append({"key": key, "file": str(path.relative_to("md")), "id": c["id"], "family": f,
                     "label_A": labels["A"].get(key), "label_B": labels["B"].get(key),
                     "e014_verdict": sealed.get(key, {}).get("verdict"), "e014_sha256": sealed.get(key, {}).get("sha256"),
                     "quote_032": c["quote"], "quote_033": n["quote"], "verdict_032": o["verdict"],
                     "verdict_033": v["verdict"], "doubts_033": v.get("doubts"), "found_in_033": v.get("found_in"),
                     "sha256": v.get("sha256"),
                     "closest_033": (v.get("closest") or {}).get("ratio")})
        print(key, rows[-1]["label_A"], rows[-1]["e014_verdict"], o["verdict"], "->", v["verdict"], flush=True)

ok = {"FOUND", "FOUND_NORMALIZED"}
agent = {"AGENT_ALTERED", "AGENT_ABSENT"}
# a false NOT_FOUND of E014 that 0.3.3 no longer calls NOT_FOUND while 0.3.2 still does on the same bytes
fixed = sorted(r["key"] for r in rows if r["e014_verdict"] == "NOT_FOUND" and r["verdict_032"] == "NOT_FOUND"
               and r["verdict_033"] != "NOT_FOUND" and r["label_A"] == r["label_B"] == "IN_SOURCE")
e014 = json.loads(Path("../comparison.json").read_text())
checked, false = e014["all"]["checked"], e014["all"]["false_not_found"]
real = e014["false_not_found_real_quotes"]["n"]
doc = {"tool": "verbatim 0.3.3 vs 0.3.2 report.py (cceceee), same snapshots per quote", "sampled": total, "changed": len(rows),
       "agent_errors_among_changed": sorted(r["key"] for r in rows if r["label_A"] in agent or r["label_B"] in agent),
       "agent_errors_now_found": sorted(r["key"] for r in rows if (r["label_A"] in agent or r["label_B"] in agent)
                                        and r["verdict_033"] in ok),
       "false_not_found_fixed": fixed,
       "in_sample_recount": {"checked": checked, "false_not_found": false - len(fixed),
                             "pct": round(100 * (false - len(fixed)) / checked, 1),
                             "ci95": wilson(false - len(fixed), checked),
                             "real_quotes_missed": real - len(fixed),
                             "real_pct": round(100 * (real - len(fixed)) / checked, 1),
                             "real_ci95": wilson(real - len(fixed), checked),
                             "note": "in-sample: 0.3.3 was written from these misses; not an out-of-sample number"},
       "rows": rows}
Path("../v033.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
print(json.dumps({k: v for k, v in doc.items() if k != "rows"}, indent=1))
