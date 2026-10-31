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
