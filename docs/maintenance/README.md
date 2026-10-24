# Maintenance review package

The operational entry point is the [post-merge audit](2026-10-24-post-merge.md).
PR #38 has merged; it is no longer a pending prerequisite.

- [Current branch inventory and evidence](post-merge-branches.json)
- [Exact deletion manifest: not approved](deletion-manifest.json)
- [Current settings snapshot](post-merge-settings.json)
- [Proposed settings](settings-proposals.json): not applied by this package; the owner applied protections later on 2026-10-24 ([read back](2026-10-24-post-merge.md#addendum-settings-read-back))
- [Publication approval proposal and its limits](publication-authorization.md)
- [Workflow patch, applied by the `release-unified-approval-gate` follow-up; settings applied separately by the owner](proposals/authorize-environment.patch)

The [original audit](2026-10-24-pre-release-audit.md), [original branches](branch-audit-2026-10-24.json)
and [original settings](settings-snapshot-2026-10-24.json) remain historical snapshots against main `b6464a7`.
Their pending-#38 instructions are superseded, not instructions for current operations.

No file in this package authorizes branch deletion, settings changes, a merge, a release tag or publication.
