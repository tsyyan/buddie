# Pre-release repository maintenance and public presentation

Audit date: 2026-10-24 (Europe/Saratov). Snapshot UTC: `2026-10-23T21:25:12.449620+00:00`.
Baseline main: [`b6464a7839274297c5c110ddd1a50557f4281c42`](https://github.com/tsyyan/buddie/commit/b6464a7839274297c5c110ddd1a50557f4281c42).

This is a review package, not authorization to change settings, delete branches, merge, tag or publish. PR #38 and its branch were read only. Its files, README and release workflows are excluded from this change.

## Evidence and priorities

Confirmed facts below come from GitHub REST/GraphQL and a full clone. Connector PR metadata disagreed with direct API data: the cached body referred to a previous head. The direct API and git refs agree on `e34cb1f3a9552a009bc7a9981e4d66b27e717754`; its check snapshot contains failures/cancellations and must not be described as green. These are point-in-time observations, not a verdict on later Claude work.

- **P0: publication controls.** No repository/inherited rulesets; GraphQL lists no classic branch protection patterns, including `main` or `v*`. REST main protection returns 404 with Branch not protected. Current main publishes on a `v*` tag push. Environment `pypi` has no protection rules, no deployment ref policy, and permits administrator bypass. Do not create a release tag before #38 and the agreed controls are in place.
- **P0: final CI.** Re-read the exact final #38 head and all its check runs before any merge decision. No fixes to #38 are included here.
- **P1: reporting and navigation.** SECURITY.md and Issues/PR templates are absent on baseline main. CONTRIBUTING exists with local test instructions. This package adds reporting guidance, forms and a documentation index.
- **P1: branch cleanup.** 34 deletion candidates, 2 retained branches. Ten candidates retain commit identities absent from main after squash merges; complete tree equality was verified, not inferred from PR status.
- **P2: discoverability.** About describes quote checking only; homepage is empty. Topics emphasize research. Issues enabled; Discussions disabled; Wiki enabled, but wiki remote is not publicly accessible. Keep Issues as the single support entry point for now.

Sources: [branches](https://api.github.com/repos/tsyyan/buddie/branches?per_page=100), [PRs](https://api.github.com/repos/tsyyan/buddie/pulls?state=all&per_page=100), [rulesets](https://api.github.com/repos/tsyyan/buddie/rulesets?includes_parents=true), [repository](https://api.github.com/repos/tsyyan/buddie), [main protection](https://api.github.com/repos/tsyyan/buddie/branches/main/protection), [pypi environment](https://api.github.com/repos/tsyyan/buddie/environments/pypi), [community profile](https://api.github.com/repos/tsyyan/buddie/community/profile). Some administrative endpoints require owner authentication. Exact captured values: [settings snapshot](settings-snapshot-2026-10-24.json).

## Every existing branch

Ahead/behind are commit counts relative to the baseline main. DELETE means eligible for separately approved cleanup, never delete now. All listed PRs except #38 are merged. No branch currently remains INVESTIGATE after the tree checks; a moved tip, reopened/new PR or missing ancestry proof changes its recommendation to INVESTIGATE.

| Branch | Tip | PR(s) | Ahead / behind | Recommendation / proof |
|---|---|---|---|---|
| `adversarial-verification-suite` | `9059fc0796b7` | [#36](https://github.com/tsyyan/buddie/pull/36) | 4 / 2 | **DELETE** — squash tree verified |
| `canon-here` | `089dbfc0d73f` | [#5](https://github.com/tsyyan/buddie/pull/5) | 0 / 68 | **DELETE** — ancestor of main |
| `catalog-p1` | `08a835d8e5d4` | [#17](https://github.com/tsyyan/buddie/pull/17) | 0 / 39 | **DELETE** — ancestor of main |
| `charset` | `7abd07be8e38` | [#12](https://github.com/tsyyan/buddie/pull/12) | 0 / 49 | **DELETE** — ancestor of main |
| `claude/project-thread-7d8b7g` | `d93d8bcdb433` | [#1](https://github.com/tsyyan/buddie/pull/1) | 0 / 79 | **DELETE** — ancestor of main |
| `codex` | `f6e875f152dd` | [#9](https://github.com/tsyyan/buddie/pull/9) | 0 / 63 | **DELETE** — ancestor of main |
| `config-decoupling` | `4296db7d0997` | [#26](https://github.com/tsyyan/buddie/pull/26) | 0 / 17 | **DELETE** — ancestor of main |
| `disclose-after-return` | `fe56e8363e70` | [#19](https://github.com/tsyyan/buddie/pull/19) | 0 / 33 | **DELETE** — ancestor of main |
| `environment-collector-snapshots` | `d77cd83203b0` | [#33](https://github.com/tsyyan/buddie/pull/33) | 2 / 5 | **DELETE** — squash tree verified |
| `evidence-freshness-staleness` | `f26465716443` | [#35](https://github.com/tsyyan/buddie/pull/35) | 2 / 3 | **DELETE** — squash tree verified |
| `evidence-registry` | `2f1b8f2963e4` | [#29](https://github.com/tsyyan/buddie/pull/29) | 5 / 9 | **DELETE** — squash tree verified |
| `existing-integrations-ux` | `ef98d073956b` | [#32](https://github.com/tsyyan/buddie/pull/32) | 1 / 6 | **DELETE** — squash tree verified |
| `http-remote` | `10fa83715989` | [#6](https://github.com/tsyyan/buddie/pull/6) | 0 / 68 | **DELETE** — ancestor of main |
| `instructions` | `74f923e99c73` | [#13](https://github.com/tsyyan/buddie/pull/13) | 0 / 49 | **DELETE** — ancestor of main |
| `lab-sync` | `cae0b76785cb` | [#4](https://github.com/tsyyan/buddie/pull/4), [#3](https://github.com/tsyyan/buddie/pull/3), [#2](https://github.com/tsyyan/buddie/pull/2) | 0 / 70 | **DELETE** — ancestor of main |
| `main` | `b6464a783927` | — | 0 / 0 | **KEEP** — Default branch |
| `mcpb` | `093f13156c4b` | [#7](https://github.com/tsyyan/buddie/pull/7) | 0 / 62 | **DELETE** — ancestor of main |
| `numbers-cyrillic` | `c998d822526e` | [#14](https://github.com/tsyyan/buddie/pull/14) | 0 / 45 | **DELETE** — ancestor of main |
| `p2-evals` | `6e6b29f3886f` | [#18](https://github.com/tsyyan/buddie/pull/18) | 0 / 36 | **DELETE** — ancestor of main |
| `protected-policy` | `12e779e1cdfb` | [#28](https://github.com/tsyyan/buddie/pull/28) | 3 / 10 | **DELETE** — squash tree verified |
| `pypi` | `24099ba5c37b` | [#8](https://github.com/tsyyan/buddie/pull/8) | 0 / 62 | **DELETE** — ancestor of main |
| `receipt-contract-v1` | `70b7b84e913b` | [#31](https://github.com/tsyyan/buddie/pull/31) | 2 / 7 | **DELETE** — squash tree verified |
| `release-1.0` | `296039d35d8f` | [#10](https://github.com/tsyyan/buddie/pull/10) | 0 / 53 | **DELETE** — ancestor of main |
| `release-1.0.1` | `d5fdcee539ea` | [#15](https://github.com/tsyyan/buddie/pull/15) | 0 / 43 | **DELETE** — ancestor of main |
| `release-1.1.0` | `fd04593b9a95` | [#20](https://github.com/tsyyan/buddie/pull/20) | 0 / 31 | **DELETE** — ancestor of main |
| `release-1.1.1` | `0e8796429023` | [#21](https://github.com/tsyyan/buddie/pull/21) | 0 / 29 | **DELETE** — ancestor of main |
| `release-candidate-2.0` | `e34cb1f3a955` | [#38](https://github.com/tsyyan/buddie/pull/38) | 6 / 0 | **KEEP** — Active draft PR #38 owned by Claude; do not modify. |
| `release-hardening-2.0` | `24527342cba5` | [#37](https://github.com/tsyyan/buddie/pull/37) | 3 / 1 | **DELETE** — squash tree verified |
| `render` | `16021757ec9c` | [#11](https://github.com/tsyyan/buddie/pull/11) | 0 / 51 | **DELETE** — ancestor of main |
| `repo-trust-boundary` | `74766755c27c` | [#23](https://github.com/tsyyan/buddie/pull/23) | 0 / 24 | **DELETE** — ancestor of main |
| `safe-defaults` | `fbc092f3d93d` | [#16](https://github.com/tsyyan/buddie/pull/16) | 0 / 41 | **DELETE** — ancestor of main |
| `security-git-execution-hardening` | `f2ab90e3ab19` | [#34](https://github.com/tsyyan/buddie/pull/34) | 1 / 4 | **DELETE** — squash tree verified |
| `trust-and-limits` | `1ca1083d6d36` | [#24](https://github.com/tsyyan/buddie/pull/24) | 0 / 21 | **DELETE** — ancestor of main |
| `typed-findings` | `856358a3a9f2` | [#25](https://github.com/tsyyan/buddie/pull/25) | 0 / 16 | **DELETE** — ancestor of main |
| `typed-gate` | `2af4785a1694` | [#27](https://github.com/tsyyan/buddie/pull/27) | 0 / 12 | **DELETE** — ancestor of main |
| `verification-profiles` | `3f8dbe6679cc` | [#30](https://github.com/tsyyan/buddie/pull/30) | 2 / 8 | **DELETE** — squash tree verified |

The new maintenance branch `pre-release-maintenance-2026-10-24` is additional to these 36 baseline branches: KEEP while its draft PR is open. Reclassify only after its eventual merge. Full SHAs, unique commit subjects, patch-equivalence counts and squash merge SHAs: [machine-readable audit](branch-audit-2026-10-24.json). `git cherry` alone did not prove equivalence for multi-commit squashes; exact tip/merge tree equality plus merge ancestry did.

## Safe cleanup procedure (approval required)

1. Keep the recorded branch-to-SHA manifest and a full `git bundle --all` outside the working tree. A complete-history bundle was created and verified locally for this audit. Copy it to durable owner-controlled storage and record its SHA-256 before deletion; it is not committed publicly. It preserves the original squash-merged commit identities.
2. After #38 finishes, fetch current refs and re-list all PRs. For every candidate require its full tip SHA to equal this manifest, no open PR from the branch, and the associated merged commit to remain reachable from current main. Verify tip ancestry or the exact tree equality again. Reject new/unmatched branches.
3. Present the exact name/SHA deletion list for separate user approval. Do not auto-delete a branch merely because its PR is merged. Exclude main, #38 while active, this maintenance branch while active, and all moved tips.
4. Delete only explicitly approved names with a lease against each recorded remote SHA, stopping on any mismatch. Do not run a blanket merged-branch cleanup. Re-list remote branches afterwards.
5. Restore an accidentally deleted ref by pushing the saved SHA from the verified bundle back to that exact branch name, after confirming no replacement ref exists. Restoring a release tag is outside this procedure; no tags are deleted or created.

## Exact proposed protections (not applied)

Reviewable payloads are in [settings-proposals.json](settings-proposals.json). They describe future settings, not executable migration automation.

### Main

- Active branch ruleset targeting exactly `refs/heads/main`; no bypass actors. Restrict deletion and block force pushes. Require PRs and resolved review threads. No linear-history requirement, signed-commit requirement, deployment gate or merge queue is introduced.
- Require up-to-date status checks from GitHub Actions (app ID 15368). After #38: `test (3.11)`, `test (3.12)`, `test (3.13)`, `os (ubuntu-latest)`, `os (macos-latest)`, `os (windows-latest)`, `catalogs`, `docker`, `release-candidate / build`. Confirm exact final check names in the API before enabling; main currently has package/mcpb jobs that #38 replaces.
- Solo-maintainer baseline: 0 approving reviews (PR and CI still mandatory). If an independent collaborator is appointed, use 1 approval, dismiss stale approvals and require approval of the latest push by someone else. Do not configure an impossible self-approval requirement. CODEOWNERS is deferred until actual owners accept responsibility.

### Release refs

- Active tag ruleset for `refs/tags/v*`: restrict updates and deletions, with **empty bypass list**. A separate creation-only tag ruleset allows repository administrators (role ID 5) to bypass creation restriction. Separating them avoids allowing the release creator to move/delete an existing release tag. It is role-level authority, not an individual-user allowlist. An admin can still edit rulesets; this is not a protection against a malicious repository owner.
- No `v*` branches exist in the snapshot. Use tag rules, not branch protection patterns, to protect releases. If release branches are introduced later, define a separate branch ruleset.

### Actions and pypi

- Keep existing default token permission read and PR review approval disabled. Workflow files already default to contents:read; elevated contents/id-token rights are scoped to publishing jobs. No pull_request_target trigger is present in baseline workflows or the inspected #38 versions.
- Current Actions allow all actions, do not require SHA pinning, and require fork approval only for first-time contributors. Proposed: allow GitHub-owned actions plus `pypa/gh-action-pypi-publish@*`, require approval for all external contributors. The inspected workflows use these action owners. Stage full action-SHA pinning and pinned CLI/schema versions in a later workflow PR coordinated with Claude; do not enable enforced SHA pinning until every referenced action, including the publishing action, is migrated and CI passes.
- `pypi`: required reviewer `tsyyan` (user ID 305538897), administrator bypass off; Selected branches and tags with one **tag** policy `v*`, no branch policy. This gives a manual owner approval gate. For a solo owner leave prevent_self_review=false; otherwise their own deployment is impossible to approve. For actual two-person approval choose an independent reviewer and set prevent_self_review=true. These are alternative configurations requiring an owner decision.
- pypi approval protects only jobs that reference that environment. In #38, recovery can run registry/GitHub stages with PyPI skipped. The tag rules plus restricted repository write access and #38 authorization checks still matter. If approval must cover every publishing/recovery stage, ask Claude for a separate shared approval gate; do not claim pypi reviewer alone covers those stages.
- Secret scanning and push protection are enabled; preserve them. Dependabot security updates are disabled. Consider a separate Actions dependency-update configuration after #38; runtime Python dependencies are currently empty. PyPI trusted-publisher configuration itself was not accessible from this GitHub audit.

GitHub references: [ruleset creation and bypass](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository), [available rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets), [environment approval and ref restrictions](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments).

## Public presentation: facts and proposals

| Area | Confirmed baseline | Concrete proposal |
|---|---|---|
| About | Quote-only description | `Verify evidence behind AI agent reports: quotes, repository state, PR/CI status and command output. CLI, MCP and plugins; no model calls.` |
| Homepage | Empty; no GitHub Pages site | After this PR merges, use `https://github.com/tsyyan/buddie/blob/main/docs/README.md` as the documentation homepage. Do not invent a product website. |
| Topics | ai-agents, ai-safety, citation-verification, deep-research, faithfulness, llm-evaluation | Retain these; add `mcp`, `mcp-server`, `claude-code`, `codex`, `developer-tools`, `evidence-verification` (12 total). |
| Issues | Enabled; no non-PR issues returned, no issue templates | Keep enabled, add bug/feature forms; allow blank issues for questions. No unsolicited issues are opened. |
| Discussions | Disabled | Keep disabled until conversation volume justifies a second support channel. |
| Wiki | Enabled; no publicly accessible wiki detected | Disable after approval; keep versioned docs as the source of truth. No wiki content deletion is proposed. |
| Security | docs/security.md exists; root policy absent; private reporting disabled | Add SECURITY.md with an honest fallback. Enable private vulnerability reporting separately, verify the Report a vulnerability button, then simplify fallback wording if desired. No invented email or SLA. |
| CONTRIBUTING | Exists, with setup, tests and source-history context | Add links to docs, ordinary Issues and confidential reporting. Existing contribution rules remain. |
| PR template | Absent | Add problem/result, actual validation, compatibility/risk prompts. |
| Navigation | README is long; #38 rewrites it | Add docs/README.md now; let Claude finish README. After #38, add index/security links there in a separate follow-up and verify newly moved docs from #38 are indexed. |

The community profile returns a documentation URL containing `tree/master/docs`; main is the default branch. This does not prove a visible broken link on the repository page. Use the explicit proposed homepage above and re-check the public page after merge. Known local file links in the added package are validated; external catalog links and the rendered README remain #38 scope. There is no code of conduct on baseline main; consider adopting one later only with an accepted enforcement contact and process.

Private reporting reference: [GitHub configuration guide](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository).

## Sequence after PR #38

1. Read final #38 head, diff and checks; wait for Claude to finish. Resolve failures there through its owner. Obtain explicit merge approval for #38, then merge only that reviewed head. No release tag yet.
2. Refresh this maintenance branch from the merged main without changing #38. Re-check that SECURITY.md, forms, index and CONTRIBUTING links work with the final documentation layout. Run the final required checks on this PR and obtain separate merge approval.
3. Approve and apply protections as separate operations: immutable-tag rules, tag creation restriction, chosen pypi reviewer/ref restrictions, main PR/CI rules using final check names. Validate saved values with read-only APIs and verify the approval gate during the approved release process. Do not use a test release tag or a publishing dispatch merely to test controls.
4. Merge the approved maintenance PR. Enable private vulnerability reporting and verify the private form; set About/homepage/topics and optionally disable the unused Wiki only after specific settings approval. Keep Discussions disabled and Issues enabled.
5. Re-audit refs and PR associations, refresh durable bundle and manifest, request approval of the final exact deletion list, then perform leased deletions. #38 branch becomes a new candidate only after its merge and proof; do not assume it is covered by approval for the 34 baseline candidates.
6. Re-check README navigation and distribution links after #38. Address the development-versus-published version distinction using its docs; any marketplace ref changes are a separate owner decision.
7. Hand off to the release procedure in final docs/release.md. Creating a version tag, dispatching publication and publishing releases remain separately authorized operations outside this maintenance task.

## Review and validation scope

Added files and the CONTRIBUTING insertion do not overlap the 26 filenames returned for #38 at audit time. No runtime code, workflows, manifests, README, release files or public settings are changed. Validation should cover YAML form structure, local Markdown links, JSON parsing, whitespace and changed-file overlap; CI remains the source for broader repository checks. The backup is local and must be retained independently before future cleanup.

Local validation completed: all 11 changed files checked for applicable YAML form structure, JSON parsing and local Markdown file links; zero overlap with the captured #38 file list. Existing catalog, version and release-hardening tests: 12 passed. `git diff --check` passed. This does not assert the full CI suite is green. The backup SHA-256 is `1fc4fe1a92e8642165716cc7741017121612c6012dc274075e5fba32d47fbee7`; its local filename is `before-cleanup.bundle` outside the repository. The raw settings and PR snapshots are also retained there.
