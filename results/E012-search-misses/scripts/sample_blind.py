"""E012 step 2. Run in data/ after run.py: every quote of the fresh pool that 0.3.2 did not find on a read page
(NOT_FOUND, UNCERTAIN, NOT_A_QUOTE) goes to two blind labellers with the E011 brief (../LABELLING.md), to count real
quotes the search still misses (and what the new rules would have had to catch). No controls: the pool is small and
0.3.2 found nothing that 0.3.1 missed (summary.json), so there are no new finds to check.
Writes blind/ (sample, page texts, snapshots) and sealed/verdicts_sealed.json; its sha256 goes into the sample."""
import hashlib, json, random, shutil
from pathlib import Path

from verbatim.store import Store, canonical_url
from verbatim.textlayer import layers

SEED = 2030
MISS = ("NOT_FOUND", "UNCERTAIN", "NOT_A_QUOTE")
SEALED = ("verdict", "doubts", "url", "sha256", "via", "closest", "not_quote", "miss", "note", "v031_locate")
res = [r for r in json.load(open("results.json")) if r.get("sha256") and r["verdict"] in MISS]
random.seed(SEED)
random.shuffle(res)
for d in ("blind/pages", "blind/snapshots", "sealed"):
    Path(d).mkdir(parents=True, exist_ok=True)
sample, sealed = [], {}
for n, r in enumerate(res, 1):
    key = f"G{n:03d}"
    lines = Path("md", r["file"]).read_text().splitlines()
    sample.append({"key": key, "file": r["file"], "line": r["line"], "quote": r["quote"],
                   "paragraph": lines[r["line"] - 1], "urls": r["urls"], "block_urls": r.get("block_urls", r["urls"])})
    sealed[key] = {k: r.get(k) for k in SEALED}
sb = (json.dumps(sealed, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode()
Path("sealed/verdicts_sealed.json").write_bytes(sb)
Path("blind/sample_blind.json").write_text(json.dumps({"seed": SEED, "tool": "verbatim 0.3.2 (tsyyan/lab cceceee)",
    "verdicts_sealed_sha256": hashlib.sha256(sb).hexdigest(), "items": sample}, ensure_ascii=False, indent=1) + "\n")
st, index, pages, k = Store("store"), Store("store").index(), {}, 0
for s in sample:
    for u in s["block_urls"]:
        cu = canonical_url(u)
        if cu in pages:
            continue
        pages[cu] = []
        for e in index.get(cu, []):
            row = {x: e.get(x) for x in ("sha256", "via", "provenance", "http_status", "error", "final_url")}
            if e.get("sha256"):
                k += 1
                row["file"] = f"{k:04d}.txt"
                data = st.read(e["sha256"])
                shutil.copyfile(st.root / "snapshots" / e["sha256"], f"blind/snapshots/{e['sha256']}")
                try:
                    text = layers(data, e.get("content_type"), e.get("content_encoding"))["visible"]
                except Exception as err:  # unreadable body: the labeller still has the raw bytes
                    text = f"(no text layer: {err})"
                Path("blind/pages", row["file"]).write_text(f"# {cu}\n# read via {row['via'] or 'direct'}, "
                                                            f"sha256 {e['sha256']}\n\n{text}\n")
            pages[cu].append(row)
Path("blind/pages/index.json").write_text(json.dumps(pages, ensure_ascii=False, indent=1) + "\n")
print(len(sample), "items,", k, "pages")
