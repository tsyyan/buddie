# BDX-004 implementation plan and ledger

Goal: implement CODEX_TASK.md without model calls or dependencies outside the stdlib.
The supplied brief is the design and execution authorization. All new material stays here,
except `.github/workflows/bdx004.yml`.

Architecture: static diagnostic documents and per-profile task rules feed independent
Markdown extraction, a deterministic snapshot stand-in, and a conservative judge.
Commands are parsed for syntax only, never executed. No provider or network code.

## Commit sequence

1. Profiles and schema/provenance tests. Build eight baseline-complete documents and
   index metadata; validate every document with `buddie.diagnostics.problems`.
2. Tasks and coverage tests. Add 24 tasks, explicit per-profile requirements and a
   deterministic eligible-unit list with seed. Test IDs, references and coverage.
3. Extraction and tests. Preserve command order/shell, strip prompts/output/comments,
   join continuations and cover inline code and Markdown edge cases.
4. Tool and tests. Copy the MCP schema, validate arguments, restrict categories/tools,
   reproduce denial/catalog semantics without probing the host.
5. Judge and tests. Check shell/OS/program/version/privilege rules, parser availability,
   and sequential installs; test conservative UNKNOWN and CLI behavior.
6. Recorded answers. At least 12 distinct pairs with good/bad/question-only answers
   plus tricky cases; assert literal expected outcomes and reasons.
7. CI and README. Pinned actions, Ubuntu/Windows Python 3.12 tests, counts and limits.

Each implementation step starts with failing tests, then implementation, full experiment
tests and a separate all-profile validation before its commit. Final review checks
scope, no execution of answer text, missing observations, unsupported shell syntax,
installer state, and platform-independent outcomes.

## Rulings and progress

- The native worktree tool rejected the nested repository path. Used a sibling Git
  worktree on the explicitly requested branch; no existing checkout was edited.
- Diagnostics does not observe sudo, libc, or ash/sh versions, and does not say which
  Windows shell the user is typing in. Preserve its schema and record those scenario
  assumptions in index/task metadata, never as invented diagnostic observations.
- Python 3.10 may be a target interpreter while buddie itself runs on Python 3.11+.
  The no-venv profile therefore has a separate 3.12 buddie_runtime.
- Profiles complete: 1 test passed; 8 profile documents independently validated.
- Tasks complete: 2 tests passed; 8 profiles validated; 24 tasks and 192 pairs.
- Extraction complete: 7 tests passed; 8 profiles validated.
- Tool complete: 13 tests passed; 8 profiles validated; catalog and schema compared to real code.
- Judge complete: 26 tests ran, 1 skipped (no local POSIX parser); 8 profiles validated.
- Recorded answers complete: 27 tests ran, 1 skipped; 55 answers across 16 complete pairs.
- Ruling: OK retains the protocol's meaning of no proven WONT_RUN. UNKNOWN commands are
  separately counted and `all_commands_decided` is false; consumers must retain these
  fields to avoid counting unproven commands as fitting.
- Final independent review found three important issues, reproduced by failing regression tests:
  Python alias deduplication was mistaken for absence; extraction dropped quoted/wrapped
  executables; Node 20 rules allowed later major versions. Fixed the facts/extraction/rule
  boundaries and retained environment-changing wrappers as UNKNOWN. The recorded Ubuntu
  broken example now uses observed-missing conda rather than an unobserved Python alias.
- Review fixes verified: 31 tests passed with Git Bash and pwsh available; all 8 profiles
  validated again. No deferred review findings. Broader repository tests run separately.
- Final extraction check reproduced common curl/pip/ffmpeg/Docker version output as
  spurious extra commands. Added a failing regression and filtered these output forms;
  32 experiment tests now pass, with all 8 profiles independently validated.

## PR review corrections (2026-11-01)

User-specified follow-up: (1) POSIX shell families and OS/program reason priority;
(2) explicit UNDECIDED answers; (3) cited base-command data; (4) expanded recorded
answers and before/after UNKNOWN shares. Each is a small test-first commit in this folder.
The earlier OK ruling above is superseded by the requested UNDECIDED outcome.

Baseline f59c325: 55 recorded answers, 39 commands, 3 UNKNOWN (7.6923%) with bash,
dash and pwsh available. Saved actual per-command results in tests/unknown_before.json.
Shell-family regressions were observed failing before the fix; the complete 37-test
experiment suite now passes with those parsers. All eight profiles still validate.

UNDECIDED regression observed failing, then fixed. Updated the corpus's literal expected
outcomes and both protocol/README; BROKEN still precedes UNKNOWN and empty text is not OK.

Base-userland regressions observed failing without task-specific whitelist/assumptions, then
fixed with cited availability sets and bounded command-form data. The complete 46-test suite
passes; explicitly missing observations still override base assumptions and unsupported
options/foreign userlands are not inferred as FITS. All eight profiles validate.

Added five hand-labelled recorded review cases (60 answers total) and recorded_stats.py.
Counter/denominator regressions were observed failing before implementation. Reference
UNKNOWN shares with bash/dash/pwsh: before 3/39; after original IDs 1/39; all current
answers 1/44. The immutable before verdict snapshot and after report are checked in.
The comparison reports parser availability and never drops unknown or broken answers.

Final independent review reproduced two false-objection cases: sh regex checks inspected
quoted literals, and shlex's foreign quoting rules were treated as authoritative. Added
failing regressions and fixed both. Added a module-availability-before-tag regression too.
Final suite: 53 tests pass with bash/dash/pwsh; eight profiles validate. Recorded UNKNOWN
counts remain 3/39 before, 1/39 matched after, 1/44 expanded after. No deferred findings.

## Lists and control structures follow-up

User authorization: add quote-aware POSIX lists/PowerShell statements, venv setup state,
POSIX control structures as one extracted command, and recorded cases/UNKNOWN shares.
Plan: commit lists/state with regressions; commit control extraction/evaluation; commit
recorded cases and measurements. All changes stay in this experiment directory.

Captured the current 60-answer/44-command baseline at 5e4c330: 1 UNKNOWN with bash,
dash and pwsh available (tests/lists_before.json). List/state tests were observed failing
before implementation. Full suite now passes 61 tests with those parsers; profiles validate.

Control regressions were observed failing before implementation. Added bounded recursive
if/loop/case parsing, intact extraction, whole-structure syntax and branch-local evaluation.
The parser consumes data only; dynamic/unsupported forms are UNKNOWN. Found and reproduced
Windows CRLF stdin corrupting dash closing keywords; switched parser stdin to LF bytes.
The complete suite now passes 67 tests with bash/dash/pwsh; eight profiles still validate.

Independent review found and regressions reproduced multiline quote/connector splitting,
dynamic case-pattern false FITS, and stale venv proofs after mutations. Fixed logical-line
extraction and invalidated proofs through modeled mutations/unknown effects/conditional
paths; dynamic patterns stay UNKNOWN. Also kept incomplete quoted structures intact.
All 74 tests pass with bash/dash/pwsh; all profiles validate. No review findings deferred.

Added sixteen literal recorded list/control/state cases, including parent and recursive
leaf expectations (76 total answers). A failing metric regression exposed UNKNOWN leaves
hidden by BROKEN parent lists; added separate parent/leaf shares and recursive answer
decidability. Reference shares: original IDs unchanged 1/44; expanded parents 6/60 and
leaves 8/81. Snapshots and README/PROTOCOL record both denominators and parser availability.
Full suite passes 76 tests with bash/dash/pwsh; every profile validates before this commit.

Push encountered concurrent remote 2bd7873 (PROTOCOL v1 only). Rebased the four unpublished
commits without force-pushing; preserved the remote protocol at each conflict and reran
61/67/74/76 tests plus profile checks before each rebase continuation. Added list/control
and metric details back into v1 without changing arms/endpoints/models/audit. Its new
installed-tag override is beyond this request and conflicts with the earlier negative
case; asked the owner asynchronously and, absent new direction, retained current selection
and explicitly recorded this pre-registration follow-up in README/PROTOCOL/PR.

## Pilot-1 sections correction

Fast-forwarded to remote b036dd5 and read the failed pilot's recorded rule change. This
pass makes no model calls and does not change run settings/workflows. Plan: (1) stricter
inline extraction, (2) data-backed section scope/targeting/counts, (3) twelve realistic
multi-system answers, bounded verification forms, measurements and docs. Review after code.
Captured pre-change results for 76 existing plus 31 profile checks on 12 new answers:
107 profile-answer cases, 237 parent commands, 25 UNKNOWN (tests/sections_before.json).
Inline regressions failed first; the complete suite now passes 85 tests with all parsers.
Section regressions failed first, then passed: audience aliases live in JSON, labels/tags
scope commands and state, no matching section gives BROKEN/wrong_os, and targeting/counts
are emitted. Updated old cross-family fixtures to the new no-applicable-section outcome;
primitive reason-order tests still exercise validation directly after selection. Observed
alternate shells use bounded base rules without borrowing default-shell task assumptions.
