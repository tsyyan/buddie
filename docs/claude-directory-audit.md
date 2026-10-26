# Claude Directory compliance audit — 2026-10-26

This is a remediation draft, not a claim of Directory approval or full submission readiness.
Keep the existing `buddie: claim checker` submission in review. This change does not withdraw, replace, resubmit,
publish a version, merge, rewrite history, or change Feedback MCP implementation.

## Scope and evidence

- Reviewed submission: `v1.1.1`, `3a351b4c56e05208af075378cb554c8dc8daed8b`.
- Audit base: `2ca999a7b1ebfb91416d574318c656dda5ce3955` (`main`, version 2.0.1).
- Candidate branch: `fix/claude-directory-compliance`. Validation is bound to the exact commit in the PR and its
  check runs, not the version string. No version is bumped here.
- Inputs: user's submission status and screenshot. The screenshot expands all six credential paths, but the three
  image/font instances, three unknown fields and five download/run instances are collapsed. Their categories
  have been audited; exact instance-to-source matching remains unverified. Do not invent a match from counts.
- The portal was not changed. Browser inspection was stopped because Computer Use could not establish its URL.
  The historical private Directory scanner is not independently available in this environment.

Official references checked on the audit date:

- [Manifest reference](https://code.claude.com/docs/en/plugins-reference): listing fields are supported in
  `plugin.json`; CLI v2.1.281+ recognizes them. Preserve `icon`, `documentationUrl`, `supportUrl`, `privacyPolicyUrl`,
  `displayName` and `userConfig`. Do not move them into a marketplace entry.
- [Pre-submission checklist](https://claude.com/docs/plugins/pre-submission-checklist): the folder controls shipped
  scope; some repository checks are wider. Non-image/font files above 256 KiB require review. `export-ignore` and
  `export-subst` are prohibited. A runtime schema pass does not replace portal scanning.
- [Submission process](https://claude.com/docs/plugins/submit): updates follow the configured branch/tag;
  validation describes one commit. Continue the existing submission rather than making a duplicate.
- [Directory policy](https://support.claude.com/en/articles/13145358-anthropic-software-directory-policy): disclose
  data handling, minimize collection, maintain accurate capabilities and support. Transcript access and retained
  local evidence need reviewer consideration; technical tests cannot decide policy interpretation.

## Finding-by-finding matrix

| Finding | Evidence | Risk / classification | Fix | Residual risk |
|---|---|---|---|---|
| A. Uninspectable `results/E008-drb2-fresh/results.json` | Historical Git blob is 805,873 bytes, valid JSON; experiment E008 results, not imported by runtime. `sample_blind.json` is 714,677 bytes. | Packaging issue: exceeds inspection limit, not evidence of malware. | Reproducible exact-blob inventory; preserve scientific data. Desktop already excludes `results/`. | Both files still belong to the root Git-source plugin. The hold is not cleared by this PR. |
| A. Additional current files | Baseline inventory also finds `tests/data/gate_golden.json` over 256 KiB. | Packaging issue: regression evidence, not runtime. | Inventory reports every such file; no hidden filtering. | Root Directory source still contains it. |
| B. Three image/font code-reference findings | Historical repository has only `assets/icon.png`; PNG format passed in the supplied screenshot. References occur in both manifests and development-only `scripts/make_icon.py`, which creates PNG bytes. No runtime image execution found. Current assets also include branding PNGs and demonstration SVGs. | Static assets / review-only heuristic. Exact three scanner instances unavailable. | Keep legitimate icon. Inventory all assets and review references (`git grep` below). | A script mentioning an image may still trigger manual review; no assertion that all three messages are cleared. |
| C. `buddie/effects.py` | Reviewed code reads two Buddie-specific token names; historical MCP config exported userConfig as `BUDDIE_GITHUB_TOKEN`. Historical Authorization was a normal urllib header. Current base uses unredirected headers but still sends the Buddie env token to an environment-selected API. | Confirmed credential-destination vulnerability under inherited token + agent-controlled API environment; historical redirects also allowed credential forwarding. | Neither token goes to an environment-selected API. Protected HTTPS Enterprise API retained. Cross-origin/out-of-prefix redirect refused before contact. Explicit plugin option wins. | Administrator-selected endpoint, proxy, TLS trust store, interpreter and process environment remain trusted. |
| C. `buddie/remote.py` | `make_server` reads `BUDDIE_HTTP_TOKEN`; handler compares inbound bearer value with `hmac.compare_digest`. Outbound GitHub calls delegate to effects through a public-repository filter. | Legitimate sensitive server authentication. Default plugin command is stdio, not HTTP. | Preserve behavior; document inbound vs outbound flows; existing HTTP auth/public-repo tests retained. | HTTP mode with no token is reachable by anyone on its bound interface. Operator must secure a deployment; this is not an approved remote connector or an OAuth compliance claim. |
| C. `buddie/verbatim/access.py` | Optional browser reads HTTPS proxy/executable/CA paths; `certutil` imports an explicitly supplied CA into local NSS. DOI lookup sends `VERBATIM_EMAIL` to Unpaywall. | Legitimate sensitive configuration, with incomplete prior disclosure. | Privacy documentation names recipient, local CA side effect, browser execution and opt-in methods. No ordinary browser-profile credential scraping found. | Proxy operator/TLS interception and chosen executable are trusted; source JavaScript runs in optional browser mode. |
| C. `tests/test_config.py` | Synthetic gate events, token-count classification and local launcher tests. Fixtures disable fetch/GitHub. Historical token-text match is a context token-count assertion, not an API secret. | Test fixture / apparent false positive. | Retain tests; classify them separately from runtime. | Tests remain in root plugin and scanner may still flag lexical matches. |
| C. `tests/test_loop.py` | Builds synthetic transcript calls/results and verifies gate behavior. No credential-store lookup or outbound bearer delivery found. | Test fixture / apparent false positive. | Retain tests and document classification. | Exact private scanner rule unavailable; tests are still within root scan scope. |
| C. `.claude-plugin/plugin.json` | `userConfig.github_token` is optional, sensitive and intentionally user-provided; `.mcp.json` references `${user_config.github_token}`. | Legitimate sensitive functionality, not silent credential harvesting. | Preserve schema. Regression tests verify consent flags and flow through configuration. | Host exports secrets to a process environment; compromised local code can read them. |
| C. Errors | Injected transport exception and malformed fake tokens reproduce disclosure through text/traceback. | Confirmed error-handling exposure. | Static transport errors without exception chaining; reject non-printable/non-ASCII/space-containing tokens before HTTP construction. | Arbitrary third-party library bugs, source URLs containing secrets and a compromised process are outside this guarantee. |
| D. Three unrecognized fields | Exact names not expanded. All current top-level fields checked against current official manifest reference and both official strict validation targets. | Historical schema/version warning; current listing metadata is legitimate. | Remove no supported field. Pin conclusions to CLI version in validation record. | Reviewer may use another validator revision; request exact messages if warnings remain. |
| D. Icon from another manifest | Screenshot explicitly identifies `icon` and says Directory reads it, runtime ignores it. | Expected listing metadata / no-action note. | Keep icon and valid PNG. | Image-reference heuristic may still hold it for review. |
| E. Five download/run findings | Exact five paths collapsed. Full historical search and execution classification below cover matching code, docs and fixtures. | Mixture of explicit installation docs, development CI and review-only package use; no automatic plugin download/run found. | Pin Desktop build example to the already-used MCPB tooling version. Local `run.py` startup retained. | Documentation and pinned registry tools can still be flagged. Exact five instance mapping remains open. |
| F. Hooks | `hooks/hooks.json` starts checked-in `hooks/run.sh`; Python isolated launcher runs local `run.py hook`. | Expected local execution / informational. | Preserve; clean-copy hook and existing compatibility tests. | PATH/interpreter/shell must be trustworthy; local code has user process privileges. |
| F. Local MCP stdio / local program | `.mcp.json` starts `python3 ${CLAUDE_PLUGIN_ROOT}/run.py serve`. | Expected core functionality / informational. | Preserve; discovery and tool execution without optional credentials tested. | Requires installed Python; platform-specific executable resolution remains host responsibility. |

## Already fixed after the reviewed commit

`58d5ec7` introduced stronger trust boundaries, bounded reads and redirect credential handling.
`a94df08` corrected `.mcp.json` to preserve the plugin token's own environment name, fixing the Claude Code MCP
path that previously treated a saved user option as a general environment token. Later policy, isolated collector,
public-remote filtering and regression coverage are part of the base, not credited to this PR.
The remaining inherited `BUDDIE_GITHUB_TOKEN` + environment API combination is closed here for CLI, Desktop,
hooks and optional remote deployment alike. Enterprise authentication now requires a protected policy destination;
anonymous environment-selected APIs remain available as caller-supplied evidence.

## Package inventory and limits

Generate inventories from exact Git objects, independent of checkout line endings and untracked files:

```powershell
python scripts/plugin_inventory.py --ref 3a351b4c56e05208af075378cb554c8dc8daed8b > historical-inventory.json
python scripts/plugin_inventory.py --ref HEAD > candidate-inventory.json
python scripts/plugin_inventory.py --ref HEAD --check
```

The last command intentionally exits 1 while inspection holds remain; it is not the proprietary validator.
It checks size/text/regular-file conditions, not image integrity, all filename rules or content-policy approval.
Its JSON lists every file's category, byte count, Git mode and SHA-256, with commit and aggregate counts.
Write outputs outside the plugin folder to avoid enlarging the working-tree scan surface.

| Category | Historical files | Base files | Why retained in the source repository |
|---|---:|---:|---|
| Runtime-required | 37 | 59 | Python package, launcher, plugin manifest, MCP config, hooks, skills, commands |
| Documentation | 19 | 68 | README, privacy, license/notice, install/release docs and worked examples |
| Assets | 1 | 6 | Icon, README branding and demonstrations; static, not executable |
| Tests | 41 | 77 | Regression and evaluation evidence; not needed at runtime |
| Experimental results | 128 | 138 | Reproducible scientific history; not needed at runtime |
| Development-only | 21 | 31 | CI/release scripts, other integrations and packaging metadata |
| Total | 247 | 379 | Historical total is exactly 4,844,032 bytes; base 7,413,638 bytes |

The historical total reproduces the submitted 247 files / approximately 4.8 MB, strongly confirming the root
repository was the plugin scan surface. Repository root and plugin root coincide (`source: "./"`), so that one
submission cannot distinguish a whole-repository scan from a plugin-root scan. Official docs explain that most
checks use the plugin folder, with some repository-wide checks. The runtime does not load experiment JSON.

There is no verified Directory ignore mechanism for selectively excluding these root files. `.gitignore`,
`.mcpbignore` and Python `MANIFEST.in` do not filter a Git-source Claude Code plugin. Do not add an unsupported
`files` field or `.claudeignore`, or prohibited `export-ignore` attributes and call the hold fixed. Moving the
authoritative runtime into a subfolder would change package layout and may introduce additional subfolder script
review holds; maintaining a second generated runtime tree would violate this task's distribution constraint.
This draft therefore preserves the source tree and requests manual review of the historical evidence. The
acceptance criterion of a minimized Directory runtime package remains unmet, explicitly, pending an agreed
supported source/layout strategy or reviewer acceptance. No evidence is deleted or split to evade inspection.

The **existing Desktop MCPB distribution** has a supported `.mcpbignore`: `results/` and `tests/` were already
excluded, but newer `experiments/` content leaked into its bundle. This PR excludes that development-only folder
and extends the release-candidate inventory check. It does not create a new runtime distribution. Desktop bundles
retain license, notice, privacy, README, icon, manifest, Python package and `run.py`; Claude Code retains hooks,
skills and `.mcp.json`. The Desktop exclusion does **not** clear the Directory root-source hold.

## Download/run execution classification

Reproduce historical candidate searches (all matching paths, not a guessed five-instance mapping):

```powershell
git grep -n -E 'uvx|npx|curl.*(sh|tar)|pip install' 3a351b4 -- ':!results'
git grep -n -E 'assets/icon|\.png|\.woff|\.ttf' 3a351b4 -- ':!results'
git diff 3a351b4..HEAD -- .claude-plugin/plugin.json .mcp.json manifest.json hooks buddie/effects.py buddie/remote.py buddie/verbatim/access.py
```

| Candidate class | Historical examples | When executed | Disposition |
|---|---|---|---|
| Plugin skill fallback | `skills/verbatim/SKILL.md`, pinned `pip install buddie==1.1.1` | Instructed fallback only without installed plugin; installed plugin uses local MCP | Preserve explicit user installation; current pin follows existing 2.0.1 release |
| User install examples | README, `docs/deploy.md`, `docs/release.md`, Codex config comments | User/deployment operator explicitly installs or starts an MCP client | Preserve legitimate workflows; checked-out `run.py` is inspectable alternative |
| Desktop packaging | `docs/install-claude-desktop.md`, `npx @anthropic-ai/mcpb pack` | Developer explicitly builds bundle | Pin to `@anthropic-ai/mcpb@2.1.2`; no runtime package launcher |
| CI/build tooling | `.github/workflows/ci.yml`, `release.yml`, Dockerfile | GitHub Actions or explicit image build, never plugin startup | Preserve. Existing release hardening separated candidate builds and publication |
| Registry publisher executable | Historical release workflow downloads publisher tarball then runs it | Maintainer release workflow | Already hardened in newer release workflow: download stored locally and hash verified before extraction/execution; not a hook/MCP install path |

Test files contain launcher regexes, sample commands and synthetic transcripts; these are fixtures, not instructions
for the installed plugin to download code. Optional Chromium executes source-page JavaScript for rendering; local
`certutil` configures trust. Neither downloads and runs an installer at plugin startup. Future registry installs
still depend on external package integrity and transitive dependencies and may legitimately require review.

## Validation record

Windows, PowerShell, Git Bash available; Python 3.14.6, Claude Code 2.1.310. Deterministic security tests use fake
credentials and loopback/fake transports. Dependency/tool installation is separate from fixture network access.

Validation results and exact candidate SHA: see the PR's final validation record and check runs. Baseline full suite:
`python -m pytest -q` — 1449 passed, 55 skipped. Skips cover unavailable lab/snapshot/platform fixtures, not disabled
security checks. Candidate checks include the full suite, targeted security/provenance/policy tests, copied-plugin
MCP discovery + verify execution + hook smoke, both official strict plugin checks, official MCPB manifest validation,
pack/unpack/start and file inventory, wheel/sdist build and clean wheel-install smoke. CI additionally exercises
Python 3.11–3.13, OS matrix, release-candidate installs and Docker; only completed green checks count as passed.

Commands run locally (outputs retained outside the plugin tree; CI logs/artifacts are the shareable record):

| Command / check | Observed result |
|---|---|
| `claude plugin validate --strict .` | Passed, CLI 2.1.310 |
| `claude plugin validate --strict .claude-plugin/plugin.json` | Passed, no unsupported fields reported |
| `npx --yes @anthropic-ai/mcpb@2.1.2 validate manifest.json` | Schema passed; informational icon-size recommendation |
| `python -m pytest -q tests/test_directory_credentials.py` | 27 passed, includes receipt, hook output, journal and traceback checks |
| `python -m pytest -q tests/test_plugin_inventory.py tests/test_plugin_clean_install.py tests/test_provenance_boundaries.py` plus credential tests | Independent review observed 45 passed before the final additional journal regression; targeted final journal run above also passed |
| `python -m pytest -q tests/test_workflow_pins.py tests/test_manifest.py tests/test_version.py tests/test_integrations.py tests/test_mcp_stdio.py` | 20 passed |
| `python -m build --outdir ../compliance-evidence/dist` | Built wheel and sdist, no publication |
| `python -m twine check --strict` on both built distributions | Both passed |
| Clean `python -m venv`, install local wheel / local sdist with `--no-deps`, `python scripts/smoke_install.py VENV_PYTHON 2.0.1` | Both passed: installed entrypoints, MCP discovery, offline quickstart |
| `npx --yes @anthropic-ai/mcpb@2.1.2 pack . OUTPUT`, then `unpack OUTPUT DIR`, `python scripts/smoke_mcpb.py DIR` | Passed; initialize and all five local tools |
| ZIP inventory of that MCPB | 62 files; `experiments/`, `results/`, `tests/` absent, license/notice/privacy/README/icon/manifest/launcher retained |
| PNG signature, chunk bounds/CRC and terminal IEND checks of current assets | All four PNGs structurally valid; no image asset changed |
| Exact-blob historical inventory | 247 files / 4,844,032 bytes, two inspection-size holds |
| `git diff --check` | Passed |

The new credential regressions were first run against the pre-fix behavior and failed for destination, redirect,
policy, precedence and exception-exposure reasons. The malformed-header regression also failed before the header
validation fix. Intermediate full runs started before those fixes were superseded; the final completed suite/CI
results are recorded on the PR. No failing or interrupted run is counted as a pass.
One completed candidate run caught `test_buddie_never_lets_a_child_inherit_its_standard_input`: the new inventory
helper omitted explicit child stdin. The helper now supplies empty input (or its batch request bytes); the
existing RH-1 protection test is unchanged. That failed run was 1475 passed, 56 skipped, one failed, and is
superseded only by the final full-suite/CI record, not by relabeling it a pass.

## Submission/update recommendation

**A: Keep the existing review and update detected commits after maintainer review of this draft.** Give the reviewer
the exact SHA, this matrix and inventories; explain both the fixed credential boundary and remaining large research
files. If the tracked branch is `main`, this unmerged branch does not update that submission. If it is a tag, do not
move it. After the owner separately authorizes integration and any required source update, use the existing
submission's commit-detection controls; confirm the detected SHA. No portal control is exercised by this PR.

**B: Wait for the current reviewer** while the draft is reviewed or if the portal offers no safe in-place update.
This preserves the existing review state but leaves the reviewer looking at older behavior. Avoid publication of
that older code; provide the new evidence through the existing review channel if requested.

**C: Withdraw and resubmit is not recommended and is not authorized.** It could lose review progress, encounter
duplicate/submission limits, or change queue position. There is no evidence that a new submission preserves priority
or resolves a policy hold. The owner must resolve the collapsed-instance mapping and packaging decision before
calling all acceptance criteria satisfied. Neither a green CI nor this draft promises Anthropic approval.
