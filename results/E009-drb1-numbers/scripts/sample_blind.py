"""E009 step 4. Run in data/ after run.py: the blind sample and its sealed verdicts (as E010 step 3).

Every number of the 100 sampled sentences is an item (the sample was drawn before any verdict, so it measures
the population of cited numeric sentences, not a pool of misses). Writes:
  blind/sample_blind.json   per sentence: key, system, task, sentence (report text, links included), urls (the
                            sentence's cited links, resolved from footnotes), numbers [{key, text}] to label.
                            No verdict, match, context or page.
  blind/pages/<n>.txt       visible text of every snapshot of those links, with a header naming how it was read;
                            blind/pages/index.json maps URL -> [{file, sha256, via, http_status, error}].
  blind/snapshots/<sha256>  the raw bytes.
  sealed/verdicts_sealed.json  the tool's verdicts; its sha256 goes into sample_blind.json.
"""
import hashlib, json, shutil
from pathlib import Path

from verbatim.store import Store, canonical_url
from verbatim.textlayer import layers

sample = json.load(open("sample.json"))
res = {o["key"]: o for o in json.load(open("results.json"))["items"]}
Path("blind/pages").mkdir(parents=True, exist_ok=True)
Path("blind/snapshots").mkdir(exist_ok=True)
Path("sealed").mkdir(exist_ok=True)
sealed = {r["key"]: r for o in res.values() for r in o["numbers"]}
sealed_bytes = (json.dumps(sealed, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode()
Path("sealed/verdicts_sealed.json").write_bytes(sealed_bytes)
items = [{"key": x["key"], "system": x["system"], "task": x["task"], "sentence": x["sentence"], "urls": x["urls"],
          "numbers": [{"key": r["key"], "text": r["text"]} for r in res[x["key"]]["numbers"]]}
         for x in sample["items"]]
doc = {"seed": sample["seed"], "tool": json.load(open("results.json"))["tool"],
       "verdicts_sealed_sha256": hashlib.sha256(sealed_bytes).hexdigest(), "items": items}
Path("blind/sample_blind.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")

st = Store("store")
index = st.index()
pages, seen = {}, {}
for x in items:
    for u in x["urls"]:
        cu = canonical_url(u)
        if cu in pages:
            continue
        rows = []
        for e in index.get(cu, []):
            row = {k: e.get(k) for k in ("sha256", "via", "provenance", "http_status", "error", "final_url",
                                         "archived_at", "fetched_at")}
            sha = e.get("sha256")
            if sha:
                if sha not in seen:
                    seen[sha] = f"{len(seen) + 1:04d}.txt"
                    shutil.copyfile(st.snapshots / sha, Path("blind/snapshots") / sha)
                    try:
                        text = layers(st.read(sha), e.get("content_type"), e.get("content_encoding"))["visible"]
                    except Exception as ex:
                        text = f"[text layer failed: {ex}]"
                    head = f"# {cu}\n# read via {e.get('via') or 'direct'} ({e.get('provenance') or 'publisher'})," \
                           f" HTTP {e.get('http_status')}, final {e.get('final_url')}, sha256 {sha}\n\n"
                    Path("blind/pages", seen[sha]).write_text(head + text)
                row["file"] = seen[sha]
            rows.append(row)
        pages[cu] = rows
Path("blind/pages/index.json").write_text(json.dumps(pages, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
print("sentences", len(items), "numbers", len(sealed), "urls", len(pages), "snapshots", len(seen))
