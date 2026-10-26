# CI execution policy (proposal)

This change replaces full validation on **every PR synchronization** with a lightweight security-and-verification suite. The full test matrix, clean-install checks, packaging/release-candidate checks, catalog validation and Docker checks run for a GitHub **merge queue** entry (`merge_group`) and for pushes to `main`.

## Event matrix

| Event | Fast job | Full jobs | Stable gate |
| --- | --- | --- | --- |
| `pull_request` | Required | Skipped | Requires fast pass and full jobs skipped |
| `merge_group` (`checks_requested`) | Required | Required | Requires all jobs success |
| `push` to `main` | Required | Full tests/platforms/catalogs/Docker, **no duplicate candidate build** | Requires all executed jobs success |

The `gate` job always runs and fails if any required result is missing, failing, or canceled. Its stable check name is intended for branch rules, but **the PR gate alone does not enforce the pre-merge full suite**: it deliberately passes after the fast suite on ordinary PR events.

## Mandatory administrative prerequisites before merge

1. Enable **GitHub Merge Queue** for `main` and require PRs to enter the queue. Configure the branch ruleset to require the stable `gate` check on queued merge groups, with no bypass. GitHub configuration is **not** changed by this PR.
2. Confirm the actual check name (typically `ci / gate`) in GitHub Actions and update required-status settings accordingly. Do not remove existing required jobs until their replacement is confirmed working.
3. Verify that one queued synthetic PR runs the full matrix and release-candidate validation against the merge-group SHA. Confirm a failing full job blocks the queue.
4. Retain an administrator-approved rollback route: revert this commit if merge queue is unavailable or any event is unexpectedly skipped.

**Important:** If merge queue is unavailable, do **not** merge this proposal as written; use a protected, SHA-bound full pre-merge approval workflow instead. A manually dispatched run by itself is *not* a merge guard.

## Limitations

- Fast coverage is a targeted subset, not an exhaustive regression suite. Review the chosen paths before adoption and expand on releases/security-sensitive PRs.
- The full suite continues to run after merge as a defense-in-depth check; it does not replace the merge queue's pre-merge verification.
- Every candidate publish workflow remains separate and requires its own authorization; this change only modifies ordinary CI execution.
- This branch is deliberately based on `main` `0a638d354c03cc44ea806a72547d084c122cd034` to avoid modifying existing release-hardening worktrees. Re-review interactions with updated workflow files before merging.

## Release candidate size and reuse policy

**The fast release path does not mean publishing unchecked packages.** Ordinary PRs execute the focused release-size unit tests; the merge queue builds the full candidate once for the merge-group SHA. A push to main does not repeat this expensive candidate build. Publishing a tag runs its own full candidate build for that **exact tagged SHA**, and publishing jobs later download the same build artifact (rather than rebuilding per channel).

The dedicated `scripts/release_size_gate.py` runs on every finished, integrity-verified release candidate. Initial compressed size limits (not extracted-size limits) are:

| Artifact | Budget | v2.0.1 reference |
| --- | ---: | ---: |
| wheel | 1 MiB | 266,231 B |
| sdist | 1 MiB | 268,422 B |
| Claude Desktop MCPB | 2 MiB | 333,422 B |
| Compact Claude plugin ZIP | 2 MiB | 904,599 B from prior reproducible packaging review |
| Total four archives | 6 MiB | - |

The gate fails the candidate on missing/duplicated artifact kinds, invalid sizes or exceeded limits. These ceilings are a regression protection, **not a claim that all packages are runtime-only**. The existing package manifest/SHA-256 verification, archive content checks, clean installs, reproducibility checks, and release authorization remain required; the active Work archive-hardening changes will add deeper content-policy validation after integration.

Only advance size ceilings through reviewed changes supported by measured package growth, not by bypassing the gate. Final publishable candidates must be built from the exact tag commit; a merge-group candidate cannot be reused for a different main/tag commit SHA.

This PR does not change `release.yml` publication privileges or weaken the user confirmation. Future release metadata/packaging work should merge with this workflow cautiously.
