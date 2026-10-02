"""E012 step 0. Run in data/ (gitignored): the DeepResearch Bench I reports no verbatim experiment has read.

DeepResearch Bench (Apache-2.0) at pinned revisions: HF muset-ai/DeepResearch-Bench-Dataset generated_reports (the
four files E004 used, tasks 51-100 only) and github Ayanami0730/deep_research_bench raw_data (Claude 3.7 Sonnet, E011
used tasks 51-100; reference.jsonl = Gemini 2.5 Pro Deep Research reference articles, a separate run from E004's
Gemini file, read by no experiment). Unread here: tasks 1-50 (Chinese prompts) of all five systems and reference.jsonl
on all 100 tasks. Numbered references are rewritten to inline links as in E011. Writes md/<system>/row-N.md and
../DATASET.json.
"""
import hashlib, json, re, urllib.request
from pathlib import Path

HF = "https://huggingface.co/datasets/muset-ai/DeepResearch-Bench-Dataset/resolve/{rev}/generated_reports/{name}.jsonl"
HF_REV = "main"
GH = "https://raw.githubusercontent.com/Ayanami0730/deep_research_bench/f2735b5c3636759c22f9e936c0232de8bf545b67/" \
     "data/test_data/raw_data/{name}.jsonl"
# sha256 as pinned by E004 (raw/DATASET.json) and E011 (DATASET.json); reference.jsonl pinned here
FILES = {
    "gemini-2.5-pro-deepresearch": (HF, "0ead8c3cc42c3ea844e71be7bf21670a608feaa5a718695e3b215247d9198a80", range(1, 51)),
    "grok-deeper-search": (HF, "f14c64de8c22d66b5a1c08af0cb0d829d9a4b671378a2952230b2219d258f0ba", range(1, 51)),
    "openai-deepresearch": (HF, "8a9dbbf7f18d8c985bc4d4f450089eb4bb73e77dbf7168a1bb4c81f811e06d84", range(1, 51)),
    "perplexity-Research": (HF, "0a3b855862c99f108abf97b9e402b43eb4d3376c3ec93c2e0a9c871b70d0736e", range(1, 51)),
    "claude-3-7-sonnet-latest": (GH, "dc16f997d3ecd09bccf6d9e756d9ad36d2834d2ed0827b8f39579b6321b98837", range(1, 51)),
    "reference": (GH, None, range(1, 101)),
}
REF = re.compile(r"^\[(\d+)\]\s+(https?://\S+).*$", re.M)


def inline(text: str) -> str:
    refs = dict((n, u) for n, u in REF.findall(text))
    body = REF.sub("", text)
    return re.sub(r"\[(\d+)\](?![(:\[])", lambda m: f"[{m.group(1)}]({refs[m.group(1)]})" if m.group(1) in refs
                  else m.group(0), body)


doc = {"dataset": "DeepResearch Bench I (Apache-2.0): HF muset-ai/DeepResearch-Bench-Dataset generated_reports, "
                  "github Ayanami0730/deep_research_bench@f2735b5 raw_data", "files": {}, "files_sha256": {}}
for name, (url, sha, ids) in FILES.items():
    u = url.format(rev=HF_REV, name=name)
    raw = urllib.request.urlopen(u, timeout=300).read()
    got = hashlib.sha256(raw).hexdigest()
    assert sha is None or got == sha, f"{name}: the pinned file changed"
    doc["files"][name] = {"url": u, "sha256": got, "tasks": f"{ids.start}-{ids.stop - 1}"}
    out = Path("md") / name
    out.mkdir(parents=True, exist_ok=True)
    for line in raw.decode("utf-8").splitlines():
        r = json.loads(line)
        if r["id"] not in ids:
            continue
        text = inline(r.get("article") or "")
        (out / f"row-{r['id']}.md").write_text(text)
        doc["files_sha256"][f"{name}/row-{r['id']}.md"] = hashlib.sha256(text.encode()).hexdigest()
Path("../DATASET.json").write_text(json.dumps(doc, indent=1) + "\n")
print("reports", len(doc["files_sha256"]))
