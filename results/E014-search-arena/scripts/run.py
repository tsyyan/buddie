"""E014 step 1. Run in data/ after get_dataset.py. Sample, then verbatim check --fetch --access default (0.3.2, rules
frozen at the commit in ../summary.json; archive deferred as in E012/E013).

Sample (seed 2031): quotes of >= 6 words with a link, as in E008-E012. Three families of systems (Perplexity sonar*,
OpenAI gpt-4o*-search, Google gemini-*-grounding); per family, reports are shuffled and taken whole (at most 3 quotes
each, the first ones) until the family has 200 quotes, so no single long answer dominates and every family weighs the
same. Writes results.json (not committed: answer paragraphs) and ../summary.json.

`run.py I N` checks shard I of N (every N-th report) into store-I/ and results-I.json, so shards run as parallel
processes; `run.py` with no arguments then merges the stores into store/ (`verbatim merge`) and the results.

Cloud container: VERBATIM_CHROMIUM=/opt/pw-browsers/chromium VERBATIM_BROWSER_CA=/root/.ccr/agent-proxy-ca.crt.
"""
import json, random, subprocess, sys
from collections import Counter
from pathlib import Path

from verbatim.access import parse
from verbatim.check import check_claims, summary
from verbatim.report import from_markdown
from verbatim.store import Store

SEED, MIN_WORDS, PER_REPORT, PER_FAMILY = 2031, 6, 3, 200
FAMILIES = {"perplexity": "sonar", "openai": "gpt-4o", "google": "gemini"}


def family(model):
    if model.endswith("wo-search"):
        return None
    return next((f for f, p in FAMILIES.items() if model.startswith(p)), None)


pool = {f: [] for f in FAMILIES}
for path in sorted(Path("md").glob("*/*.md")):
    f = family(path.parent.name)
    claims = [c for c in from_markdown(path.read_text())[0] if c["urls"] and len(c["quote"].split()) >= MIN_WORDS]
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
if len(sys.argv) == 3:
    i, n = map(int, sys.argv[1:])
    st, out = Store(f"store-{i}"), []
    for f, path, claims in sample[i::n]:
        for attempt in (1, 2):
            try:
                res = check_claims(claims, st, fetch=True, access=parse("default"), defer=("archive",))
                break
            except Exception as err:  # store.fetch does not catch http.client.IncompleteRead (a cut-off body)
                print(path, "attempt", attempt, repr(err)[:200], flush=True)
                res = [dict(c, verdict="SOURCE_UNAVAILABLE", error=f"crash: {repr(err)[:200]}") for c in claims]
        for r in res:
            r["file"], r["family"] = str(path.relative_to("md")), f
        out.extend(res)
        print(path, summary(res), flush=True)
    Path(f"results-{i}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    sys.exit(0)
parts = sorted(Path(".").glob("results-*.json"))
order = {(str(p.relative_to("md")), c["line"], c["quote"]): k for k, (_, p, cs) in enumerate(sample) for c in cs}
out = sorted((r for p in parts for r in json.loads(p.read_text())), key=lambda r: order[(r["file"], r["line"], r["quote"])])
assert len(out) == len(order), (len(out), len(order))
for p in sorted(Path(".").glob("store-*")):
    subprocess.run([sys.executable, "-m", "verbatim", "merge", str(p), "--store", "store"], check=True)
Path("results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
checked = [r for r in out if r["verdict"] not in ("SOURCE_UNAVAILABLE", "NO_SOURCE") and r.get("page_chars", 0) >= 1500]
commit = subprocess.run(["git", "-C", Path(__file__).resolve().parent, "log", "-1", "--format=%h", "--",
                         "../../../components/verbatim"], capture_output=True, text=True).stdout.strip()
doc = {"seed": SEED, "tool": f"verbatim 0.3.2 (tsyyan/lab {commit})",
       "pool_quotes": {f: sum(len(c) for _, c in reps) for f, reps in pool.items()},
       "pool_reports": {f: len(reps) for f, reps in pool.items()},
       "quotes": len(out), "reports": len({r["file"] for r in out}), "checked_e010": len(checked),
       "verdicts": summary(out),
       "by_family": {f: {"quotes": sum(1 for r in out if r["family"] == f),
                         "checked_e010": sum(1 for r in checked if r["family"] == f),
                         "verdicts_checked": dict(Counter(r["verdict"] for r in checked if r["family"] == f))}
                     for f in FAMILIES},
       "checked_files": [r["file"] for r in checked],
       "sampled_sha256": {str(p.relative_to("md")): __import__("hashlib").sha256(p.read_bytes()).hexdigest()
                          for _, p, _ in sample},
       "by_model": dict(Counter(r["file"].split("/")[0] for r in out))}
Path("../summary.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
print(json.dumps(doc, indent=1))
