"""E014 step 0. Run in data/ (outside git): Search Arena 24k (lmarena-ai/search-arena-24k @fac8dcf, prompts CC-BY-4.0,
model outputs under the providers' terms, so responses are not committed). No verbatim experiment has read it: E004-E012
read DeepResearch Bench I/II and ydc. Every assistant turn of a conversation tagged English only becomes one report;
numbered markers ([1], [[1]]) are rewritten to inline links from that turn's web_search_trace. Writes md/<model>/
<conv_id>-<turn>.md and ../DATASET.json.
"""
import hashlib, json, re, sys, urllib.request
from pathlib import Path

REV = "fac8dcf86146c8773ef020095c5694c9b2bc98d7"
URL = f"https://huggingface.co/datasets/lmarena-ai/search-arena-24k/resolve/{REV}/data/search-arena-chat-24k.parquet"
MARK = re.compile(r"\[\[(\d+)\]\]|\[(\d+)\](?![(:\[])")


def inline(text: str, refs: dict) -> str:
    def sub(m):
        n = m.group(1) or m.group(2)
        return f"[{n}]({refs[n]})" if n in refs else m.group(0)
    return MARK.sub(sub, text)


def main():
    import pandas as pd
    p = Path("sa24k.parquet")
    if not p.exists():
        p.write_bytes(urllib.request.urlopen(URL, timeout=600).read())
    raw_sha = hashlib.sha256(p.read_bytes()).hexdigest()
    df = pd.read_parquet(p)
    doc = {"dataset": "lmarena-ai/search-arena-24k (prompts CC-BY-4.0; outputs under provider terms, not committed)",
           "url": URL, "sha256": raw_sha, "filter": "languages == ['English'], every assistant turn, both sides",
           "files_sha256": {}}
    for _, r in df.iterrows():
        if list(r["languages"]) != ["English"]:
            continue
        for s in "ab":
            md, model = r[f"system_{s}_metadata"], r[f"model_{s}"]
            trace = md.get("web_search_trace")
            turns = [m["content"] for m in r[f"messages_{s}"] if m["role"] == "assistant"]
            for k, text in enumerate(turns):
                refs = {}
                if trace is not None and k < len(trace) and trace[k] is not None:
                    for pair in trace[k]:
                        refs[str(pair[0]).strip("[]")] = str(pair[1])
                out = Path("md") / model / f"{md['conv_id']}-{k + 1}.md"
                out.parent.mkdir(parents=True, exist_ok=True)
                body = inline(text or "", refs)
                out.write_text(body)
                doc["files_sha256"][str(out.relative_to("md"))] = hashlib.sha256(body.encode()).hexdigest()
    doc["reports"] = len(doc.pop("files_sha256"))  # sampled reports' sha256 are in summary.json (run.py)
    doc["note"] = "sha256 of every sampled report is in summary.json (sampled_sha256)"
    Path("../DATASET.json").write_text(json.dumps(doc, indent=1) + "\n")
    print("reports", doc["reports"])


if __name__ == "__main__":
    main()
