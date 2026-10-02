"""verbatim command line.

  verbatim snap URL [URL ...]          fetch each URL and keep its bytes in the store
  verbatim add URL FILE                put bytes you already have (curl output, a saved page) in the store
  verbatim text URL|SHA [--grep RE]    print the visible text of a snapshot (read and quote from this, not from a summary)
  verbatim check REPORT [--fetch]      verdict for every quote in a Markdown/JSON report; exit 1 on any NOT_FOUND
                 [--access default]    unreadable cited page: try a browser, archives, open-access copies, known copies
                                       (--strict: exit 1 unless every quote is found)
                 [--defer archive]     leave a method for elsewhere; the URLs that need it go to the JSON's "deferred"
  verbatim access METHOD URL ... | --from JSON   run one access method (archive in GitHub Actions) into the store
  verbatim merge OTHER_STORE           add another store's snapshots and index entries to this one

Store: --store DIR, else $VERBATIM_STORE, else ./.verbatim
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from verbatim import __version__
from verbatim.access import parse as parse_access
from verbatim.check import OK, check_claims, summary
from verbatim.report import load
from verbatim.store import Store, now
from verbatim.textlayer import Unreadable, layers

MARK = {"FOUND": "ok  ", "FOUND_NORMALIZED": "ok~ ", "HIDDEN_ONLY": "HID ", "FOUND_IN_COPY": "copy", "UNCERTAIN": "miss?", "NOT_A_QUOTE": "notq", "NOT_FOUND": "MISS",
        "SOURCE_UNAVAILABLE": "N/A ", "NO_SOURCE": "NOSRC"}


def _short(text: str, n: int = 90) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def cmd_snap(args) -> int:
    store, bad = Store(args.store), 0
    for url in args.urls:
        e = store.fetch(url)
        if e.get("sha256"):
            print(f"{e['sha256'][:12]}  {e['http_status']}  {e['bytes']:>9} B  {url}")
        else:
            bad += 1
            print(f"{'-' * 12}  {e.get('error')}  {url}", file=sys.stderr)
    return 1 if bad else 0


def cmd_add(args) -> int:
    data = Path(args.file).read_bytes()
    e = Store(args.store).add(args.url, data, content_type=args.content_type, fetched_at=args.fetched_at)
    print(f"{e['sha256'][:12]}  {e['bytes']:>9} B  {args.url}")
    return 0


def cmd_text(args) -> int:
    try:
        entry, data = Store(args.store).resolve(args.ref)
    except KeyError:
        print(f"no snapshot for {args.ref}; run: verbatim snap {args.ref}", file=sys.stderr)
        return 1
    try:
        lay = layers(data, entry.get("content_type"), entry.get("content_encoding"))
    except Unreadable as error:
        print(f"{args.ref}: {error}", file=sys.stderr)
        return 1
    text = lay["hidden"] if args.hidden else lay["visible"]
    print(f"# {entry.get('final_url')}  sha256={entry['sha256']}  fetched_at={entry.get('fetched_at')}",
          file=sys.stderr)
    if not args.grep:
        print(text)
        return 0
    found = 0
    for m in re.finditer(args.grep, text, re.I):
        found += 1
        print(f"[{m.start()}] …{text[max(0, m.start() - args.context):m.end() + args.context]}…")
    return 0 if found else 1


def cmd_check(args) -> int:
    raw = Path(args.report).read_text()
    claims, skipped = load(args.report, raw, args.min_chars)
    copies = json.loads(Path(args.copies).read_text()) if args.copies else None
    deferred: set[str] = set()
    results = check_claims(claims, Store(args.store), fetch=args.fetch, access=parse_access(args.access),
                           copies=copies, defer=parse_access(args.defer), deferred=deferred)
    counts = summary(results)
    doc = {"tool": f"verbatim {__version__}", "checked_at": now(), "report": args.report,
           "report_sha256": hashlib.sha256(raw.encode()).hexdigest(), "summary": counts,
           "skipped_short_quotes": skipped, "claims": results}
    if args.defer:
        doc["deferred"] = {"methods": list(parse_access(args.defer)), "urls": sorted(deferred)}
    if args.json:
        Path(args.json).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
    if not args.quiet:
        for r in results:
            where = f"L{r['line']}" if r.get("line") else r["id"]
            print(f"{MARK[r['verdict']]} {where:<6} {_short(r['quote'])}")
            if r["verdict"] == "UNCERTAIN":
                print(f"       why uncertain: {', '.join(r['doubts'])}")
            if r["verdict"] == "NOT_A_QUOTE":
                print(f"       not a quote: {r['not_quote']}")
            if r["verdict"] in ("NOT_FOUND", "UNCERTAIN", "NOT_A_QUOTE") and r.get("closest", {}).get("text"):
                c = r["closest"]
                print(f"       closest ({c['ratio']:.2f}): {_short(c['text'])}")
            elif r["verdict"] == "SOURCE_UNAVAILABLE":
                print(f"       {r.get('error')}: {r.get('url')}")
            elif r["verdict"] == "FOUND_IN_COPY":
                print(f"       not the cited page; read via {r.get('via')}")
            if r.get("provenance") in ("archive", "open_access") and r["verdict"] in OK:
                print(f"       read via {r.get('via')}")
            elif r.get("note") or (r["verdict"] == "FOUND_NORMALIZED" and args.verbose):
                print(f"       matched: {_short(r.get('matched', ''))}")
    total = len(results)
    ok = sum(counts.get(v, 0) for v in OK)
    line = ", ".join(f"{k} {v}" for k, v in counts.items()) or "no quotes"
    print(f"verbatim: {ok}/{total} quotes found in their sources ({line})"
          + (f"; {skipped} short quotes skipped" if skipped else ""))
    if deferred:
        print(f"verbatim: {len(deferred)} URLs wait for {args.defer} (\"deferred\" in --json); run it elsewhere, "
              f"merge the store, check again")
    if args.strict:
        return 0 if ok == total else 1
    return 1 if counts.get("NOT_FOUND") else 0


def cmd_access(args) -> int:
    from verbatim import access as acc
    if args.method not in acc.METHODS:
        print(f"unknown method {args.method}; known: {', '.join(acc.METHODS)}", file=sys.stderr)
        return 2
    urls = list(args.urls)
    for path in args.from_json or []:
        doc = json.loads(Path(path).read_text())
        urls += doc["deferred"]["urls"] if isinstance(doc, dict) else doc
    from concurrent.futures import ThreadPoolExecutor
    store, ok, urls = Store(args.store), 0, list(dict.fromkeys(urls))
    jobs = 1 if args.method == "browser" else max(1, args.jobs)  # one Chromium per process, not thread-safe
    with ThreadPoolExecutor(jobs) as pool:
        for url, e in zip(urls, pool.map(lambda u: acc.METHODS[args.method](store, u), urls)):
            if e and e.get("sha256"):
                ok += 1
                print(f"{e['sha256'][:12]}  {e.get('via')}  {url}", flush=True)
            else:
                print(f"{'-' * 12}  {(e or {}).get('error', 'does not apply')}  {url}", flush=True)
    print(f"verbatim access {args.method}: {ok}/{len(urls)} URLs read")
    return 0


def cmd_merge(args) -> int:
    store, other = Store(args.store), Store(args.other)
    index, added = store.index(), 0
    for url, entries in other.index().items():
        have = index.setdefault(url, [])
        for e in entries:
            if e in have:
                continue
            if e.get("sha256"):
                store.put(other.read(e["sha256"]))
            have.append(e)
            added += 1
    store._write_index(index)
    print(f"verbatim merge: {added} entries from {args.other}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="verbatim", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"verbatim {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--store", help="snapshot store directory (default: $VERBATIM_STORE or ./.verbatim)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("snap", parents=[common], help="fetch URLs into the store")
    s.add_argument("urls", nargs="+")
    s.set_defaults(func=cmd_snap)

    s = sub.add_parser("add", parents=[common], help="put existing bytes in the store under a URL")
    s.add_argument("url")
    s.add_argument("file")
    s.add_argument("--content-type")
    s.add_argument("--fetched-at", help="UTC time the bytes were fetched (default: now)")
    s.set_defaults(func=cmd_add)

    s = sub.add_parser("text", parents=[common], help="print the visible text of a snapshot")
    s.add_argument("ref", help="URL or sha256 (prefix)")
    s.add_argument("--grep", help="regex; print only matches with context")
    s.add_argument("--context", type=int, default=120)
    s.add_argument("--hidden", action="store_true", help="print script/meta/alt text instead")
    s.set_defaults(func=cmd_text)

    s = sub.add_parser("check", parents=[common], help="check every quote in a report")
    s.add_argument("report", help="Markdown file, or JSON with claims [{quote, url}]")
    s.add_argument("--fetch", action="store_true", help="snapshot cited URLs that are not in the store yet")
    s.add_argument("--access", metavar="METHODS",
                   help="when a cited page cannot be read: 'default' (browser,archive,open_access,copy), 'all' "
                        "(adds the third-party relay), or a comma list; see verbatim/access.py")
    s.add_argument("--copies", metavar="JSON", help='{"cited URL": ["republished copy URL", ...]} for --access copy')
    s.add_argument("--json", help="write the full verdicts here")
    s.add_argument("--min-chars", type=int, default=12)
    s.add_argument("--quiet", action="store_true", help="only the summary line")
    s.add_argument("--strict", action="store_true",
                   help="exit 1 unless every quote is found (default: exit 1 only on NOT_FOUND)")
    s.add_argument("--verbose", action="store_true")
    s.add_argument("--defer", metavar="METHODS", help="access methods not to run here, e.g. archive (see access)")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("access", parents=[common], help="run one access method on URLs and store what it reads")
    s.add_argument("method", help="browser, archive, open_access, relay")
    s.add_argument("urls", nargs="*")
    s.add_argument("--from", dest="from_json", action="append", metavar="JSON",
                   help='a check --json with "deferred", or a JSON list of URLs; repeatable')
    s.add_argument("--jobs", type=int, default=1, help="URLs in parallel (archive in Actions: 8)")
    s.set_defaults(func=cmd_access)

    s = sub.add_parser("merge", parents=[common], help="add another store's entries to this one")
    s.add_argument("other")
    s.set_defaults(func=cmd_merge)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
