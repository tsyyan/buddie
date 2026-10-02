"""E010 step 0. Run in data/ (gitignored): download the reports and write one Markdown file per report.

Dataset: SaltyDuck0/ydc-deep-research-evals at a pinned commit: 102 research queries with the answer of OpenAI Deep
Research (o3, 2025), Markdown with inline links. None of its queries is a DeepResearch Bench I or II task, and none of
its reports was in E004-E008, so the not-a-quote rules (fitted on E008) meet them here for the first time. The
dataset has no card or license; its reports are not committed, only their sha256 (DATASET.json) and, in the blind
sample, the paragraph each quote stands in. Writes md/OpenAI-DR-ydc/row-N.md (N = CSV row, from 1).
"""
import csv, hashlib, json, urllib.request
from pathlib import Path

REPO = "SaltyDuck0/ydc-deep-research-evals"
REV = "59ee56cf100013a544df03858c83a922aae2edb5"
URL = f"https://huggingface.co/datasets/{REPO}/resolve/{REV}/ydc-deep-research-evals.csv"
CSV_SHA256 = "b90efcc7d6af9c9ff713758f2f51c78b1b7e38a536174513ef7408a1e25b3d93"

raw = urllib.request.urlopen(URL, timeout=120).read()
assert hashlib.sha256(raw).hexdigest() == CSV_SHA256, "the pinned CSV changed"
csv.field_size_limit(10 ** 9)
rows = list(csv.DictReader(raw.decode("utf-8").splitlines(keepends=True)))
out = Path("md/OpenAI-DR-ydc")
out.mkdir(parents=True, exist_ok=True)
files = {}
for n, row in enumerate(rows, 1):
    text = row["OpenAI_DeepResearch_Response"]
    (out / f"row-{n}.md").write_text(text)
    files[f"OpenAI-DR-ydc/row-{n}.md"] = hashlib.sha256(text.encode()).hexdigest()
doc = {"dataset": f"{REPO} (no license stated)", "revision": REV, "csv_sha256": CSV_SHA256, "rows": len(rows),
       "files_sha256": files}
Path("DATASET.json").write_text(json.dumps(doc, indent=1) + "\n")
print("reports", len(rows))
