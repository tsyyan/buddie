"""Blind relabel E004: build a dossier per miss from fresh snapshots (no labels read)."""
import json, re
from verbatim.store import Store
from verbatim.check import check_claims, Page, loose
st = Store("store")
d = json.load(open("sample_blind.json"))  # sample_labeled.json without "label", plus "urls" of each quote from the full report
res = check_claims([{"id": x["key"], "quote": x["quote"], "urls": x["urls"]} for x in d], st)
per = [[check_claims([{"id":"u","quote":x["quote"],"urls":[u]}], st)[0] for u in x["urls"]] for x in d]
out = []
for x, r, pu in zip(d, res, per):
    e = st.latest(r.get("url") or x["url"]) or {}
    ctx = ""
    words = []
    if e.get("sha256") and r["verdict"] not in ("SOURCE_UNAVAILABLE",):
        try:
            pg = Page(st.read(e["sha256"]), e.get("content_type"), e.get("content_encoding"))
            off = r.get("visible_offset") if "visible_offset" in r else r.get("closest", {}).get("visible_offset")
            if off is not None:
                ctx = pg.visible[max(0, off - 500): off + 700]
            # which distinctive quote words are absent from the page
            pl = pg.visible_loose
            words = [w for w in set(re.findall(r"[a-z0-9%$.]{5,}", loose(x["quote"])[0])) if w not in pl]
        except Exception as ex:
            ctx = f"ERR {ex}"
    out.append({"key": x["key"], "system": x["system"], "quote": x["quote"], "url": x["url"],
                "best_url": r.get("url"), "per_url": [(p.get("url","")[:110], p["verdict"], p.get("closest",{}).get("ratio"), p.get("error")) for p in pu], "orig_ratio": x["ratio"], "orig_near": x["near"], "same_sha": e.get("sha256") == x["sha256"],
                "fresh_verdict": r["verdict"], "fresh_err": r.get("error"), "fresh_ratio": r.get("closest", {}).get("ratio"),
                "missing_words": sorted(words), "line": x["line"], "context": ctx})
json.dump(out, open("dossier.json", "w"), ensure_ascii=False, indent=1)
from collections import Counter
print(Counter(o["fresh_verdict"] for o in out), Counter(o["same_sha"] for o in out))
