"""buddie command line.

  buddie verify REPORT [--repo DIR ...] [--no-fetch] [--access default] [--numbers gap|fail|off] [--json receipt.json]
                [--transcript SESSION.jsonl] [--no-github]
                                    receipt for a report; exit 1 on FAIL
  buddie mandate queue|accepted|verdict [N ...] [--repo DIR] [--rev COMMIT]
                                    the work queue itself: done rows anchored, accepted plans quoting the user,
                                    auto/ask per row; exit 1 when a claim is BROKEN
  buddie serve                      MCP server on stdio (verify_report, snap, source_text)
  buddie hook                       Claude Code hook: reads the event on stdin, exit 2 blocks a FAIL answer
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def cmd_verify(args) -> int:
    from buddie.anchors import find_repos
    from buddie.effects import github_get
    from buddie.verify import verify
    text = sys.stdin.read() if args.report == "-" else Path(args.report).read_text(encoding="utf-8")
    repos = [Path(r) for r in args.repo] if args.repo else find_repos(Path.cwd())
    receipt = verify(text, name=args.report, repos=repos, store=args.store, fetch=not args.no_fetch,
                     access=args.access, quotes=not args.anchors_only, rev=args.rev,
                     github=None if args.no_github else github_get, transcript=args.transcript,
                     numbers=args.numbers)
    pred = receipt["predicate"]
    if args.json:
        Path(args.json).write_text(json.dumps(receipt, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for item in pred["blocking"]:
        print(f"BLOCK {item}")
    for item in pred["gaps"]:
        print(f"gap   {item}")
    for item in pred.get("notes", []):
        print(f"note  {item}")
    print(pred["line"])
    return 1 if pred["outcome"] == "FAIL" else 0


def cmd_mandate(args) -> int:
    from buddie import mandate as man
    from buddie.anchors import find_repos
    repos = [Path(r) for r in args.repo] if args.repo else find_repos(Path.cwd())
    cfg = man.find_config(repos)
    if cfg is None:
        print(f"no {man.CONFIG} with a [mandate] section in {', '.join(map(str, repos)) or 'cwd'}", file=sys.stderr)
        return 2
    if args.what == "queue":
        out = man.check_queue(cfg, args.rev)
        claims = out["done"]
    elif args.what == "accepted":
        out = claims = man.check_accepted(cfg, args.rev)
    else:
        m = man.Mandate(cfg, args.rev)
        out = [m.verdict(n) for n in (args.rows or [n for n in sorted(m.table)
                                                    if m.table[n]["status"].startswith(cfg["proposed"])])]
        claims = []
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 1 if man.outcome(claims) == "FAIL" else 0


def cmd_serve(args) -> int:
    from buddie.mcp import serve
    return serve()


def cmd_hook(args) -> int:
    from buddie.hook import main
    return main()


def main(argv: list[str] | None = None) -> int:
    from buddie import __version__
    p = argparse.ArgumentParser(prog="buddie", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"buddie {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("verify", help="receipt for a report")
    s.add_argument("report", help="Markdown file, or - for stdin")
    s.add_argument("--repo", action="append", help="repo checkout for anchors (repeatable; default: around cwd)")
    s.add_argument("--store", help="snapshot store (default $VERBATIM_STORE or ./.verbatim)")
    s.add_argument("--no-fetch", action="store_true", help="only use snapshots already in the store")
    s.add_argument("--access", help="verbatim access cascade for unreadable pages, e.g. default")
    s.add_argument("--anchors-only", action="store_true", help="skip quotes")
    s.add_argument("--json", help="write the receipt here")
    s.add_argument("--rev", help="judge work claims against the queue as of this commit")
    s.add_argument("--transcript", help="Claude Code session jsonl for run: anchors")
    s.add_argument("--no-github", action="store_true", help="leave pr:/ci: anchors UNCHECKABLE (offline)")
    s.add_argument("--numbers", choices=("gap", "fail", "off"), default="gap",
                   help="a number of a cited sentence not in its source: a gap (default), a failure, or not checked")
    s.set_defaults(func=cmd_verify)
    m = sub.add_parser("mandate", help="check the work queue and the accepted plans (buddie.toml [mandate])")
    m.add_argument("what", choices=("queue", "accepted", "verdict"))
    m.add_argument("rows", nargs="*", type=int)
    m.add_argument("--repo", action="append", help="repo checkout with buddie.toml (default: around cwd)")
    m.add_argument("--rev", help="the queue as of this commit")
    m.set_defaults(func=cmd_mandate)
    sub.add_parser("serve", help="MCP server on stdio").set_defaults(func=cmd_serve)
    sub.add_parser("hook", help="Claude Code hook on stdin").set_defaults(func=cmd_hook)
    args = p.parse_args(argv)
    return args.func(args)
