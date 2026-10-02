"""E010 step 3. Run in data/ after run.py: the blind sample and its sealed verdicts (as E008 step 3).

Pool: quotes of >= 6 words whose own page was read (checked: not SOURCE_UNAVAILABLE / NO_SOURCE, >= 1500 visible
characters). The sample is every checked miss (NOT_FOUND, UNCERTAIN, and the new NOT_A_QUOTE), every find that only the
new punctuation rule made (note "punctuation"), plus CONTROLS random other checked finds (FOUND, FOUND_NORMALIZED,
FOUND_IN_COPY), shuffled with SEED. The finds are there for two reasons: they measure whether a find
can hide an agent error, and the labeller cannot assume every item is a miss.

Writes into blind/ (what the labeller gets) and sealed/ (what it must not read until its labels are committed):
  blind/sample_blind.json   key, system, task, quote, report paragraph, own links (urls), every link of the paragraph
                            (block_urls), report line. No verdict, doubts, closest passage, via or page size.
  blind/pages/<n>.txt       visible text of every snapshot the store holds for those links (direct fetch, browser,
                            archive, open access, copy), one file per snapshot, with a header naming how it was read;
                            blind/pages/index.json maps URL -> [{file, sha256, via, provenance, http_status, error}].
  blind/snapshots/<sha256>  the raw bytes, to check the text layer when a quote seems absent.
  sealed/verdicts_sealed.json  verbatim's verdict for each key; its sha256 goes into sample_blind.json.
"""
import hashlib, json, random, shutil
from pathlib import Path

from verbatim.store import Store, canonical_url
from verbatim.textlayer import layers

SEED = 2028
CONTROLS = 30
OK = ("FOUND", "FOUND_NORMALIZED", "FOUND_IN_COPY")
SEALED = ("verdict", "doubts", "url", "sha256", "via", "provenance", "found_in", "error", "closest", "first_read",
          "page_chars", "binding", "not_quote", "miss", "note")


def checked(c):
    return c["verdict"] not in ("SOURCE_UNAVAILABLE", "NO_SOURCE") and c.get("page_chars", 0) >= 1500


out = json.load(open("results.json"))
md = {(o["system"], o["id"]): Path("md", o["system"], f"row-{o['id']}.md").read_text().splitlines() for o in out}
miss, found = [], []
for o in out:
    for c in o["claims"]:
        if checked(c):
            if c["verdict"] not in OK or c.get("note") == "punctuation":
                miss.append((o["system"], o["id"], c))
            else:
                found.append((o["system"], o["id"], c))
random.seed(SEED)
items = miss + random.sample(found, min(CONTROLS, len(found)))
random.shuffle(items)

Path("blind/pages").mkdir(parents=True, exist_ok=True)
Path("blind/snapshots").mkdir(exist_ok=True)
Path("sealed").mkdir(exist_ok=True)
sample, sealed = [], {}
for n, (m, task, c) in enumerate(items, 1):
    key = f"F{n:03d}"
    sample.append({"key": key, "system": m, "task": task, "line": c["line"], "quote": c["quote"],
                   "paragraph": md[(m, task)][c["line"] - 1], "urls": c["urls"],
                   "block_urls": c.get("block_urls", c["urls"])})
    sealed[key] = {k: c.get(k) for k in SEALED}
sealed_bytes = (json.dumps(sealed, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode()
Path("sealed/verdicts_sealed.json").write_bytes(sealed_bytes)
doc = {"seed": SEED, "tool": "verbatim 0.3.0, check --access default (tsyyan/lab 5e372cb)",
       "pool": {"checked_misses_and_punctuation_finds": len(miss), "checked_finds": len(found), "controls": min(CONTROLS, len(found))},
       "verdicts_sealed_sha256": hashlib.sha256(sealed_bytes).hexdigest(), "items": sample}
Path("blind/sample_blind.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")

st = Store("store")
index = st.index()
pages, seen = {}, {}
for s in sample:
    for u in s["block_urls"]:
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
                    except Exception as ex:  # unreadable bytes: the labeller still has the raw file
                        text = f"[text layer failed: {ex}]"
                    head = f"# {cu}\n# read via {e.get('via') or 'direct'} ({e.get('provenance') or 'publisher'})," \
                           f" HTTP {e.get('http_status')}, final {e.get('final_url')}, sha256 {sha}\n\n"
                    Path("blind/pages", seen[sha]).write_text(head + text)
                row["file"] = seen[sha]
            rows.append(row)
        pages[cu] = rows
Path("blind/pages/index.json").write_text(json.dumps(pages, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
print(doc["pool"], len(sample), "urls", len(pages), "snapshots", len(seen))
