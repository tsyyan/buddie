"""E014 step 2. Run in data/ after run.py: the blind sample and its sealed verdicts (as E010 step 3).

Checked: the own page was read (not SOURCE_UNAVAILABLE / NO_SOURCE) and has >= 1500 visible characters (E010).
Sample: every checked quote 0.3.2 did not find (NOT_FOUND, UNCERTAIN, NOT_A_QUOTE) plus CONTROLS random checked finds
(FOUND, FOUND_NORMALIZED, FOUND_IN_COPY), shuffled with SEED. Writes blind/ (labellers' input) and
sealed/verdicts_sealed.json, whose sha256 goes into blind/sample_blind.json before labelling.
"""
import hashlib, json, random, shutil
from pathlib import Path

from verbatim.store import Store, canonical_url
from verbatim.textlayer import layers

SEED, CONTROLS = 2032, 30
OK = ("FOUND", "FOUND_NORMALIZED", "FOUND_IN_COPY")
SEALED = ("verdict", "doubts", "url", "sha256", "via", "provenance", "found_in", "error", "closest", "first_read",
          "page_chars", "binding", "not_quote", "miss", "note", "family")


def checked(c):
    return c["verdict"] not in ("SOURCE_UNAVAILABLE", "NO_SOURCE") and c.get("page_chars", 0) >= 1500


res = [r for r in json.load(open("results.json")) if checked(r)]
miss = [r for r in res if r["verdict"] not in OK]
found = [r for r in res if r["verdict"] in OK]
random.seed(SEED)
items = miss + random.sample(found, min(CONTROLS, len(found)))
random.shuffle(items)
for d in ("blind/pages", "blind/snapshots", "sealed"):
    Path(d).mkdir(parents=True, exist_ok=True)
sample, sealed = [], {}
for n, r in enumerate(items, 1):
    key = f"S{n:03d}"
    lines = Path("md", r["file"]).read_text().splitlines()
    sample.append({"key": key, "system": r["file"].split("/")[0], "task": r["file"].split("/")[1], "line": r["line"],
                   "quote": r["quote"], "paragraph": lines[r["line"] - 1], "urls": r["urls"],
                   "block_urls": r.get("block_urls", r["urls"])})
    sealed[key] = {k: r.get(k) for k in SEALED}
sb = (json.dumps(sealed, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode()
Path("sealed/verdicts_sealed.json").write_bytes(sb)
summ = json.load(open("../summary.json"))
Path("blind/sample_blind.json").write_text(json.dumps({"seed": SEED, "tool": summ["tool"],
    "verdicts_sealed_sha256": hashlib.sha256(sb).hexdigest(), "misses": len(miss), "controls": len(items) - len(miss),
    "items": sample}, ensure_ascii=False, indent=1) + "\n")
st = Store("store")
index, pages, k = st.index(), {}, 0
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
                shutil.copyfile(st.root / "snapshots" / e["sha256"], f"blind/snapshots/{e['sha256']}")
                try:
                    text = layers(st.read(e["sha256"]), e.get("content_type"), e.get("content_encoding"))["visible"]
                except Exception as err:  # unreadable body: the labeller still has the raw bytes
                    text = f"(no text layer: {err})"
                Path("blind/pages", row["file"]).write_text(f"# {cu}\n# read via {row['via'] or 'direct'}, "
                                                            f"sha256 {e['sha256']}\n\n{text}\n")
            pages[cu].append(row)
Path("blind/pages/index.json").write_text(json.dumps(pages, ensure_ascii=False, indent=1) + "\n")
print(len(sample), "items:", len(miss), "misses +", len(items) - len(miss), "controls;", k, "pages")
