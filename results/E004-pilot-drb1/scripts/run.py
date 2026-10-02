"""E004 step 2. Run in data/: verbatim check of every English report; writes results.json."""
import json, re, collections
from verbatim.report import from_markdown
from verbatim.check import check_claims, summary
from verbatim.store import Store
st = Store("store")
out = []
for m in ["gemini-2.5-pro-deepresearch","grok-deeper-search","openai-deepresearch","perplexity-Research"]:
    for line in open(m+".jsonl"):
        r = json.loads(line)
        if re.search(r"[一-鿿]", r["prompt"]): continue
        claims, skipped = from_markdown(r["article"])
        claims = [c for c in claims if c["urls"]]
        if not claims: continue
        res = check_claims(claims, st)
        out.append({"system": m, "id": r["id"], "summary": summary(res), "claims": res})
json.dump(out, open("results.json","w"), ensure_ascii=False, indent=1)
tot = collections.defaultdict(collections.Counter)
for o in out:
    for c in o["claims"]: tot[o["system"]][c["verdict"]] += 1
for m,c in tot.items(): print(m, dict(c))
