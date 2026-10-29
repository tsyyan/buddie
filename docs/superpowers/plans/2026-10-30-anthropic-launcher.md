# Anthropic launcher and 2.0.6 implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prepare and publish 2.0.6 with a launcher the Anthropic directory can inspect, then submit the released compact plugin for review.

**Architecture:** Replace computed interpreter execution with explicit python3, python and py -3 branches. Keep Python >=3.11, isolated mode, unchanged stdin/arguments and the existing no-Python Stop handling. Validate the compact candidate in the actual portal before publishing.

**Tech stack:** POSIX sh, Python, pytest, GitHub Actions.

**Spec:** User approval on 2026-10-30: prepare the fix and release 2.0.6; the published 2.0.5 is immutable. Portal rejected hooks/run.sh as UNPINNED_NPX because it could not resolve a launched program; no npx or uvx is used by the launcher.

## Global constraints

- No new runtime dependencies or permissions.
- Preserve Windows Git Bash, Linux and macOS behavior and Python >=3.11.
- Never replace published 2.0.5 assets or move its tag.
- Publish the checked candidate through the repository release workflow.

## Review focus

- Missing auxiliary PATH tools must not break an available Python launcher.
- Paths with spaces and Windows backslashes must retain their meaning.
- Failed or old interpreters must fall through in the existing order.
- Version probes must not consume the hook event; arguments must remain separate.
- No-Python Stop must hold once and then disclose without looping.

## Task 1: Launcher

Files: hooks/run.sh; tests/test_trust_boundary.py.

- [ ] Run the unchanged suite as baseline.
- [ ] Add and run a failing real-shell test with Python available but no dirname/tr; assert the hook runs and receives its event.
- [ ] Use explicit interpreter branches and readable path normalization, preserving isolated mode and fallback semantics.
- [ ] Exercise fallback interpreters, spaces/backslashes and stdin/arguments; run the complete suite and strict plugin validation.
- [ ] Commit, build the compact source, push a separate preview branch and validate it in the Anthropic portal. Portal validation is the authority for whether the blocker is removed.

## Task 2: Release and submission

Files: version manifests, releases/2.0.6.json, generated public release copy, docs/directory-submission.md.

- [ ] Prepare consistent 2.0.6 metadata using existing release tooling; describe only observed behavior.
- [ ] Obtain a fresh whole-branch review and green CI; integrate through a pull request.
- [ ] Tag the merged commit, build its candidate, dispatch publication of that exact candidate and verify all public outputs.
- [ ] Return the portal to plugin-stable, verify 2.0.6 and complete the submission; request user action only for a required human checkpoint.

## Execution record

- Reused the existing clean linked worktree on new branch fix/anthropic-launcher-206, based on origin/main aaef44b. Native worktree creation cannot accept this nested repository as a workspace root.
- Proceeding autonomously under the user's explicit authorization for the fix and release.
- Ruling: the actual failing test is the portal validation (reproduced on plugin-stable 469fa13, 1 blocking UNPINNED_NPX, Next disabled). A source-text assertion would merely mirror the implementation; additional real-shell tests characterize compatibility instead. Preserve the original auxiliary-tool behavior rather than expand this patch into a PATH redesign.
- Baseline: with Git Bash on PATH, tests/test_trust_boundary.py and tests/test_config.py passed (43 tests). The new six fallback/path/argument/isolated-mode cases pass against the old launcher; they are compatibility coverage, not evidence that the Directory issue is fixed.
- Portal experiment: explicit Python calls and split path normalization alone still blocked (preview c9a9504); replacing `[` by `test` still blocked (e864053); replacing case patterns by equivalent parameter matching passed (7214182, Next enabled, five warnings and six manual-review holds remain). The expanded hold specifically identified a program named by a pattern. No review holds were hidden.
- Ruling: user requested no subagents on 2026-10-30; stopped the review agent and continue all work and review myself. This overrides skill delegation instructions.
- CI found test-fixture PATH errors on macOS (/usr/bin omitted) and Windows (usr/usr/bin for the alternate sh location). Fixing the fixture; production behavior was unchanged by these failures.
