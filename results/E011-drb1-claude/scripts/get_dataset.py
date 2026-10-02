"""E011 step 0. Run in data/ (gitignored): download the reports and write one Markdown file per report.

Dataset: DeepResearch Bench (Ayanami0730/deep_research_bench, Apache-2.0) at a pinned commit, file
data/test_data/raw_data/claude-3-7-sonnet-latest.jsonl: answers of Claude 3.7 Sonnet with web search to the 100
DeepResearch Bench I tasks. A system no verbatim experiment has read (E004 had OpenAI, Gemini, Perplexity and Grok on
these tasks; E008 DeepResearch Bench II; E010 o3 on ydc). Only English tasks (id 51-100): quotes are counted in words.

The reports cite with numbers ("… [3][7]") and end with a list "[3] https://… - title". verbatim reads "[3]: url"
definitions only for [text][ref] links, so each "[n]" in the text becomes the inline link [n](url of n) - what a reader
clicks - and the list is dropped. Nothing else changes. Writes md/Claude-3.7-DRB/row-N.md (N = task id).
"""
import hashlib, json, re, urllib.request
from pathlib import Path

REPO = "Ayanami0730/deep_research_bench"
REV = "f2735b5c3636759c22f9e936c0232de8bf545b67"
PATH = "data/test_data/raw_data/claude-3-7-sonnet-latest.jsonl"
URL = f"https://raw.githubusercontent.com/{REPO}/{REV}/{PATH}"
SHA256 = "dc16f997d3ecd09bccf6d9e756d9ad36d2834d2ed0827b8f39579b6321b98837"
REF = re.compile(r"^\[(\d+)\]\s+(https?://\S+).*$", re.M)


def inline(text: str) -> str:
    refs = dict((n, u) for n, u in REF.findall(text))
    body = REF.sub("", text)
    return re.sub(r"\[(\d+)\](?![(:\[])", lambda m: f"[{m.group(1)}]({refs[m.group(1)]})" if m.group(1) in refs
                  else m.group(0), body)


raw = urllib.request.urlopen(URL, timeout=120).read()
assert hashlib.sha256(raw).hexdigest() == SHA256, "the pinned file changed"
out = Path("md/Claude-3.7-DRB")
out.mkdir(parents=True, exist_ok=True)
files = {}
for line in raw.decode("utf-8").splitlines():
    r = json.loads(line)
    if r["id"] <= 50:
        continue
    text = inline(r["article"])
    (out / f"row-{r['id']}.md").write_text(text)
    files[f"Claude-3.7-DRB/row-{r['id']}.md"] = hashlib.sha256(text.encode()).hexdigest()
doc = {"dataset": f"{REPO} {PATH} (Apache-2.0)", "revision": REV, "file_sha256": hashlib.sha256(raw).hexdigest(),
       "reports": len(files), "files_sha256": files}
Path("DATASET.json").write_text(json.dumps(doc, indent=1) + "\n")
print("reports", len(files))
