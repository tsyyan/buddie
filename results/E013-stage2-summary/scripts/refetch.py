"""E013 step 1: re-read the pages of every labelled E010 and E011 quote (their snapshots were not committed) and
locate the quote with 0.3.1's search (check_031.py = check.py at d976963, the same as 0.3.0's at 5e372cb) and with
0.3.2's on the same bytes. The cascade is E010/E011's (`--access default`) with archive deferred, as in E012: Wayback
is unreachable from the container and Common Crawl takes minutes per page. Run in data/ (gitignored); writes
../refetch.json. Each row keeps the full 0.3.2 check result too, for a reader.

Cloud container: VERBATIM_CHROMIUM=/opt/pw-browsers/chromium VERBATIM_BROWSER_CA=/root/.ccr/agent-proxy-ca.crt.
"""
import json, os, sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import check_031 as old
from verbatim import check as new
from verbatim.access import parse
from verbatim.report import from_markdown
from verbatim.store import Store

LAB = Path(__file__).resolve().parents[3]
SETS = {"E010": LAB / "experiments/E010-not-a-quote", "E011": LAB / "experiments/E011-example-hints"}


def claim(it):
    """The quote as 0.3.2's report reader sees it in its paragraph (kind, attribution); links from the sample."""
    found = [c for c in from_markdown(it["paragraph"] + "\n")[0] if c["quote"] == it["quote"]]
    c = dict(found[0]) if found else {"quote": it["quote"]}
    c.update(id=it["key"], urls=it["urls"], block_urls=it.get("block_urls") or [])
    return c


st = Store("store")
out = {}
for name, exp in SETS.items():
    rows = {}
    for it in json.loads((exp / "sample_blind.json").read_text())["items"]:
        k = it["key"]
        r = new.check_claims([claim(it)], st, fetch=True, access=parse("default"), defer=("archive",))[0]
        row = {"check_032": {x: r.get(x) for x in ("verdict", "miss", "not_quote", "note", "doubts", "url", "via",
                                                    "sha256", "error", "repaired")}}
        if r.get("sha256"):
            e = next(e for es in st.index().values() for e in es if e.get("sha256") == r["sha256"])
            data = st.read(r["sha256"])
            po, pn = (m.Page(data, e.get("content_type"), e.get("content_encoding")) for m in (old, new))
            row.update(v031_now=po.locate(it["quote"])["verdict"], v032_now=pn.locate(it["quote"])["verdict"])
        rows[k] = row
        print(name, k, row.get("v031_now"), row.get("v032_now"), r["verdict"], flush=True)
    out[name] = rows
Path("../refetch.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
