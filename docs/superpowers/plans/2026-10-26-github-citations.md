# GitHub citations implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Automatically verify literal GitHub citations in ordinary Markdown reports.
**Architecture:** A strict GitHub source resolver and code extractor feed the existing quote findings and receipts.
**Tech Stack:** Python >=3.11, standard library, pytest.
**Spec:** `docs/superpowers/specs/2026-10-26-github-citations-design.md`.

## Global constraints

No model, shell execution, new dependency, or new MCP tool. Never normalize code punctuation, case or indentation.
Remote public-only permissions, offline behavior, provenance rules and existing non-GitHub receipts remain intact.

## Review focus

- Wrong diff side or text crossing a hunk must not pass.
- Multiple possible citations must not turn into first-success matching.
- Missing/truncated patch or malformed API body must flag, not fail or crash.
- Replayed/caller-supplied evidence must not gain collector provenance.
- Remote private repository content must never be fetched, including new path families.

### Task 1: Source adapter

Files: create `buddie/github_sources.py`, `tests/test_github_sources.py`.
Interface: `Resolver(store, github, fetch).check(claim) -> dict` and `is_github(url) -> bool`.
- [x] Write failing tests for pinned files/ranges, PR bodies, diff sides/kinds/hunks, incomplete sources and replay.
- [x] Run `python -m pytest tests/test_github_sources.py -q` and confirm the missing adapter fails.
- [x] Implement the adapter, bounded parsing and content-addressed replay, then make those tests pass.

### Task 2: Report integration

Files: create `buddie/github_report.py`, `tests/test_github_report.py`; modify `buddie/verify.py`,
`buddie/findings.py`, `buddie/remote.py` and MCP/CLI help text.
Interfaces: `code_claims(text) -> list[dict]`; existing `check_quotes` receives the GitHub callback.
- [x] Write failing tests for code extraction, ambiguity, strict prose routing, complete receipt locations,
      callback provenance, disabled fetches and remote public/private paths.
- [x] Run the new tests, confirm failures, implement and rerun.
- [x] Verify existing profiles, hooks and receipt renderers still use the same quote check.

### Task 3: Documentation and delivery

Files: create `docs/github-citations.md`; update docs index, verification guide and Unreleased changelog.
- [x] Document supported report examples, URL shapes, guarantees, replay, privacy and limitations.
- [x] Run full `python -m pytest -q`, inspect diff and run `git diff --check`.
- [x] Commit and publish a separate PR with exact validation results and limitations; do not merge.

## Execution record

Task 1: complete. Task 2: complete. Task 3: implementation and verification complete; delivery through a separate PR.
See `docs/design-github-citations-validation.md` for exact results, baseline failures, live checks and review fixes.
