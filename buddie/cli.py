"""buddie command line.

  buddie verify REPORT [--repo DIR ...] [--no-fetch] [--access default] [--numbers gap|fail|off] [--json receipt.json]
                [--transcript SESSION.jsonl] [--no-github]
                                    receipt for a report; exit 1 on FAIL
  buddie mandate queue|accepted|verdict [N ...] [--repo DIR] [--rev COMMIT]
                                    the work queue itself: done rows anchored, accepted plans quoting the user,
                                    auto/ask per row; exit 1 when a claim is BROKEN
  buddie journal lessons|measure [PATH ...] [--since TIME] [--sessions 10] [--skip SESSION]
                                    the gate's journal (files or dirs of *.jsonl; default: the hook's own): what
                                    past sessions were sent back for (SessionStart prints it), and NEXT №55's measure
  buddie summary [--session ID] [--repo DIR] [--no-queue] [--stale 30] [--text]
                                    when no subagent is left: what they did, what was lost, the next steps with
                                    auto/ask and a ready AskUserQuestion card (JSON; --text only the text)
  buddie init [--repo DIR]          write buddie.toml with the default levels and the intro mode on
  buddie intro [--false] [--repo DIR]
                                    where the intro mode stands; --false: the last return was false, restart the count
  buddie enforce [--repo DIR]       end the intro mode: returns block from now on
  buddie serve                      MCP server on stdio (verify_report, snap, source_text, summary)
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


def cmd_journal(args) -> int:
    from buddie import journal
    from buddie.hook import journal_paths
    rows = journal.entries([Path(p) for p in args.paths] if args.paths else journal_paths())
    if args.what == "lessons":
        print(journal.lessons(rows, skip_session=args.skip))
    else:
        print(json.dumps(journal.measure(rows, args.since, args.sessions), ensure_ascii=False, indent=1))
    return 0


def cmd_summary(args) -> int:
    from buddie.anchors import find_repos
    from buddie.summary import summarize
    repos = [Path(r) for r in args.repo] if args.repo else find_repos(Path.cwd())
    out = summarize(args.session, repos, queue=not args.no_queue, stale=args.stale)
    print(out["text"] if args.text else json.dumps(out, ensure_ascii=False, indent=1))
    if args.text and out["card"]:
        print(json.dumps(out["card"], ensure_ascii=False))
    return 0


def _config_path(args) -> Path | None:
    from buddie import config
    from buddie.anchors import find_repos
    return config.find([Path(r) for r in args.repo] if args.repo else find_repos(Path.cwd()) or [Path.cwd()])


def cmd_init(args) -> int:
    from buddie import config
    from buddie.anchors import find_repos
    repo = Path(args.repo[0]) if args.repo else (find_repos(Path.cwd()) or [Path.cwd()])[0]
    try:
        path = config.init(repo)
    except FileExistsError as e:
        print(f"{e} exists; not overwritten", file=sys.stderr)
        return 1
    print(f"wrote {path}: intro mode for the next {config.INIT_FINALS} final answers (returns only warn)")
    return 0


def cmd_intro(args, enforce: bool = False) -> int:
    from buddie import config
    path = _config_path(args)
    if path is None:
        print(f"no {config.CONFIG} here: run `buddie init`", file=sys.stderr)
        return 2
    if enforce:
        config.enforce(path)
    elif args.false:
        config.false_return(path)
    tour = config.intro(path, config.load(path))
    print(f"{path}: " + (f"intro, {tour['seen']} of {tour['finals']} final answers passed without a false return"
                         if tour else "enforced: returns block"))
    return 0


def cmd_serve(args) -> int:
    from buddie.mcp import serve
    return serve()


def cmd_hook(args) -> int:
    from buddie.hook import main
    return main()


def main(argv: list[str] | None = None) -> int:
    from buddie import __version__
    for stream in (sys.stdout, sys.stderr):  # quotes, anchors and reasons are UTF-8 on every OS (Windows: cp1252)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
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
    j = sub.add_parser("journal", help="the gate's journal: lessons for a new session, the closed-loop measure")
    j.add_argument("what", choices=("lessons", "measure"))
    j.add_argument("paths", nargs="*", help="journal files or directories of *.jsonl (default: the hook's own)")
    j.add_argument("--since", default="", help="measure: sessions that started at or after this time")
    j.add_argument("--sessions", type=int, default=10, help="measure: the first N such sessions (0: all)")
    j.add_argument("--skip", help="lessons: leave out this session")
    j.set_defaults(func=cmd_journal)
    u = sub.add_parser("summary", help="summary of the subagents' results and a choice card for the next steps")
    u.add_argument("--session", help="the session (default: the one whose hook state changed last)")
    u.add_argument("--repo", action="append", help="repo checkout with buddie.toml for the queue (default: around cwd)")
    u.add_argument("--no-queue", action="store_true", help="only the steps the subagents named, not the queue's rows")
    u.add_argument("--stale", type=int, default=30, help="minutes of silence before a started subagent counts as lost")
    u.add_argument("--text", action="store_true", help="print the text, then the card as one JSON line")
    u.set_defaults(func=cmd_summary)
    i = sub.add_parser("init", help="write buddie.toml with the default levels and the intro mode on")
    i.add_argument("--repo", action="append", help="where to write it (default: the repo around cwd)")
    i.set_defaults(func=cmd_init)
    t = sub.add_parser("intro", help="where the intro mode stands; --false reports a false return")
    t.add_argument("--false", action="store_true", help="the last return was false: restart the count")
    t.add_argument("--repo", action="append", help="repo with buddie.toml (default: around cwd)")
    t.set_defaults(func=cmd_intro)
    e = sub.add_parser("enforce", help="end the intro mode")
    e.add_argument("--repo", action="append", help="repo with buddie.toml (default: around cwd)")
    e.set_defaults(func=lambda args: cmd_intro(args, enforce=True))
    sub.add_parser("serve", help="MCP server on stdio").set_defaults(func=cmd_serve)
    sub.add_parser("hook", help="Claude Code hook on stdin").set_defaults(func=cmd_hook)
    args = p.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as e:
        if args.cmd not in ("verify", "mandate"):
            raise
        print(f"buddie {args.cmd}: {e}", file=sys.stderr)  # a missing report or --rev: usage, not FAIL (NEXT №105)
        return 2
