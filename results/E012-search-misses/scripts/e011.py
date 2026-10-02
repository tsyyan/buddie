"""E012 on E011: every labelled E011 quote that verbatim 0.3.1 did not find, re-read now (access default as E011, but archive deferred:
Wayback is unreachable from the container and Common Crawl takes minutes per page; E011 read 2 of 249 pages through
it) and located with 0.3.1 (check_031.py) and 0.3.2 on the same bytes. Run in data/ (gitignored, store in data/store).
E011's own snapshots were not committed, so pages may have changed since 2026-10-02 morning; an item whose page
cannot be read now is listed as unread. Writes ../e011.json.

Cloud container: VERBATIM_CHROMIUM=/opt/pw-browsers/chromium VERBATIM_BROWSER_CA=/root/.ccr/agent-proxy-ca.crt.
"""
import json, os, sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import check_031 as old
from verbatim import check as new
from verbatim.access import parse
from verbatim.store import Store

LAB = Path(__file__).resolve().parents[3]
E011 = LAB / "experiments/E011-example-hints"
OK = {"FOUND", "FOUND_NORMALIZED"}
items = json.loads((E011 / "sample_blind.json").read_text())["items"]
sealed = json.loads((E011 / "verdicts_sealed.json").read_text())
la = {x["key"]: x["label"] for x in json.loads((E011 / "labels_A.json").read_text())}
lb = {x["key"]: x["label"] for x in json.loads((E011 / "labels_B.json").read_text())}
st = Store("store")
rows = []
for it in items:
    k = it["key"]
    if sealed[k]["verdict"] in OK | {"NO_SOURCE", "SOURCE_UNAVAILABLE"}:
        continue
    r = new.check_claims([dict(it, id=k)], st, fetch=True, access=parse("default"), defer=("archive",))[0]
    row = {"key": k, "label": la[k] if la[k] == lb[k] else f"{la[k]}|{lb[k]}", "v031_then": sealed[k]["verdict"]}
    if not r.get("sha256"):
        row.update(unread=r.get("error"))
    else:
        data = st.read(r["sha256"])
        e = next(e for es in st.index().values() for e in es if e.get("sha256") == r["sha256"])
        po, pn = (m.Page(data, e.get("content_type"), e.get("content_encoding")) for m in (old, new))
        a, b = po.locate(it["quote"]), pn.locate(it["quote"])
        row.update(v031_now=a["verdict"], v032_now=b["verdict"], note=b.get("note"), tag=b.get("tag"),
                   repaired=pn.repaired or None, via=r.get("via"))
    rows.append(row)
    print(row, flush=True)
gained = [r for r in rows if r.get("v032_now") in OK and r.get("v031_now") not in OK]
out = {"misses_031": len(rows), "unread_now": [r["key"] for r in rows if "unread" in r],
       "found_now_by_031": [r["key"] for r in rows if r.get("v031_now") in OK],
       "found_by_032_only": [r["key"] for r in gained],
       "hidden_agent_errors": [r["key"] for r in gained if "AGENT_" in r["label"]], "rows": rows}
Path("../e011.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
print({k: v for k, v in out.items() if k != "rows"})
