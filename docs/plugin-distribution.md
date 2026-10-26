# The compact Claude Code plugin and `plugin-stable`

One source, `main`, and one release candidate. The candidate is built from one commit and holds:

- the wheel and the sdist (PyPI);
- the Claude Desktop bundle (MCPB);
- the compact Claude Code plugin.

The compact plugin is derived from that commit each time it is built
([`scripts/plugin_package.py`](../scripts/plugin_package.py)), and nobody edits it. Released versions of it are
promoted to the distribution branch `plugin-stable` (docs/release.md, section 3). This document records what the
package holds, why, and what it changes and does not change. That includes the Claude Directory review: nothing here
claims Directory approval or full compliance.

## What the package holds

**Selection.** An explicit allowlist in `plugin_package.py` (`EXACT`, `DIRECTORIES`):

- `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.mcp.json`, `run.py`;
- `hooks/hooks.json`, `hooks/run.sh`;
- `buddie/*.py`, `buddie/verbatim/*.py`, `skills/*/SKILL.md`, `commands/*.md`;
- `assets/icon.png`, `README.md`, `LICENSE`, `NOTICE`, `PRIVACY.md`.

**Files are read as Git blobs of the exact commit**, never from the working tree.

**Every tracked file under a runtime root must match a rule, or the build fails.** The roots are `buddie/`,
`skills/`, `commands/`, `hooks/` and `.claude-plugin/`. A new file there is reviewed, not silently shipped or dropped.

**The build is refused on any of these:**

- missing required files;
- symlinks and submodules (Git modes other than 100644 or 100755);
- text over 256 KiB, or that is not UTF-8 or contains NUL;
- an icon that is not a PNG or is over 1 MiB;
- non-plain or case-colliding paths;
- more than 128 files or 2 MiB in total;
- a version disagreement;
- a manifest or launcher reference to a file the package lacks.

**Determinism.** ZIP entries are in path order and STORED; the timestamp is 1980-01-01 and every mode is 0644; there
are no directory entries, extra fields or comment. STORED, because deflate output depends on the zlib build. The
bytes depend only on the selected files. The manifest (`plugin-manifest.json`) records:

- the source commit and tree;
- the version;
- the builder revision and selection;
- every file's size and SHA-256;
- the package's size and SHA-256.

`verify --ref` rebuilds and compares the bytes.

### Inventory before and after (this branch, commit of the PR head)

The categories are those of [#61's inventory](../scripts/plugin_inventory.py): every committed file, by exact
blob.

| | Repository root (today's Directory source layout) | Compact package |
|---|---:|---:|
| Files | 386 | **66** |
| Bytes | 7,513,921 | **897,209** |
| Runtime-required (#61's category) | 60 files / 860,385 B | 60 files / 860,385 B: all of them, byte-identical |
| Documentation | 69 / 796,646 B | 4 / 33,186 B (README, LICENSE, NOTICE, PRIVACY) |
| Assets | 6 / 66,617 B | 1 / 3,086 B (the icon; the README's branding images stay in the repository) |
| Tests | 81 / 1,616,778 B | 0 |
| Experimental results | 138 / 4,096,410 B | 0 |
| Development-only | 32 / 77,085 B | 1 / 552 B (`marketplace.json`, which makes the package root installable) |
| #61's inspection holds (non-image over 256 KiB) | 3: `results/E008-drb2-fresh/results.json`, `.../sample_blind.json`, `tests/data/gate_golden.json` | **0** |

The README links to images that the package does not carry. They display on GitHub, not inside the package.

## Verification in the release candidate (every pull request)

[`release-candidate.yml`](../.github/workflows/release-candidate.yml) builds the plugin from `$GITHUB_SHA` and then:

1. **Rebuild:** `verify --ref` (same bytes);
2. **Validation**, with the pinned CLI `@anthropic-ai/claude-code@2.1.310` (as for MCPB, a pinned npm tool):
   - `claude plugin validate --strict` on the tree and on its `plugin.json`;
   - `--strict --profile directory` (the Directory's published subset of checks; the CLI says the Directory also
     runs a safety scan and a policy review that it does not);
3. **Clean install:** `claude plugin marketplace add` plus `claude plugin install buddie@buddie` into an isolated
   `CLAUDE_CONFIG_DIR` (no sign-in, nothing of the runner's);
4. **Smoke test of the installed copy** ([`scripts/smoke_plugin.py`](../scripts/smoke_plugin.py)):
   - exactly the manifest's files, byte for byte, and no development or research file;
   - MCP initialize, tools/list (the commit's tool list) and a `verify_report` call, from a clean environment and a
     directory outside the plugin, with no pip install;
   - the same with a well-formed and a malformed optional GitHub token, which appears in no output;
   - the SessionStart and Stop hook commands as `hooks.json` declares them;
   - the `userConfig` token still optional and sensitive.

[`release_manifest.py`](../scripts/release_manifest.py) records the ZIP and its manifest next to the wheel, the sdist
and the MCPB, with the same exact-file checks (missing, unexpected, changed). It also binds the two: the plugin
manifest must name the candidate's commit and version and the recorded ZIP's size and SHA-256, so a swapped ZIP with
a rewritten record is refused. CI publishes nothing.

**Operating systems.** [`tests/test_plugin_package.py`](../tests/test_plugin_package.py) runs in the Linux, macOS and
Windows jobs. It covers:

- selection and refusals;
- determinism (same commit; another repository with the same files);
- tampering;
- the unpacked package as a plugin: MCP and token on every OS, hooks where `sh` exists, which includes Windows with
  Git Bash.

Its synthetic sources are made with `git fast-import`, so modes and bytes do not depend on the file system.

## Security review

**`plugin_package.py`**

- **Input:** it reads Git objects only.
- **Path safety:** paths must be plain relative POSIX names (no `..`, no absolute paths, no backslashes). `unpack`
  writes only verified entries into an empty directory, so no zip-slip.
- **Integrity:** symlink and mode bits in a ZIP are refused on read.
- **Isolation:** nothing executes package content.

**`smoke_plugin.py`**

- **What it runs:** the package's own launcher, with a minimal environment (`PATH` and OS basics), GitHub and
  fetching off, and fake tokens.
- **What it checks:** the token strings never appear in output.

**`plugin_promote.py`**

- **Pushes:** one plain push of one commit to `refs/heads/plugin-stable`, with no force and no `+` refspec (a test
  pins it).
- **Trust:** the trailers it trusts are on commits of that branch. Protect the branch so that only the release
  workflow can push (see the deployment plan below).

**`release.yml` `plugin-stable` job**

- **Permissions:** `contents: write` only here. It needs `authorize` (the `pypi` environment's reviewers), the tag on
  `main`, and the candidate run of this commit and workflow.
- **Inputs:** they reach scripts through `env`, never interpolated into a shell line. The confirmation text is
  separate from publishing's.
- **Supply chain:** the pinned npm CLI is a dependency, like `mcpb@2.1.2`.

**PR #61's credential boundaries** are untouched and travel unchanged into the package:

- tokens only to GitHub.com or a protected-policy HTTPS API;
- cross-origin redirect refusal;
- malformed-token rejection before headers;
- static transport errors.

#61's credential suite runs on this branch.

## Compatibility with every existing channel

| Channel | Change |
|---|---|
| PyPI (wheel, sdist) | none. Same build; `pypi` checks still compare exactly the wheel and the sdist. |
| Claude Desktop MCPB | none. Same `.mcpbignore` (from #61) and checks. |
| MCP Registry | none |
| GitHub Release | from the next release, two more assets: `buddie-plugin-X.Y.Z.zip` and `plugin-manifest.json`. The documented release check moves them into `plugin/`. Releases already published are only re-checked, never changed. |
| Claude Code from the repository root (`/plugin marketplace add tsyyan/buddie`) | none: the root stays a working plugin and marketplace. The full research history is still in it. |
| Claude Code from `plugin-stable` | new, after the first authorized promotion. The branch root is a marketplace with one plugin at `./`. |
| Codex plugin, `uvx buddie serve`, Docker, remote server | none |
| `release.yml` | new choice `only: plugin-stable` (never in `all`), new input `create_branch`. Existing stages, permissions and their tests are unchanged. |
| `release_publish.authorize` | stage-specific confirmation. `publish buddie X.Y.Z` is unchanged for every existing stage. |

## Directory compliance reconciliation (with PR #61)

**Verified here, offline and in CI:**

- the compact package carries none of #61's three inspection holds;
- it carries none of its test fixtures flagged by lexical credential matches (`tests/test_config.py`,
  `tests/test_loop.py`);
- it carries no CI workflow, Dockerfile, release document, install example or `scripts/make_icon.py`;
- it passes `plugin validate --strict` and the Directory profile subset.

Per #61's finding table, as far as the package's content goes:

| #61 finding | With the compact package as the source |
|---|---|
| A. Uninspectable research JSON, and `tests/data/gate_golden.json` over 256 KiB | not in the package |
| B. Three image/font references | the icon and both manifest references remain (legitimate). `scripts/make_icon.py` is gone. The README's image links remain as text. The exact three instances are still unmapped. |
| C. `buddie/effects.py`, `remote.py`, `verbatim/access.py` | **remain**. They are runtime code, with #61's fixes. `remote.py` is the optional HTTP server, kept so the package is the real `buddie` package. |
| C. `tests/test_config.py`, `tests/test_loop.py` (fixtures) | not in the package |
| C. `plugin.json` userConfig, error handling | remain, as fixed in #61 |
| D. Unrecognized fields; icon from another manifest | unchanged. `plugin.json` is the same file. `manifest.json` (Desktop) is not in the package. |
| E. Five download/run findings | the CI, Dockerfile, release docs, Codex config and install examples are gone. The skills' explicit `pip install` fallback and the README's install section remain. The exact five instances are still unmapped. |
| F. Hooks, local MCP stdio | remain: expected, core functionality |

**Assumptions about the Directory portal, not verified:**

- that a submission can track a branch (`plugin-stable`) rather than a tag at the repository root;
- whether it scans the plugin folder only or the whole repository;
- whether a branch whose history holds only package commits avoids repository-wide checks;
- whether the reviewer accepts a distribution branch at all.

The existing `v1.1.1` submission is not modified, withdrawn or resubmitted here, and no tag is created or moved.
Whether to point a submission at `plugin-stable` is a separate decision for the owner, after the branch exists and
its exact commit has been validated.

## Deployment plan for `plugin-stable`

1. **Merge.** Merge #61, then this PR, each after review (not done here).
2. **Protect the branch.** Before the first promotion, the owner adds a ruleset for `plugin-stable`:
   - no force pushes, no deletion;
   - pushes only by GitHub Actions (the release workflow).

   This is the repository owner's setting, not testable here.
3. **Release.** Cut the next release as usual (docs/release.md, "Cutting a release"). The candidate now includes the
   plugin.
4. **Publish.** Run the publishing stages as before.
5. **Promote.** Run `release.yml` by hand on the tag with:
   - `candidate`: the tag's candidate run;
   - `only`: `plugin-stable`;
   - `confirm`: `promote buddie X.Y.Z to plugin-stable`;
   - `create_branch`: `true`, the first time only.

   The run summary records the promotion: branch commit, parent, tree, source commit, package and manifest SHA-256.
6. **Check.** Install it yourself:
   - add the branch as a marketplace in a test profile, by the branch reference form the Claude Code documentation
     gives for Git marketplaces (not verified here), or from `git archive` of the branch head, as the job does;
   - compare `git ls-tree` of the branch head with the release's `plugin-manifest.json`.
7. **Directory, only with separate authorization:** use the existing submission's controls to point at
   `plugin-stable` and confirm the detected commit, or keep the current review as it is.

Retry, rollback and refusals: docs/release.md, section 3.
