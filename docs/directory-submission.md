# New Anthropic plugin directory submission (prepared 2026-10-29)

## Portal check, 2026-10-30

The published 2.0.5 on `plugin-stable` (`469fa13`) is blocked by `UNPINNED_NPX` in `hooks/run.sh`.
There is no package download in that launcher: the expanded finding says the scanner mistook shell patterns for
program names. Explicit Python calls and split path commands alone did not resolve it. A compact 2.0.6 preview
(`7214182` on `preview/anthropic-launcher-206`) passed after replacing the fallback's `case` patterns with equivalent
builtin parameter matching and `test`; Next became enabled. The five warnings and six policy holds remain visible
for reviewers. This preview is not a release or a submission. Submit only after publishing 2.0.6, promoting its exact
package to `plugin-stable`, and validating that released revision again.

The 1.1.1 submission ("buddie: claim checker", repository root at `3a351b4`) was withdrawn by the owner: a submission
under review cannot be edited. This is the packet for the new one. Nothing here submits anything; the portal steps
are the owner's. Approval is the reviewer's decision under the
[Software Directory Policy](https://support.claude.com/en/articles/13145358-anthropic-software-directory-policy);
no check here predicts it.

## What changes against the withdrawn submission

| | Withdrawn (1.1.1) | New |
|---|---|---|
| Source | repository root, `main`/tag, 247 files incl. research data | branch **`plugin-stable`**: the compact package only (69 files at 2.0.4), its own history with no research or tests |
| Files a reviewer must inspect by hand (non-image > 256 KiB) | 2 (`results/E008-…`) | **0** |
| Scripts referring to an image (`scripts/make_icon.py`) | present | absent |
| CI, Dockerfile, release docs, test fixtures with token-like strings | present | absent |
| Name | buddie: claim checker | **buddie** |
| Icon | green check mark | the dog from the README logo; 23 KB from 2.0.5 (884 KB at 2.0.4) |
| Version | 1.1.1 | **2.0.5 or later** (see "When") |

The runtime code is the same package that ships on PyPI (`buddie/*.py`), so #61's runtime findings still apply and
are answered below, not hidden.

## When

Submit after 2.0.5 is released and promoted, so the first scanned commit already has the unified name and the small
icon:

1. Merge the change that adds this document (name, icon, marketplace channel).
2. Protect `plugin-stable` (deletion and force-push blocked; [distribution.md](distribution.md#current-channel-check-2026-10-29)).
3. Cut and publish 2.0.5 with `only: all`; check that `plugin-stable`'s head commit message names 2.0.5 and that
   `git ls-tree -r origin/plugin-stable` matches the release's `plugin-manifest.json`.
4. Then submit. Submitting at 2.0.4 is possible, but its listing would show "Buddie — AI Agent Reliability Toolkit"
   and the 884 KB icon until the next scan.

## Portal fields

At [claude.ai/directory/manage](https://claude.ai/directory/manage) → **Submit new** → **Plugin bundle**:

| Field | Value |
|---|---|
| Repository | `tsyyan/buddie` |
| Plugin path | empty (the plugin is the root of `plugin-stable`) |
| Tracked ref | branch `plugin-stable` (each release advances it; the directory rescans new commits) |
| Name | `buddie` (from `plugin.json`) |
| Short description | Checks AI agents' claims against primary evidence, with no model; observes only what you grant. |
| Description | the one-paragraph text in [listing-copy.md](listing-copy.md#descriptions) |
| Category | Developer tools |
| Support | https://github.com/tsyyan/buddie/issues |
| Privacy policy | https://github.com/tsyyan/buddie/blob/main/PRIVACY.md |
| Documentation | https://github.com/tsyyan/buddie#readme |

Not verified from here (portal-only): that the portal accepts a branch other than the default as the tracked ref, and
whether it scans only the tracked branch or the whole repository. If it scans the whole repository, the research files
on `main` come back as manual-review items; answer them as research data that the plugin never loads.

## Validate before submitting

```sh
git fetch origin plugin-stable
git worktree add /tmp/buddie-stable origin/plugin-stable
npx --yes @anthropic-ai/claude-code@2.1.310 plugin validate --strict /tmp/buddie-stable
npx --yes @anthropic-ai/claude-code@2.1.310 plugin validate --strict --profile directory /tmp/buddie-stable
```

Then **Validate** in the portal and fix anything marked *Blocking*.

## Findings the scan is likely to raise, and the answers

| Finding | Where | Answer |
|---|---|---|
| Credential access | `buddie/effects.py`, `buddie/remote.py`, `buddie/verbatim/access.py`, `plugin.json` `userConfig.github_token` | The GitHub token is optional, declared `sensitive: true`, entered by the person in the plugin's settings and sent only to `api.github.com` (or a GitHub Enterprise API named in an administrator's protected policy). buddie never reads an ambient `GITHUB_TOKEN`; cross-origin redirects are refused before contact; malformed tokens are rejected before a header is built. `remote.py` is the optional HTTP server (not started by the plugin) and compares an inbound bearer token. `access.py` reads proxy and CA settings only in the optional browser mode. |
| Downloads / runs programs | `.mcp.json` (`python3 run.py serve`), `hooks/run.sh` | The plugin runs its own bundled Python; nothing is downloaded at install or run time. Hooks start the same launcher for `SessionStart` and `Stop`. |
| Network access | `snap`, `verify_report`, `feedback_*` | Fetches only the URLs a report cites (to snapshot them) and the GitHub API for `pr:`/`ci:` anchors. Both can be turned off (`BUDDIE_FETCH=0`, `BUDDIE_GITHUB=0`). No telemetry, no model calls. |
| Reads the session transcript | `buddie/hook.py` | Reads the Claude Code transcript in place to check `run:` anchors; never copies or sends it. The `read_transcript` setting turns it off. |
| Image referenced by manifest | `plugin.json` `icon` | The listing icon; Claude Code does not read it. |

## Data-handling answers

| Question | Answer |
|---|---|
| Reads personal data? | **Reads and stores**: transcript/report text is read locally; source snapshots, pending report lines and feedback state can contain personal data. The transcript file itself is not copied or uploaded. |
| Stores data? | Local journal hashes/verdicts, pending report lines, feedback state and content-addressed snapshots, including explicitly authorized private GitHub evidence. Optional journal text is off by default. See PRIVACY.md for all locations and controls. |
| Sends data elsewhere? | **Yes, listed in README**: requests to cited URLs and the GitHub API (or an administrator-approved Enterprise API). No report or transcript is sent to a Buddie collection service. |
| Retention | **Longer**: local files have no automatic expiry and remain until the person deletes them. There is no developer-operated collection backend in the plugin. |
| Intended for people under 18? | No. |

Evidence for the description: the plugin evals ([research.md](research.md#plugin-evals)). Limits to state plainly:
[limitations.md](limitations.md).
