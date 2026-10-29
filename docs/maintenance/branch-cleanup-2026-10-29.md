# Branch cleanup, 2026-10-29

The owner approved deleting every branch already in `main` plus three unmerged ones. The session that prepared this
could not delete refs (its GitHub access refuses ref deletion), so the list and the command are here for the owner.

[`branch-cleanup-2026-10-29.tsv`](branch-cleanup-2026-10-29.tsv): branch, full head SHA, reason. 75 branches:

| Reason | Count | Why it is safe |
|---|---:|---|
| `ancestor-of-main` | 51 | the head commit is in `main`'s history |
| `squash-merged #N` | 21 | PR #N was merged with exactly this head; `main` has its squash commit |
| `owner-approved 2026-10-29` | 3 | `directory-candidate-2.0.4` (a copy of `plugin-stable` with another date), `bdx-001-lite-collect` (temporary, raw fixtures from a personal machine), `investigate/linux-worker-lifecycle` (diagnostics for #73) |

Kept: `main`, `plugin-stable` (the Claude Code channel), the heads of open PRs #57 and #71
(`docs/projects-module-design-20261026`, `docs/bdx001-methodology-retained`), and `hardening/release-protection`
(two unmerged commits without a PR; the owner chose to keep it).

## Delete

From a clone with push rights, after checking that nothing moved since the list was made (a branch whose head is not
the recorded SHA is skipped, not deleted):

```sh
git fetch --prune origin
while IFS=$'\t' read -r branch sha reason; do
  if [ "$(git rev-parse "refs/remotes/origin/$branch" 2>/dev/null)" = "$sha" ]; then
    git push origin --delete "$branch"
  else
    echo "skip $branch: not at $sha"
  fi
done < docs/maintenance/branch-cleanup-2026-10-29.tsv
```

A deleted branch can be restored from its SHA while GitHub keeps the commit (`git push origin <sha>:refs/heads/<branch>`).

Deleting a branch does not remove its commits from GitHub: PR refs, forks and clones keep them. That matters only for
`bdx-001-lite-collect`, whose raw fixtures came from a personal machine. Removing them for good is a separate
procedure (the privacy note in [the 2026-10-26 project-control report](../project-control/2026-10-26.md)).
