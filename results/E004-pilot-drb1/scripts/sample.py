"""Random sample of misses for manual labelling (E004). Run in data/ after run.py.

Pool: NOT_FOUND quotes of >= 6 words whose snapshot has >= 1500 visible characters. Seed 7.
The labelled sample (../sample_labeled.json) was drawn from results.json before the gate-page and gzip fixes,
so a re-run draws a slightly different sample.
"""
import json, random

QUOTA = {"openai-deepresearch": 25, "perplexity-Research": 20, "grok-deeper-search": 13}
out = json.load(open("results.json"))
arts = {}
for m in QUOTA:
    for line in open(m + ".jsonl"):
        r = json.loads(line)
        arts[(m, r["id"])] = r["article"]
random.seed(7)
pool = {}
for o in out:
    for c in o["claims"]:
        if c["verdict"] == "NOT_FOUND" and c["page_chars"] >= 1500 and len(c["quote"].split()) >= 6:
            pool.setdefault(o["system"], []).append((o["id"], c))
sample = []
for m, q in QUOTA.items():
    for i, c in random.sample(pool[m], min(q, len(pool[m]))):
        sample.append({"key": f"{m[:6]}/{i}/{c['id']}", "system": m, "task": i, "claim": c["id"], "quote": c["quote"],
                       "url": c["url"], "sha256": c["sha256"], "ratio": c["closest"]["ratio"],
                       "near": c["closest"]["text"], "line": arts[(m, i)].splitlines()[c["line"] - 1],
                       "page_chars": c["page_chars"]})
json.dump(sample, open("sample.json", "w"), ensure_ascii=False, indent=1)
print(len(sample))
