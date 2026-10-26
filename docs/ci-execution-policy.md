# CI execution policy

Ordinary PR updates run a fast, focused suite. Full validation (test matrix, three-OS clean installs, catalogs,
Docker, and the release candidate with its size gate) runs when a maintainer asks for it with the label
**`full-ci-required`**, and again after merge on `main`. GitHub Merge Queue is **not** used: this repository
belongs to a personal account, where merge queue is not assumed to be available.

## The required check: `gate`

`ci.yml` has one job meant to be required by branch protection, `gate` (shown as **`gate`**, or `ci / gate`
when GitHub groups it by workflow). It runs on every event, needs every other job, and is fail-closed:

| Event | Fast | Full jobs | Release candidate | `gate` passes only if |
| --- | --- | --- | --- | --- |
| PR without the label | runs | skipped | skipped | never: fails with "full validation not requested" |
| PR with `full-ci-required` | runs | run on the PR merge ref | built and size-gated | fast and every full job and the candidate succeeded |
| push to `main` | runs | run | skipped (no duplicate build) | fast and every full job succeeded |
| any other event | - | - | - | never |

- **New commits invalidate it.** A status belongs to a commit; a push creates a new head SHA whose `gate` starts
  pending and has to pass again (the label stays, so full validation reruns on the new head).
- **Removing the label invalidates it.** `unlabeled` starts a new run for the same head; its `gate` fails, and as
  the newest check run of that name it replaces the earlier success. The per-PR concurrency group with
  `cancel-in-progress` cancels any older full run, so it cannot finish later and overwrite the newer result.
- **Base changes.** `pull_request` runs test the proposed merge result (`refs/pull/N/merge`) as of the run. Require
  branches to be up to date before merging, so a moved `main` forces an update, a new head and a new `gate`.
- Fast checks alone never make `gate` pass on a pull request.

## Limits of this design (owner must accept or mitigate)

1. **A PR controls its own workflow file.** `pull_request` runs the PR's version of `ci.yml`, so a PR could edit
   `gate` to pass. This holds for any Actions-based gate (merge queue included). Mitigations: require an approving
   review (and CODEOWNERS for `.github/`), and for outside contributors require approval before workflows run.
   Review every change to `.github/workflows/`.
2. **Who may label.** Only users with triage/write access can add labels; fork authors cannot. Adding the label is a
   request to run, not an approval: `gate` still needs the full jobs to succeed.
3. **Check name collisions.** Another job named `gate` in another workflow would also report a `gate` check. Pin the
   required check to the GitHub Actions app as its source, and do not add other jobs named `gate`.
4. **Admin bypass.** Unless "Do not allow bypassing the above settings" is on, an admin can merge on a red `gate`.

## Release candidate size and reuse policy

Tag runs (`release.yml`) build the publishable candidate from the exact tagged commit; every publication channel
downloads that one verified artifact, nothing is rebuilt per channel. The candidate built for a labeled PR is a
check only and is never published.

`scripts/release_size_gate.py` runs inside `release-candidate.yml` after `release_manifest.py verify` and
`sha256sum -c`, and reads each archive's size from the file on disk (refusing missing, symlinked or escaping
paths and any mismatch with the manifest), so the budgets bind to the validated candidate, not to manifest claims.

| Artifact | Budget | 2.0.2 development build |
| --- | ---: | ---: |
| wheel | 1 MiB | 306,145 B |
| sdist | 1 MiB | 278,891 B |
| Claude Desktop MCPB | 2 MiB | 310,608 B |
| Compact Claude Code ZIP | 2 MiB | 896,059 B |
| Total of the four | 6 MiB | 1,791,703 B |

Archive content policies, runtime-only allowlists, legal/privacy files, path/symlink checks and exact Git source
binding stay in their own checks; the size gate does not replace them. Change ceilings only through reviewed
changes backed by measured growth.

**Not yet covered:** the planned Codex ZIP is not in the budget. When the Codex profile lands, add its kind with
its own ceiling and include it in the total, in the same change.
