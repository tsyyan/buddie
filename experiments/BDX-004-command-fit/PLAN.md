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
