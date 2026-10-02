"""E012 step 1. Run in data/ after get_dataset.py: verbatim check --fetch --access default (0.3.2) on every quote of
>= 6 words with a link in md/ (archive deferred, as in e011.py), then every quote 0.3.2 did not find
exactly is located again with 0.3.1
(scripts/check_031.py) on the same snapshot, so the new rules' effect is read off one read of each page.
Writes results.json (not committed: report paragraphs) and ../summary.json.

Cloud container: VERBATIM_CHROMIUM=/opt/pw-browsers/chromium VERBATIM_BROWSER_CA=/root/.ccr/agent-proxy-ca.crt.
"""
import json, os, sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import check_031 as old
from verbatim.access import parse
from verbatim.check import check_claims, summary
from verbatim.report import from_markdown
from verbatim.store import Store

MIN_WORDS = 6
OK = {"FOUND", "FOUND_NORMALIZED"}
st = Store("store")
out = []
for path in sorted(Path("md").glob("*/*.md")):
    claims = [c for c in from_markdown(path.read_text())[0] if c["urls"] and len(c["quote"].split()) >= MIN_WORDS]
    if not claims:
        continue
    res = check_claims(claims, st, fetch=True, access=parse("default"), defer=("archive",))
    for r in res:
        r["file"] = str(path.relative_to("md"))
        if r.get("sha256"):
            e = next(e for es in st.index().values() for e in es if e.get("sha256") == r["sha256"])
            pg = old.Page(st.read(r["sha256"]), e.get("content_type"), e.get("content_encoding"))
            r["v031_locate"] = pg.locate(r["quote"])["verdict"]
    out.extend(res)
    print(path, summary(res), flush=True)
Path("results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
checked = [r for r in out if r.get("sha256")]
changed = [r for r in checked if r["verdict"] in OK and r.get("v031_locate") not in OK]
doc = {"quotes": len(out), "reports_with_quotes": len({r["file"] for r in out}), "checked": len(checked),
       "verdicts_032": summary(out), "found_by_032_only": [{k: r.get(k) for k in ("file", "id", "line", "note", "tag",
                                                                                    "repaired", "url")} for r in changed],
       "notes_032": dict(Counter(r.get("note") for r in checked if r["verdict"] in OK and r.get("note")))}
Path("../summary.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
print({k: v for k, v in doc.items() if k != "found_by_032_only"}, len(changed))
