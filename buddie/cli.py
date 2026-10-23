"""buddie command line.

  buddie verify REPORT [--repo DIR ...] [--no-fetch] [--access default] [--numbers gap|fail|off] [--json receipt.json]
                [--transcript SESSION.jsonl] [--no-github]
                                    receipt for a report; exit 1 on FAIL
  buddie snapshot [--root DIR] [--artifact PATH ...] [--report FILE] [--supply KEY=VALUE ...] [--json FILE]
                                    what buddie observes of the environment: runtime, repository, artifacts
                                    (docs/environment.md); not a check, never signed
  buddie freshness ci --repo OWNER/REPO (--pr N | --commit SHA) --evidence SHA [--check NAME] [--json FILE]
  buddie freshness repo --commit SHA [--root DIR] [--artifact PATH=SHA256 ...] [--snapshot FILE] [--json FILE]
                                    whether evidence is bound to the revision a claim is about (docs/freshness.md):
                                    exit 0 CURRENT, 1 STALE, 3 UNKNOWN, 2 the input cannot be used
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
  buddie status [--repo DIR] [--last 50]
                                    what the hook does here now (config, levels, intro, transcript) and what the
                                    journal says about the last checks
  buddie intro [--false] [--repo DIR]
                                    where the intro mode stands; --false: the last return was false, restart the count
  buddie enforce [--repo DIR]       end the intro mode: returns block from now on
  buddie serve                      MCP server on stdio (verify_report, snap, source_text, summary)
  buddie serve --http [--host 127.0.0.1] [--port 8000]
                                    remote MCP server over Streamable HTTP at /mcp (remote.py: no files, no
                                    local repos, public addresses only)
  buddie hook                       Claude Code hook: reads the event on stdin, exit 2 blocks a FAIL answer
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def cmd_verify(args) -> int:
    from buddie.anchors import find_repos
    from buddie.effects import github_get
    from buddie import profiles, receipts
    from buddie.verify import assessment
    try:
        selection = profiles.resolve(args.profile, args.modules, args.checks)
    except profiles.UnknownProfile as error:  # a usage error, not a smaller check
        print(f"buddie verify: {error}", file=sys.stderr)
        return 2
    # a report that cannot be read is an input error (exit 2), never a FAIL (exit 1): a traceback exited 1 before
    if args.report != "-" and Path(args.report).is_dir():
        print(f"buddie verify: {args.report} is a directory: give a report file, or - for stdin", file=sys.stderr)
        return 2
    try:
        text = sys.stdin.read() if args.report == "-" else Path(args.report).read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        print(f"buddie verify: {args.report}: not UTF-8 (byte {error.start}); give the report as UTF-8 text",
              file=sys.stderr)
        return 2
    except OSError as error:
        if isinstance(error, FileNotFoundError):
            raise  # main() says so, as before
        print(f"buddie verify: {args.report} cannot be read ({error.strerror or error})", file=sys.stderr)
        return 2
    repos = [Path(r) for r in args.repo] if args.repo else find_repos(Path.cwd())
    got = assessment(text, args.modules, name=args.report, repos=repos, store=args.store, fetch=not args.no_fetch,
                     access=args.access, quotes=not args.anchors_only, rev=args.rev,
                     github=None if args.no_github else github_get, transcript=args.transcript, numbers=args.numbers,
                     profile=args.profile, checks=args.checks)
    receipt, covered = got.receipt, got.coverage  # receipt-v0: the lines and the exit code, whatever --receipt
    pred = receipt["predicate"]
    chosen = receipts.render(got, args.receipt)  # the same check, in the contract asked for
    if args.json:
        Path(args.json).write_text(json.dumps(chosen, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for item in pred["blocking"]:
        print(f"BLOCK {item}")
    for item in pred["gaps"]:
        print(f"gap   {item}")
    for item in pred.get("notes", []):
        print(f"note  {item}")
    if line := profiles.note(selection, covered):
        print(f"note  {line}")
    print(receipts.line(chosen) if args.receipt == "v1" else pred["line"])
    return 1 if pred["outcome"] == "FAIL" else 0  # v0 FAIL is v1 FAIL: the exit code is the same for both


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
    from buddie.logbook import journal_paths
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


def cmd_status(args) -> int:
    """What the hook does in this repo now: the config, the level of each class, the intro, transcript reading, and
    what the journal says about the last checks."""
    from collections import Counter

    from buddie import __version__, config, logbook
    path = _config_path(args)
    cfg = config.load(path)
    lv = config.levels(cfg, path is not None)
    print(f"buddie {__version__}")
    if path:
        print(f"config: {path}")
        if why := config.problem(path):
            print(f"config error: {config.CONFIG} cannot be read ({why}): none of its settings apply, buddie's full "
                  "defaults do, and the hook returns each answer until the file is fixed")
        tour = config.intro(path, cfg)
        if tour:
            print(f"intro mode: {tour['seen']} of {tour['finals']} final answers passed; until then nothing is returned, "
                  "only warned (`buddie enforce` ends it)")
    else:
        print(f"config: no {config.CONFIG} (fresh-install defaults): only a quote that is not on its page or an anchor "
              "that does not hold goes back; `buddie init` turns on the project's full checks")
    print("levels: " + ", ".join(f"{k}={v}" for k, v in lv.items()))
    from buddie import policy
    loaded = policy.load()
    if loaded.status is policy.Status.ACTIVE:
        print(f"policy: active ({loaded.path}): its floors and limits apply above these levels (buddie policy show)")
    elif loaded.status is policy.Status.INVALID:
        print(f"policy: INVALID ({loaded.path}: {loaded.error}): the strictest limits apply and the hook returns each "
              "answer until an administrator fixes the file (buddie policy check)")
    if path and not config.problem(path) and config.load(path).get("verify") is not None:
        from buddie import resolved
        ctx = resolved.resolve({"cwd": str(path.parent)}, [path.parent])  # with the protected policy's floors
        run = ctx.run_checks()
        print(f"profile: {ctx.profile.profile}; the hook runs: " + (", ".join(run) if run else
              "no verification check (every class it feeds is off): nothing an answer claims is verified"))
    print("transcript: " + ("read (run: anchors are checked)" if config.reads_transcript(cfg)
                            else "not read (run: anchors are unchecked)"))
    logs = [p for p in logbook.log_targets(None)[:1] if p.is_file()]
    if not logs:
        print("journal: none yet")
        return 0
    rows = []
    for raw in logs[0].read_text(encoding="utf-8", errors="replace").splitlines()[-args.last:]:
        try:
            rows.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    checks = [r for r in rows if "outcome" in r]
    returned = [r for r in checks if r.get("exit") == 2]
    reasons = Counter(k for r in returned for k in (r.get("reasons") or {}))
    print(f"journal: {logs[0]}")
    print(f"last {len(checks)} checks: {len(checks) - len(returned)} let through, {len(returned)} returned, "
          f"{sum(1 for r in checks if r.get('warned'))} with warnings; outcomes "
          + ", ".join(f"{k} {v}" for k, v in Counter(r["outcome"] for r in checks).most_common()))
    if reasons:
        print("returned for: " + ", ".join(f"{k} {v}" for k, v in reasons.most_common()))
    return 0


def cmd_serve(args) -> int:
    if args.http:
        from buddie.remote import serve as serve_http
        return serve_http(args.host, args.port)
    from buddie.mcp import serve
    return serve()


def cmd_hook(args) -> int:
    from buddie.hook import main
    return main()


def _module_ids(spec: str) -> list[str]:
    """--modules: known ids only, so a misspelt one is a usage error (exit 2), not a silently smaller check."""
    from buddie.modules import UnknownModule, parse
    try:
        return [m.id for m in parse(spec)]
    except UnknownModule as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def cmd_receipt_schema(args) -> int:
    """The JSON Schema of receipt-v1 (buddie/receipts.py; docs/receipt-v1.schema.json is the same)."""
    from buddie import receipts
    print(json.dumps(receipts.SCHEMA, ensure_ascii=False, indent=1))
    return 0


def cmd_snapshot(args) -> int:
    """An environment snapshot (buddie/environment.py). Advice, not enforcement: it gates nothing, and nothing reads it
    back as evidence. Exit 0 with a snapshot (unavailable facts included), 2 when the input cannot be used."""
    from buddie import environment
    supplied = {}
    for item in args.supply or []:
        key, sep, value = item.partition("=")
        if not sep:
            print(f"buddie snapshot: --supply {item!r}: give KEY=VALUE", file=sys.stderr)
            return 2
        supplied[key] = value
    text = None
    if args.report is not None:  # read as `buddie verify` reads it, so the digest is its receipt's subject
        if args.report != "-" and Path(args.report).is_dir():
            print(f"buddie snapshot: {args.report} is a directory: give a report file, or - for stdin", file=sys.stderr)
            return 2
        try:
            text = sys.stdin.read() if args.report == "-" else Path(args.report).read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            print(f"buddie snapshot: {args.report}: not UTF-8 (byte {error.start})", file=sys.stderr)
            return 2
        except OSError as error:
            print(f"buddie snapshot: {args.report} cannot be read ({error.strerror or type(error).__name__})",
                  file=sys.stderr)
            return 2
    try:
        snap = environment.collect(args.root, args.artifact or [], report=text, supplied=supplied)
    except ValueError as error:
        print(f"buddie snapshot: {error}", file=sys.stderr)
        return 2
    if args.json:
        Path(args.json).write_text(environment.dumps(snap) + "\n", encoding="utf-8")
        print(environment.line(snap))
    else:
        print(environment.dumps(snap))
    return 0


FRESHNESS_EXIT = {"CURRENT": 0, "STALE": 1, "UNKNOWN": 3, "NOT_APPLICABLE": 3}


def _freshness_exit(results) -> int:
    """STALE anywhere: 1; else anything not CURRENT: 3; else 0. Freshness alone: a CI failure on the right commit
    is CURRENT (its outcome is printed beside it), so the exit code says whether the evidence applies, not whether
    it passed."""
    codes = {FRESHNESS_EXIT[r.state] for r in results}
    return 1 if 1 in codes else 3 if 3 in codes else 0


def cmd_freshness(args) -> int:
    """Evidence freshness (buddie/freshness.py). Advice, not enforcement: no gate reads it, and no receipt changes."""
    from buddie import environment, evidence, freshness, policy
    from buddie.effects import github_get
    with policy.held() as loaded:
        lim = loaded.effective
        if args.what == "ci":
            if not freshness.REPO.match(args.repo or "") or not freshness.HEX.match(args.evidence or "") or (
                    (args.pr is None) == (args.commit is None)):
                print("buddie freshness ci: give --repo OWNER/REPO, --evidence SHA (7 to 64 hex) and one of --pr N "
                      "or --commit SHA", file=sys.stderr)
                return 2
            if args.commit is not None and not freshness.FULL.match(args.commit):
                print("buddie freshness ci: --commit is the full commit id (40 or 64 hex): a branch or a prefix is no "
                      "revision", file=sys.stderr)
                return 2
            off = None
            if lim is not None and lim.network == "forbidden":
                off = "network_forbidden"
            elif args.no_github or os.environ.get("BUDDIE_GITHUB", "1") == "0":
                off = "github_off"
            get = None if off else github_get
            with evidence.collector():  # the protected policy's network, as for the hook's fetches
                target = (freshness.resolve_pr_head(args.repo, args.pr, get, off=off) if args.pr is not None
                          else freshness.claimed("commit", args.repo, args.commit))
                found = freshness.ci_evidence(args.repo, args.evidence, get, check=args.check, off=off)
            results = [freshness.assess(target, found)]
        else:
            commit, recorded = args.commit, {}
            for item in args.artifact or []:
                path, sep, digest = item.rpartition("=")
                if not sep or not path or not freshness.re.fullmatch(r"[0-9a-f]{64}", digest):
                    print(f"buddie freshness repo: --artifact {item!r}: give PATH=SHA256", file=sys.stderr)
                    return 2
                recorded[path] = digest
            if args.snapshot:
                try:
                    doc = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                    print(f"buddie freshness repo: {args.snapshot} cannot be read as JSON ({type(error).__name__})",
                          file=sys.stderr)
                    return 2
                if problems := environment.problems(doc):
                    print(f"buddie freshness repo: {args.snapshot} is not a consistent snapshot: {problems[0]}",
                          file=sys.stderr)
                    return 2
                head = doc["repository"]["head"]
                commit = commit or (head["value"] if head["status"] == "observed" else None)
                for a in doc["artifacts"]:
                    if a["status"] == "observed":
                        recorded.setdefault(a["path"], a["sha256"])
            if commit is not None and not freshness.FULL.match(commit):
                print("buddie freshness repo: --commit is the full commit id (40 or 64 hex)", file=sys.stderr)
                return 2
            if commit is None and not recorded:
                print("buddie freshness repo: give --commit, --artifact or a --snapshot that records either",
                      file=sys.stderr)
                return 2
            root = Path(args.root or ".")
            if not root.is_dir():
                print("buddie freshness repo: the root is not a directory", file=sys.stderr)
                return 2
            results = []
            if commit is not None:
                results.append(freshness.assess(freshness.claimed("commit", "local", commit),
                                                freshness.repository_now(root)))
            for path, digest in sorted(recorded.items()):
                results.append(freshness.assess_artifact(digest, freshness.artifact_now(root, path)))
    doc = freshness.render(results)
    if args.json:
        Path(args.json).write_text(freshness.dumps(doc) + "\n", encoding="utf-8")
    for r in results:
        print(("" if r.target.kind != "artifact" else f"{r.evidence.ref or r.target.ref}: ") + freshness.line(r))
    return _freshness_exit(results)


def _receipt_version(name: str) -> str:
    from buddie import receipts
    try:
        return receipts.version_of(name)
    except receipts.UnknownReceiptVersion as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def cmd_profiles(args) -> int:
    """The verification profiles and the modules and checks each one resolves to (buddie/profiles.py)."""
    from buddie import profiles
    for name in profiles.BUILT_IN:
        selection = profiles.resolve(name)
        print(f"{name:<10} modules: {', '.join(m.id for m in selection.modules)}")
        print(f"{'':<10} checks: {', '.join(selection.check_ids)}")
    print(f"{'custom':<10} what you list: --modules {','.join(profiles.mods.IDS)} and/or --checks "
          f"{','.join(profiles.CHECK_IDS)}")
    return 0


def cmd_modules(args) -> int:
    """The verification modules buddie has (buddie/modules.py), with what each checks and reads."""
    from buddie.modules import REGISTRY
    for m in REGISTRY:
        print(f"{m.id:<10} {m.summary}")
        print(f"{'':<10} checks: {', '.join(c.value for c in m.checks)}; reads: {', '.join(m.inputs)}")
    return 0


def cmd_policy(args) -> int:
    """The protected policy: where it is, whether it is in force, and what it changes for the repo around cwd. buddie
    never writes it: `template` prints one for an administrator to install (docs/policy.md)."""
    from buddie import policy, resolved
    if args.what == "template":
        print(policy.TEMPLATE, end="")
        return 0
    loaded = policy.load()
    print(f"policy: {loaded.path}")
    print(f"status: {loaded.status.value}" + (f" ({loaded.error})" if loaded.error else ""))
    if args.what == "check":
        return 1 if loaded.status is policy.Status.INVALID else 0
    if loaded.status is policy.Status.ABSENT:
        print("no protected policy: buddie.toml and the hook's environment decide everything, as before")
        return 0
    ctx = resolved.resolve({"cwd": os.getcwd()}, [Path(r) for r in args.repo] if args.repo else None)
    print("levels: " + ", ".join(f"{k}={v.value}" + ("*" if v.source.value == "protected" else "")
                                 for k, v in ctx.levels.items()) + "   (* raised to the policy's floor)")
    print(f"intro allowed: {ctx.intro_allowed}; disclosure: {ctx.disclosure_allowed}; transcript: "
          f"{ctx.transcript.value} ({ctx.transcript.source.value}); journal words: {ctx.journal_text}; "
          f"network: {'allowed' if ctx.network_allowed else 'forbidden'}")
    lim = loaded.effective
    print(f"evidence: repos={lim.repos}, stores={lim.stores}, journal={lim.journal}, collector={lim.collector}, "
          f"github_api={lim.github_api or 'as the environment says'}")
    print("refused here: " + (", ".join(ctx.refused) or "nothing"))
    return 0


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
    s.add_argument("--profile", help="developer, research, complete or custom (see `buddie profiles`)")
    s.add_argument("--receipt", type=_receipt_version, default="v0",
                   help="receipt contract for --json and the summary line: v0 (default) or v1 (docs/receipts.md)")
    s.add_argument("--checks", type=lambda v: [c for c in v.split(",") if c.strip()],
                   help="custom profile: these checks, comma separated (with or without --modules)")
    s.add_argument("--modules", type=_module_ids,
                   help="only these modules, comma separated (default: all; see `buddie modules`)")
    s.add_argument("--json", help="write the receipt here")
    s.add_argument("--rev", help="judge work claims against the queue as of this commit")
    s.add_argument("--transcript", help="Claude Code session jsonl for run: anchors")
    s.add_argument("--no-github", action="store_true", help="leave pr:/ci: anchors UNCHECKABLE (offline)")
    s.add_argument("--numbers", choices=("gap", "fail", "off"), default="gap",
                   help="a number of a cited sentence not in its source: a gap (default), a failure, or not checked")
    s.set_defaults(func=cmd_verify)
    sn = sub.add_parser("snapshot", help="what buddie observes of the environment (docs/environment.md)")
    sn.add_argument("--root", help="the directory artifacts are named under (default: the working directory)")
    sn.add_argument("--artifact", action="append", help="a file under the root to digest (repeatable)")
    sn.add_argument("--report", help="the report a receipt was made for (its sha256 pairs the two), or - for stdin")
    sn.add_argument("--supply", action="append", help="KEY=VALUE the caller states (kept apart, never checked)")
    sn.add_argument("--json", help="write the snapshot here and print one line (default: the snapshot on stdout)")
    sn.set_defaults(func=cmd_snapshot)
    fr = sub.add_parser("freshness", help="whether evidence is bound to the revision a claim is about")
    fr.add_argument("what", choices=("ci", "repo"))
    fr.add_argument("--repo", help="ci: OWNER/REPO on GitHub")
    fr.add_argument("--pr", type=int, help="ci: the PR whose current head is the target")
    fr.add_argument("--commit", help="the target commit (full id): a claim about that commit, historical included")
    fr.add_argument("--evidence", help="ci: the commit the CI result is offered from (SHA or prefix)")
    fr.add_argument("--check", help="ci: only the check run or status of this name")
    fr.add_argument("--no-github", action="store_true", help="ci: do not ask GitHub (everything UNKNOWN)")
    fr.add_argument("--root", help="repo: the checkout to observe (default: the working directory)")
    fr.add_argument("--artifact", action="append", help="repo: PATH=SHA256 recorded for a file under the root")
    fr.add_argument("--snapshot", help="repo: an environment snapshot whose recorded HEAD and artifacts to compare")
    fr.add_argument("--json", help="write the freshness document here")
    fr.set_defaults(func=cmd_freshness)
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
    st = sub.add_parser("status", help="what the hook does in this repo now, and what it did lately")
    st.add_argument("--repo", action="append", help="repo with buddie.toml (default: around cwd)")
    st.add_argument("--last", type=int, default=50, help="journal lines to read (default 50)")
    st.set_defaults(func=cmd_status)
    t = sub.add_parser("intro", help="where the intro mode stands; --false reports a false return")
    t.add_argument("--false", action="store_true", help="the last return was false: restart the count")
    t.add_argument("--repo", action="append", help="repo with buddie.toml (default: around cwd)")
    t.set_defaults(func=cmd_intro)
    e = sub.add_parser("enforce", help="end the intro mode")
    e.add_argument("--repo", action="append", help="repo with buddie.toml (default: around cwd)")
    e.set_defaults(func=lambda args: cmd_intro(args, enforce=True))
    s = sub.add_parser("serve", help="MCP server on stdio, or over HTTP with --http")
    s.add_argument("--http", action="store_true", help="Streamable HTTP at /mcp instead of stdio (remote.py)")
    s.add_argument("--host", default=os.environ.get("BUDDIE_HTTP_HOST", "127.0.0.1"),
                   help="address to listen on (default 127.0.0.1; 0.0.0.0 in a container)")
    s.add_argument("--port", type=int, default=int(os.environ.get("PORT") or 8000), help="default $PORT or 8000")
    s.set_defaults(func=cmd_serve)
    po = sub.add_parser("policy", help="the protected policy: show it, check it, or print a template to install")
    po.add_argument("what", choices=("show", "check", "template"))
    po.add_argument("--repo", action="append", help="repo whose buddie.toml to judge (default: around cwd)")
    po.set_defaults(func=cmd_policy)
    sub.add_parser("modules", help="the verification modules and what each checks").set_defaults(func=cmd_modules)
    sub.add_parser("profiles", help="the verification profiles and what each checks").set_defaults(func=cmd_profiles)
    sub.add_parser("receipt-schema", help="the JSON Schema of receipt-v1").set_defaults(func=cmd_receipt_schema)
    sub.add_parser("hook", help="Claude Code hook on stdin").set_defaults(func=cmd_hook)
    args = p.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as e:
        if args.cmd not in ("verify", "mandate"):
            raise
        print(f"buddie {args.cmd}: {e}", file=sys.stderr)  # a missing report or --rev: usage, not FAIL (NEXT №105)
        return 2
