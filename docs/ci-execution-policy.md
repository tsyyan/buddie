# CI execution policy (proposal)

This change replaces full validation on **every PR synchronization** with a lightweight security-and-verification suite. The full test matrix, clean-install checks, packaging/release-candidate checks, catalog validation and Docker checks run for a GitHub **merge queue** entry (`merge_group`) and for pushes to `main`.

## Event matrix

| Event | Fast job | Full jobs | Stable gate |
| --- | --- | --- | --- |
| `pull_request` | Required | Skipped | Requires fast pass and full jobs skipped |
| `merge_group` (`checks_requested`) | Required | Required | Requires all jobs success |
| `push` to `main` | Required | Required | Requires all jobs success |

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
