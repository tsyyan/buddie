"""E004 step 0. Run in data/ next to the four dataset .jsonl files (see ../raw/DATASET.json): list URLs cited next to quotes."""
import json, re
from verbatim.report import from_markdown
from verbatim.store import canonical_url

urls = set()
for m in ["gemini-2.5-pro-deepresearch", "grok-deeper-search", "openai-deepresearch", "perplexity-Research"]:
    for line in open(m + ".jsonl"):
        r = json.loads(line)
        if re.search(r"[一-鿿]", r["prompt"]):
            continue  # English tasks only
        for c in from_markdown(r["article"])[0]:
            urls.update(canonical_url(u) for u in c["urls"])
open("urls.txt", "w").write("\n".join(sorted(urls)))
print(len(urls))
