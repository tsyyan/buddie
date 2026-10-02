"""Second random sample of misses for a blind label (E006). Run in data/ after run.py with verbatim v0.2.

Pool: quotes of >= 6 words that v0.2 does not find (NOT_FOUND or UNCERTAIN), in reports (system + task) that gave
nothing to the first sample (../sample_labeled.json), so no report a labeller has seen comes back. Excluding the task
for every system leaves only 27 misses and no Grok at all; per report the pool is 63 (OpenAI 48, Perplexity 15,
Grok 0: all its misses sit in the 7 Grok reports of the first sample). The whole pool is taken, in an order shuffled
with seed 2026, so the order says nothing about system or verdict.

Two files:
  sample_blind.json   what the labeller gets: quote, paragraph, its links and the snapshots verbatim read,
                      no verdict, no closest passage, no doubts.
  verdicts_sealed.json  verbatim's verdicts for the same keys. Only its sha256 goes into sample_blind.json,
                      so the verdicts are fixed before labelling and can be compared after it.
"""
import hashlib, json, random, shutil
from pathlib import Path

from verbatim.store import canonical_url

SEED = 2026
SYSTEMS = ["openai-deepresearch", "perplexity-Research", "grok-deeper-search"]
first = json.load(open(Path(__file__).resolve().parents[1] / "sample_labeled.json"))
seen = {(s["system"], s["task"]) for s in first}
out = json.load(open("results.json"))
arts = {}
for m in SYSTEMS:
    for line in open(m + ".jsonl"):
        r = json.loads(line)
        arts[(m, r["id"])] = r["article"]

pool = {m: [] for m in SYSTEMS}
for o in out:
    if o["system"] not in SYSTEMS or (o["system"], o["id"]) in seen:
        continue
    for c in o["claims"]:
        if c["verdict"] in ("NOT_FOUND", "UNCERTAIN") and len(c["quote"].split()) >= 6:
            pool[o["system"]].append((o["id"], c))

items = [(m, task, c) for m in SYSTEMS for task, c in pool[m]]
random.seed(SEED)
random.shuffle(items)
sample, sealed = [], {}
for n, (m, task, c) in enumerate(items, 1):
    key = f"B{n:02d}"  # neutral key: the system is in the item, but the key gives no order to read a verdict from
    lines = arts[(m, task)].splitlines()
    sample.append({"key": key, "system": m, "task": task, "claim": c["id"], "quote": c["quote"],
                   "paragraph": lines[c["line"] - 1], "line": c["line"], "urls": c["urls"],
                   "binding": c.get("binding"), "block_urls": c.get("block_urls", c["urls"])})
    sealed[key] = {k: c.get(k) for k in ("verdict", "doubts", "url", "sha256", "found_in", "error", "closest")}

sealed_bytes = (json.dumps(sealed, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode()
Path("verdicts_sealed.json").write_bytes(sealed_bytes)
doc = {"seed": SEED, "tool": "verbatim 0.2.0 (after E005 fixes)", "excluded_reports": sorted(f"{m}/{t}" for m, t in seen),
       "pool": {m: len(p) for m, p in pool.items()},
       "verdicts_sealed_sha256": hashlib.sha256(sealed_bytes).hexdigest(), "items": sample}
Path("sample_blind.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")

# the snapshots verbatim read for these items, so the label is about the same bytes, not a page that changed since
index = json.load(open("store/index.json"))
snap = Path("sample_store/snapshots")
snap.mkdir(parents=True, exist_ok=True)
sub = {}
for s in sample:
    for u in s["block_urls"]:
        cu = canonical_url(u)
        if cu in index and cu not in sub:
            sub[cu] = index[cu]
            for e in index[cu]:
                if e.get("sha256"):
                    shutil.copyfile(Path("store/snapshots") / e["sha256"], snap / e["sha256"])
Path("sample_store/index.json").write_text(json.dumps(sub, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
print({m: len(p) for m, p in pool.items()}, len(sample), len(sub))
