"""E008 step 2. Run in data/ after fetch_all.py: verbatim check --access default on every quote of >= 6 words.

The same as `verbatim check report.md --fetch --access default` per report, run in-process over 8 workers. Store.record
rewrites one index.json, so each worker gets its own copy of store/ (snapshots hard-linked) and the new entries the
cascade adds (browser, archive, open access) are merged back into store/ at the end. Writes results.json.

Cloud container: VERBATIM_CHROMIUM=/opt/pw-browsers/chromium VERBATIM_BROWSER_CA=/root/.ccr/agent-proxy-ca.crt
(certutil from libnss3-tools). Wayback is unreachable from there, so `archive` falls through to Common Crawl.
"""
import json, multiprocessing as mp, os, shutil, subprocess, sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from reports import reports
from verbatim.access import parse
from verbatim.check import check_claims, summary
from verbatim.report import from_markdown
from verbatim.store import Store

N = 8
MIN_WORDS = 6


TAG = os.environ.get("E008_TAG", "")  # a second runner (E008_TAG=r) walks each worker's reports backwards


def work(k: int) -> list[dict]:
    root = Path(f"stores/{TAG}{k}")
    if not root.exists():
        root.mkdir(parents=True)
        subprocess.run(["cp", "-al", "store/snapshots", str(root / "snapshots")], check=True)
        shutil.copyfile("store/index.json", root / "index.json")
    st, out = Store(root), []
    done = Path(f"stores/{TAG}{k}.jsonl")
    other = Path(f"stores/{'' if TAG else 'r'}{k}.jsonl")
    mine = list(enumerate(reports()))
    for i, (m, task, text) in reversed(mine) if TAG else mine:
        seen = {(o["system"], o["id"]) for f in (done, other) if f.exists() for o in map(json.loads, f.open())}
        if i % N != k or (m, task) in seen:
            continue
        claims = [c for c in from_markdown(text)[0] if c["urls"] and len(c["quote"].split()) >= MIN_WORDS]
        if not claims:
            continue
        res = check_claims(claims, st, fetch=True, access=parse("default"))
        with done.open("a") as f:
            f.write(json.dumps({"system": m, "id": task, "summary": summary(res), "claims": res}, ensure_ascii=False) + "\n")
        print(k, m, task, summary(res), flush=True)
    return k


if __name__ == "__main__":
    with mp.Pool(N) as pool:
        for k in pool.imap_unordered(work, range(N)):
            print("worker done", k, flush=True)
    if TAG:
        sys.exit(0)  # the first runner merges
    out = {}
    for f in sorted(Path("stores").glob("*.jsonl")):
        for line in open(f):
            o = json.loads(line)
            out.setdefault((o["system"], o["id"]), o)  # a report both runners reached: keep the first
    out = list(out.values())
    out.sort(key=lambda o: (o["system"], o["id"]))
    Path("results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    main = Store("store")
    orig = main.index()  # what every worker started from
    base = json.loads(json.dumps(orig))
    for root in sorted(p for p in Path("stores").iterdir() if p.is_dir()):
        idx = json.loads((root / "index.json").read_text())
        for u, es in idx.items():
            n = len(orig.get(u, []))
            for e in es[n:]:
                if e.get("sha256") and not (main.snapshots / e["sha256"]).exists():
                    shutil.copyfile(root / "snapshots" / e["sha256"], main.snapshots / e["sha256"])
            base.setdefault(u, []).extend(es[n:])
    main._write_index(base)
    print("reports", len(out))
