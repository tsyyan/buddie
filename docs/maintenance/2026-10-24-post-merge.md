# Post-merge maintenance reconciliation

Verified at `2026-10-23T21:42:02.397270+00:00`. This is the current operational update; the original dated audit is historical.

## Verified repository state

- Current main: `0f29c19430b764884eb057a16a3c84676b066698`. PR #38 is merged, closed, with this exact squash merge commit; its final branch head is `431f924c5ac00d46cff2f2e71d68b977be5024f5`.
- PR #39 remains Draft. Remote head at collection: `55b6454bef6fc7fdba26d738fbb349ba32fd2819`; API base SHA at collection: `b6464a7839274297c5c110ddd1a50557f4281c42`. Local reconciliation merge: `1ad2568e9b21316026d62d2cb75637399d6d1d9c` (parents are the reviewed #39 head and current main). Final published head and full CI receipt are recorded in the PR description after push, since a commit cannot contain its own SHA.
- The reconciliation was an ordinary merge, with no conflicts and no history rewrite. README, workflows, release scripts, runtime code and package metadata are byte-identical to merged main. None of the 27 final #38 paths is overwritten by the maintenance changes.
- 37 remote branches at collection; only open PR is #39, head `pre-release-maintenance-2026-10-24`, base `main`. Both head and base dependencies of every open PR were checked.
- All nine check runs on merged main were successful. Exact required contexts, GitHub Actions app ID 15368:

  - `test (3.11)`
  - `release-candidate / build`
  - `test (3.13)`
  - `docker`
  - `os (macos-latest)`
  - `os (ubuntu-latest)`
  - `test (3.12)`
  - `os (windows-latest)`
  - `catalogs`

## Branch deletion review

34 DELETE candidates remain unchanged from the original audit; main and #39 are KEEP. Former #38 branch is INVESTIGATE because it moved from the original snapshot, even though its current tip exactly matches the squash-merged tree. Its inclusion in any deletion approval requires a separate owner decision. No branch was deleted.

The [full inventory](post-merge-branches.json) contains every full tip SHA, all associated PRs, unique commit subjects, open head/base dependencies, ancestry and exact-tree evidence. The [final deletion manifest](deletion-manifest.json) is explicitly `approved: false`. A merged PR label alone was never treated as sufficient evidence. Unchanged multi-commit squash candidates have exact tip/merge tree equality and a merge commit reachable from current main.

| DELETE candidate | Exact current tip | Proof |
|---|---|---|
| `adversarial-verification-suite` | `9059fc0796b7ebbe1e0a5b4b1a59ef84c18b7632` | unchanged PR head; exact squash tree; merged commit ancestor of main |
| `canon-here` | `089dbfc0d73fa96ec6c0f56a89f00c0da358dcde` | tip ancestor of main |
| `catalog-p1` | `08a835d8e5d44d217aa93fec070654c8353b58cd` | tip ancestor of main |
| `charset` | `7abd07be8e3850e5703cb89507fee57899016a5c` | tip ancestor of main |
| `claude/project-thread-7d8b7g` | `d93d8bcdb4337568a00009f2b3944cba370e867f` | tip ancestor of main |
| `codex` | `f6e875f152dde8f28ea07dfcb0698154a7061abd` | tip ancestor of main |
| `config-decoupling` | `4296db7d0997e8f3637d02ff21f5389faf021bf1` | tip ancestor of main |
| `disclose-after-return` | `fe56e8363e70766c7642bd715a16ea8a80becf4c` | tip ancestor of main |
| `environment-collector-snapshots` | `d77cd83203b0db92f5c5c7d3110c5211ff0e4abc` | unchanged PR head; exact squash tree; merged commit ancestor of main |
| `evidence-freshness-staleness` | `f2646571644335e50e8c30532b1ff4de34deb639` | unchanged PR head; exact squash tree; merged commit ancestor of main |
| `evidence-registry` | `2f1b8f2963e4d119767347d03663eb0702869fc7` | unchanged PR head; exact squash tree; merged commit ancestor of main |
| `existing-integrations-ux` | `ef98d073956b288b05432aaaffe399f9bec5a20c` | unchanged PR head; exact squash tree; merged commit ancestor of main |
| `http-remote` | `10fa8371598952d04ec17cdc12833fc452502ac4` | tip ancestor of main |
| `instructions` | `74f923e99c73b21b965d8fd3e20358f98a78ba28` | tip ancestor of main |
| `lab-sync` | `cae0b76785cbd710fb4bd7b238a6524bfad881c6` | tip ancestor of main |
| `mcpb` | `093f13156c4bab63a3b05beb913c907e3ff2d206` | tip ancestor of main |
| `numbers-cyrillic` | `c998d822526efa2e001ccd5227465bcf7719bf79` | tip ancestor of main |
| `p2-evals` | `6e6b29f3886f33c17345ad1347591a75d84d539b` | tip ancestor of main |
| `protected-policy` | `12e779e1cdfbc8cd90d9a15392c773fdb07631d8` | unchanged PR head; exact squash tree; merged commit ancestor of main |
| `pypi` | `24099ba5c37b93e7e1f4da21f4061533a4f3f816` | tip ancestor of main |
| `receipt-contract-v1` | `70b7b84e913b5316f535aeafcdbb7383498a9841` | unchanged PR head; exact squash tree; merged commit ancestor of main |
| `release-1.0` | `296039d35d8fde069e934e963b3bb2080b76fe5c` | tip ancestor of main |
| `release-1.0.1` | `d5fdcee539ea45cb6df78fb4e62a4b3d220fd32d` | tip ancestor of main |
| `release-1.1.0` | `fd04593b9a9517c5d94851cb00155814fc5f6abf` | tip ancestor of main |
| `release-1.1.1` | `0e8796429023b19a0a14ccf205f04b3b726a070b` | tip ancestor of main |
| `release-hardening-2.0` | `24527342cba5c3105240e7e799aadbca615a321d` | unchanged PR head; exact squash tree; merged commit ancestor of main |
| `render` | `16021757ec9c6bd4b577567d461a61af7d047857` | tip ancestor of main |
| `repo-trust-boundary` | `74766755c27c5016767767a275ea96cc1b7fe850` | tip ancestor of main |
| `safe-defaults` | `fbc092f3d93d89397c915fa9d26e7e4992ef8308` | tip ancestor of main |
| `security-git-execution-hardening` | `f2ab90e3ab19736badbc84f10f5b5d205759edc8` | unchanged PR head; exact squash tree; merged commit ancestor of main |
| `trust-and-limits` | `1ca1083d6d3664f9f6181da237a85e889dd9070f` | tip ancestor of main |
| `typed-findings` | `856358a3a9f2bad30c09321c42883572aa6eef4f` | tip ancestor of main |
| `typed-gate` | `2af4785a16948135b95ca3883bd737861319b401` | tip ancestor of main |
| `verification-profiles` | `3f8dbe6679cc73d2091dc0587d9ce6d24d77e2b6` | unchanged PR head; exact squash tree; merged commit ancestor of main |

INVESTIGATE: `release-candidate-2.0` at `431f924c5ac00d46cff2f2e71d68b977be5024f5`; merged PR #38; tree equality and merge ancestry verified. This ref is deliberately absent from the approved-candidate section.

Before any separately approved deletion, fetch again, verify the full expected SHA, reject moved refs and new open PR dependencies, recheck representation in current main, and preserve the complete-history backup. Use an exact-ref lease; never delete all branches described by GitHub as merged. Restore from the retained bundle only after verifying the replacement ref does not already exist.

## Backup verification

- Original bundle verified again as a complete-history bundle; SHA-256 remains `1fc4fe1a92e8642165716cc7741017121612c6012dc274075e5fba32d47fbee7`.
- Updated complete-history bundle verified: `<owner storage>/stage4-evidence/post-merge-before-cleanup.bundle` (the owner's local path, redacted for publication; the file is identified by the SHA-256 below).
- Updated SHA-256: `54f933af9b6317a0e5c774b4c59707cd3d2a7c3e37047131b2eb6fc45a28e5be`.
- This updated backup covers all fetched remote refs and the reconciliation merge, including merged main and former #38 tip. Before future cleanup, copy it to durable owner-controlled storage. A final exact-head bundle is also created after the review package commit; its digest and path are reported in the PR description/final handoff without creating a self-referential commit.

## Current settings versus supported proposals

The [new settings capture](post-merge-settings.json) is distinct from the original snapshot. No repository/account setting was changed.

| Control | Newly verified fact | Recommendation and safety condition |
|---|---|---|
| main | Classic protection absent (404 Branch not protected); GraphQL patterns empty; rulesets including parents empty | Active exact-main ruleset: mandatory PR, nine contexts above from app 15368, strict up-to-date checks, resolved threads, no force push or deletion, no bypass. Solo mode uses zero required approvals; require one independent approval only after appointing another reviewer. |
| v* tags | No tag ruleset | Separate immutable update/deletion ruleset with no bypass and creation-only restriction with admin-role bypass (role ID 5). No v* branches exist. |
| Actions | All actions allowed, no enforced SHA pinning; token defaults read; PR approval disabled; fork policy first_time_contributors | Keep read/no-approval. Select GitHub-owned actions plus pypa/gh-action-pypi-publish@*; approve all external contributors. Do not enforce SHA pinning until a coordinated workflow change pins every action. This allowlist does not restrict code fetched through npm, pip or curl. |
| pypi | No reviewers/protection; no deployment ref policy; administrator bypass allowed | Required reviewer, bypass off; custom policy with tags v* and no branches. Owner reviewer/self-review allowed for solo mode; another actual reviewer plus prevent_self_review=true for independent review. Review historical-tag workflow definitions before approving old-tag dispatches. |
| Secret scanning | Scanning and push protection enabled | Preserve both; no paid feature is assumed. |
| Private vulnerability reporting | Disabled | Enable only after owner approval; SECURITY.md honestly describes the unavailable-button fallback meanwhile. |

Availability: GitHub reports the repository public and this connection admin. The account endpoint returned no plan name (`null`), so no paid plan is asserted. Branch/tag rulesets, public-repository environment reviewers/ref restrictions and private reporting are supported for this public repository; read APIs are accessible. No paid push ruleset, organization team or Evaluate-only rule is proposed. Actual write acceptance and enforcement cannot be proven without the prohibited settings changes; read values back and validate after specific approval.

Sources: [ruleset availability](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets), [environment review/ref behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments), [private reporting](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository). [Current payloads](settings-proposals.json) are proposals, not evidence of enforcement.

## Publication authorization gap

Confirmed against the final merged files. Recovery jobs can skip the PyPI environment. [Detailed analysis, minimal one-line proposal and consequences](publication-authorization.md) are included. The unapplied patch adds environment pypi to the existing authorize job; retaining the publisher environment preserves trusted publishing but can require a second approval in a normal run. Reviewer configuration and workflow approval are both release blockers. PR #39 does not apply that patch, dispatch release.yml, or modify publication scripts.

## Community and public presentation

- SECURITY.md is consistent with the final execution-boundary docs and privacy policy. It claims no security email, response SLA, certification or guaranteed backports. Private reporting remains disabled and the fallback is explicit.
- Bug/feature forms and PR template contain no unsupported client promises or private-data requests. Local Markdown links and form structure are validated. They become active as community files only when merged to the default branch.
- docs/README.md now indexes the Claude Code, configuration, research and distribution guides introduced by #38. CONTRIBUTING version guidance matches all manifests checked by test_version.py. README and package metadata remain unchanged, including the published 1.1.1 versus unreleased 2.0 distinction.
- Proposed About: Verify evidence behind AI agent reports: quotes, repository state, PR/CI status and command output. CLI, MCP and plugins; no model calls.
- Proposed homepage after this PR merges: https://github.com/tsyyan/buddie/blob/main/docs/README.md . No external site is invented.
- Proposed topics: retain ai-agents, ai-safety, citation-verification, deep-research, faithfulness, llm-evaluation; add mcp, mcp-server, claude-code, codex, developer-tools, evidence-verification.
- Current Issues on, Discussions off, Wiki on. Preserve settings for review; proposed Wiki disablement remains optional and unexecuted.

## Remaining owner decisions and sequence

1. Complete independent review of current #39 diff and its final head-bound CI; approve its merge separately. Keep Draft until that review is complete.
2. Approve protection settings and choose solo versus independent reviewer. Apply/read back main/tag rules and pypi restrictions only under that approval. Avoid self-review prevention with only the owner appointed.
3. Approve the separate publication-gate follow-up before tagging or publishing; the document-only proposal does not close the release blocker. Validate actual protected-environment behavior during the separately approved release process.
4. Approve public About/homepage/topics, private reporting and optional Wiki change. Do not turn on Discussions automatically.
5. Re-fetch and regenerate the final deletion list at execution time; approve exact name/SHA pairs. Former #38 remains outside the 34-candidate list until explicitly reviewed. No deletion is authorized by this report.
6. Release tags, publication and catalog changes require independent explicit authorization. Follow the final docs/release.md only after all release blockers are resolved.

## Validation and verdict scope

Validation commands and final CI conclusions are recorded in the PR description. New offline tests validate manifest exclusions, local community links/index coverage and the unapplied gate patch in a temporary copy. Existing security, release authorization, artifact, README, version and catalog tests are run locally; the entire hosted matrix is run on the final PR head. No release workflow is dispatched to validate this package.

READY FOR REVIEW applies to the maintenance package after its final CI and independent review findings are resolved. It is not release approval: the publication gate is still unapplied and the protection/reviewer settings remain unchanged.

## Addendum: the publication gate follow-up

Recorded after this audit; the audit above is unchanged. The one-line workflow proposal from "Publication
authorization gap" is applied by the pull request on branch `release-unified-approval-gate`
([publication-authorization.md](publication-authorization.md), status note; [docs/release.md](../release.md), "Who
approves a publication"). That closes the workflow half of the release blocker. The other half is not closed: the
`pypi` environment's reviewers, administrator bypass and `v*` tag rule are the owner's settings, still as recorded in
[post-merge-settings.json](post-merge-settings.json).

## Addendum: settings, read back

Observed through the API later on 2026-10-24, after this record: environment `pypi` has required reviewer `tsyyan` (self-review allowed), administrator bypass off and deployments from tags `v*` only; rulesets `main-reviewed-ci`, `release-tags-creation` and `release-tags-immutable` are active. Applied by the owner, not by these maintenance changes. The current release checklist is in
[docs/release.md](../release.md#final-pre-release-checklist).
