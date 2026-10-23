# Distribution: where buddie is, what each channel serves, what to do after a release

Audited on 2026-10-23, against `main` at `b6464a7` (buddie 2.0.0 prepared, not released). Each fact is marked:
**verified** (observed here, with how), **hypothesis** (inferred, with the evidence), or **publisher-only** (visible
only to the owner's account, not checked here). Listing a server and distributing its package are different things:
of the channels below, PyPI, GitHub Releases and the repository's own marketplace carry buddie's code; the MCP
Registry points at PyPI; MCPRush and Glama are directories that describe it and print install lines.

## The matrix

| Channel | Public version now | Artifact or source | Install | Update mechanism | Publication | External review | Install tested here | After 2.0.0 is released |
|---|---|---|---|---|---|---|---|---|
| **PyPI** | 1.1.1 | wheel and sdist uploaded by `release.yml` | `pip install buddie`, `uvx buddie serve` | a new version uploaded; `pip install -U`; unpinned `uvx buddie` resolves PyPI's latest | automatic from the publish run (manual dispatch since PR #38) | none | **verified**: `uvx buddie serve` resolves 1.1.1 and lists 4 tools; `uvx buddie@2.0.0` is refused (not published); the 2.0.0 wheel and sdist pass in clean venvs | nothing beyond the publish run |
| **GitHub Releases** | v1.1.1 | the same wheel and sdist, the `.mcpb`, from 2.0 also `release-manifest.json` and `SHA256SUMS` | download | a new release | automatic from the publish run | none | **verified**: v1.1.1's three assets' digests equal PyPI's files (API) | nothing beyond the publish run |
| **Claude Code plugin marketplace** (this repository) | **2.0.0, unreleased** (`main`'s `plugin.json` since `b6464a7`) | the repository at `main`'s HEAD: `.claude-plugin/marketplace.json` `source: "./"` | `/plugin marketplace add tsyyan/buddie`, `/plugin install buddie@buddie` | `claude plugin update` (or auto-update, off by default) installs `main` when `plugin.json`'s `version` changes | every merge to `main` | none | `claude plugin validate .` passes (2.1.286); a live install was **not** run here | see "The marketplace follows main" below |
| **Anthropic plugin directory** | none listed; submission of 1.1.1 at `3a351b4` held for review | the repository at the tracked branch or tag (publisher-only which) | from claude.ai's directory, synced to Claude Code as `buddie@synced` | the directory scans new commits on its tracked ref on a schedule (or on push with the webhook), each version scanned and, when held, reviewed | manual submission, then per version | **yes**: automated validation, security scan, a person reviews a new listing; held versions wait for a reviewer | no | see "Anthropic's plugin directory" below |
| **Codex plugin marketplace** (this repository) | **2.0.0, unreleased** (`main`'s `.codex-plugin/plugin.json`) | the repository at `main` | `codex plugin marketplace add tsyyan/buddie`, `codex plugin add buddie@buddie` | Codex reads the marketplace again; the version follows `main` (**hypothesis**: same model as Claude Code, not tested) | every merge to `main` | none; the public OpenAI directory takes no plugins with hooks | no | as Claude Code |
| **Claude Desktop (`.mcpb`)** | 1.1.1 | `buddie-1.1.1.mcpb` on the GitHub Release | open the file | download the next release's file | automatic from the publish run | none (no directory listing used) | the 2.0.0 bundle validates, packs, unpacks and starts with 4 tools in the candidate run; opening it in Claude Desktop was **not** tested | nothing beyond the publish run |
| **MCP Registry** (`io.github.tsyyan/buddie`) | 1.1.1 (`isLatest`), and 1.0.0, 1.0.1, 1.1.0 | `server.json`: a pointer to the PyPI package, `uvx buddie serve` | through registry-aware clients | a new `server.json` version published by `release.yml` | automatic from the publish run, after PyPI | none (namespace proved by GitHub OIDC) | **verified** by its API (`/v0/servers/io.github.tsyyan%2Fbuddie/versions/latest`) | nothing beyond the publish run |
| **MCPRush** (`tsyyan/buddie-mcp`) | 1.1.1 | its own listing, describing the PyPI package; runs nothing of its own for buddie | `claude mcp add --scope user buddie-mcp '--' uvx buddie serve` (and per-client lines) | **hypothesis**: it follows new versions by itself (below); listing text is the publisher's in Studio | not by this repository | MCPRush reviews submissions and claims (its docs) | the `uvx buddie serve` part **verified**; `claude mcp add` not run (it writes the person's configuration) | check the Versions tab shows 2.0.0; owner reviews the listing text in Studio |
| **Glama** (`tsyyan/buddie`) | "v1.1.1" from its last inspection; README as of `0f864ec` (2026-10-22) | the GitHub repository (default branch), inspected by running the server | Glama's "Deploy Server" / "Try in Browser", or the README's commands | Glama re-indexes the repository on its own schedule (observed: about a day behind) | not by this repository | none observed | no (deploying needs a Glama account and runs buddie on Glama's infrastructure) | wait for or trigger a re-index; check the tools, env vars and README |

## The marketplace follows `main`

`.claude-plugin/marketplace.json` names the plugin at `./`, the repository itself, so Claude Code and Codex install
whatever `main` holds. PR #37 set `plugin.json` to 2.0.0 on `main`, so since `b6464a7` a person with 1.1.1 who runs
`claude plugin update` (or has auto-update on) receives 2.0.0 **before it is released**: the code is the reviewed
`main`, but it has no tag, no PyPI package and no release notes yet. (**verified**: `raw.githubusercontent.com` serves
`"version": "2.0.0"` for `main`; the update rule is the [Claude Code docs](https://code.claude.com/docs/en/plugins/publish.md)'.)

Options, for the owner to choose; this PR changes none of them:

1. Accept it: `main` is the plugin channel, and each version bump on `main` is a plugin release. Release 2.0.0 soon
   after this PR so the channels agree again.
2. Pin the marketplace entry to a release: a `github` source with `ref` set to the release tag (the
   [marketplace reference](https://code.claude.com/docs/en/plugins/marketplace-reference.md) allows `ref` and `sha`),
   bumped as part of each release. Not tested here with Codex, which reads the same file.
3. Bump `plugin.json`'s version only in the release commit, in future cycles.

## MCPRush

Listing: <https://mcprush.com/tsyyan/buddie-mcp>, read on 2026-10-23 in a browser (the site refuses plain HTTP clients
with a JavaScript challenge).

| Question | Finding |
|---|---|
| How the listing was created | **publisher-only**. The listing's description is `server.json`'s word for word and its two variables are `server.json`'s, and its 1.0.0 row says it "was on when mcprush began following its releases", undated: **hypothesis**, it was created from the MCP Registry entry or the PyPI project and is not a submission made from Studio. MCPRush's docs say listings are created in a Studio wizard (no publisher CLI) and that an existing listing can be *claimed* (GitHub sign-in, a file in the repository, a token in a package release, or a domain). Whether this one is claimed is publisher-only. |
| Do versions follow PyPI by themselves | **hypothesis: yes, with gaps.** Its Versions tab lists 1.0.0, 1.0.1 and 1.1.1, dated as on PyPI and the registry, but not 1.1.0, which was replaced by 1.1.1 about an hour later: consistent with a periodic poll. MCPRush documents reading `pypi.org/pypi/<project>/json` (name, summary, keywords, latest version) for PyPI listings. Not observed over a release: check after 2.0.0. |
| Is Studio needed | For the listing's text, tool access labels, categories and the badge: yes (Studio → Servers → Manage). For a new version to appear: apparently not (above). |
| Release history for a local stdio server | The install line names no version, so it installs whatever `uvx` resolves ("Always latest"); the Versions tab can pin one, which rewrites the line to name it. MCPRush hosts nothing for buddie ("this marketplace is not in the path"). |
| Do the commands work | **verified** for `uvx buddie serve`: 1.1.1, four tools. The `claude mcp add` line is Claude Code's own command, not run here. |
| Does `uvx buddie serve` resolve the intended version | It resolves PyPI's latest at the time uv resolves it. uv documents `uvx buddie@latest` to ask for the latest and `uvx buddie@2.0.0` to pin; whether a cached environment from 1.1.1 is reused after 2.0.0 is out could not be tested before a newer version exists. |
| Distribution or configuration | **Configuration.** For a local server MCPRush prints a client entry that starts the publisher's PyPI package; the bytes come from PyPI. Its gateway and hosting apply to listings that use them, not this one. |
| Accuracy | Tools: the four names are right. It labels all four **read**; `snap` and `verify_report` also fetch URLs and write snapshots, so `network` and `write` would be accurate. `summary` is listed without saying it needs the Claude Code hook's journal. Its "Trust score 94" scan read the package's source but "no tools were enumerated". Privacy and license are not shown on the pages read. |
| Can it be improved | In Studio (owner): declare each tool's access (`publish-08`: read, write or network), a description that says what buddie does not verify, and the supported clients. Its README badge shows a grade, downloads and access level, so this README links to the listing instead of embedding it. |

## Glama

Listing: <https://glama.ai/mcp/servers/tsyyan/buddie>, read on 2026-10-23 (HTML and in a browser).

| Question | Finding |
|---|---|
| Source and indexing | **verified**: it shows the repository's file tree and README from GitHub, linked to `tsyyan/buddie` `main`. The README it shows is the one at `0f864ec` (2026-10-22: it has "Receipt v1", not "Evidence freshness" or the protected policy), while `main` moved four times on 2026-10-23: it re-indexes on its own schedule, about a day behind. It does not read PyPI or releases for content. |
| Versions and tools | "Tool Schema Changelog … observed during successful MCP inspections": v1.0.0 (2026-10-19, 4 tools) and v1.1.1 (2026-10-23). Glama runs the server to list its tools. The four tools match `buddie serve` (`verify_report`, `snap`, `source_text`, `summary`). |
| Stale or contradictory content | **verified**: its *Schema* tab lists a `GITHUB_TOKEN` variable as "Alternative GitHub API token", which buddie never reads. It came from a sentence in the old README ("with `BUDDIE_GITHUB_TOKEN` or `GITHUB_TOKEN` if set"), removed in PR #38. It says the server "publishes no instructions"; `initialize` does return them (`buddie/mcp.py`), so its last inspection predates that record or did not keep it. Its "How do I use" suggests checking "test claims against the transcript" in a Glama deployment, where there is no Claude Code transcript (`run:` is unchecked there). |
| Tool descriptions | Its quality score (TDQS) marks `snap` and `source_text` down for parameters without descriptions; PR #38 adds a description to each of their parameters. |
| Deploy and browser playground | Glama's "Deploy Server" runs buddie in Glama's infrastructure ("Hybrid"). There it has no repository and no transcript: quotes, numbers and `pr:`/`ci:` are checked, repo anchors and `run:` are not, and fetches go out from Glama's network. Not tried here (it needs an account and starts a deployment). |
| Installation instructions | Glama's own route is its deployment; the README's commands are shown as written. Nothing found that would leak a token. |
| `glama.json` | Its schema is **verified** (`https://glama.ai/mcp/schemas/server.json`): one required field, `maintainers`, "GitHub usernames that have permission to maintain the server". What Glama does with it beyond that was not verified, so this PR does not add one. If the owner wants the Admin tab, add `{"$schema": "https://glama.ai/mcp/schemas/server.json", "maintainers": ["tsyyan"]}` at the repository root, or claim the listing in Glama. |
| Badges | Glama's badge shows a rating ("rated A"): not used in this README. |
| Refresh after 2.0.0 | Merge PR #38 (the README Glama shows), release, then check after a day that the README, the tool list and the Schema tab's variables match `main`; if not, re-index from the listing's Admin tab (publisher-only). |

## Anthropic's plugin directory

Submission "buddie: claim checker", version 1.1.1, commit `3a351b4` (the 1.1.1 release merge on `main`, tagged
`v1.1.1`). Portal status, as reported by the owner: security scan completed, in review, held for content policy
review. The portal itself is **publisher-only**; this section reads the plugin's files against the
[pre-submission checklist](https://claude.com/docs/plugins/pre-submission-checklist) and the
[submission guide](https://claude.com/docs/plugins/submit).

**What the plugin ships.** The plugin is the repository root, so the directory scans every file in it:

| | `3a351b4` (submitted) | `main` (2.0.0) | Checklist rule |
|---|---|---|---|
| files | 247 | 298 (with this PR: 307) | ≤ 512, else held |
| files over 256 KiB (not image or font) | 2: `results/E008-drb2-fresh/results.json`, `sample_blind.json` | 3: those two and `tests/data/gate_golden.json` (771 KB) | held: "Files or downloads the validator couldn't inspect" |
| binary files | `assets/icon.png` (a complete PNG) | the same | PNG is allowed |
| research data | `results/`, 128 files, 4.0 MB | the same | — |

| Warning | Assessment | Action |
|---|---|---|
| Large research JSON files | **Real, harmless.** Research data the plugin never reads; the rule holds any non-image over 256 KiB for a reviewer. Since 2.0 a test fixture adds a third. | Only removable from the scanned folder (below). Not an issue in the code. |
| Potentially executable image or font | **Likely harmless, partly actionable.** The only binary is `assets/icon.png`. The checklist holds a plugin whose scripts refer to a bundled image: `scripts/make_icon.py` wrote that path. PR #38 makes the script take its output path as an argument instead. | Done in this PR; the scan decides. |
| Credential access | **Partly actionable.** The checklist holds a plugin that reads a credential already in the environment "such as `$GITHUB_TOKEN`… even in a README example". At `3a351b4` the README listed `GITHUB_TOKEN` as a token buddie uses, although 1.1 had stopped reading it; `main` still said "with `BUDDIE_GITHUB_TOKEN` or `GITHUB_TOKEN` if set" in one place, removed in PR #38. The plugin takes its token through `userConfig` with `sensitive: true` and passes it to the MCP server as `${user_config.github_token}` (`.mcp.json`) and to hooks as `CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN`, which is the supported way. The code also accepts `BUDDIE_GITHUB_TOKEN` from the environment for the CLI and other clients; a scan may still name it. | README fixed; the rest is as the checklist asks. |
| Unrecognized manifest fields | **Harmless.** `icon`, `documentationUrl`, `supportUrl` and `privacyPolicyUrl` are directory-listing fields: the [plugins reference](https://code.claude.com/docs/en/plugins-reference.md) says Claude Code ignores them at load time and the directory reads them; validators before Claude Code 2.1.281 reported them as unknown. `displayName` and `userConfig` are in the schema; every `userConfig` key used (`type`, `title`, `description`, `sensitive`, `required`, `default`) is allowed. `claude plugin validate` 2.1.286 passes with no warning. | None. |
| Icon ignored by the Claude Code runtime | **Expected.** The same reference: "Icon for the plugin's listing in Anthropic's directory. Claude Code doesn't read it." | None. |

**Excluding research without deleting it.** The directory scans only the plugin folder, and a submission names
that folder ("plugin path"). The ways to keep `results/` and the large test fixture out of the scanned plugin:

1. A plugin folder of its own (for example `plugin/`) holding `.claude-plugin/`, `hooks/`, `skills/`, `commands/`,
   `run.py` and a copy of the `buddie` package, kept in sync by a script or the release workflow. The marketplace
   entry then points at that folder. This is a restructuring with its own risks (two copies of the code), and a
   different plugin path is a different submission ("one submission for each repository and folder").
2. A generated distribution branch or tag (the release's plugin files only) that the submission tracks.
3. Leave it: a hold is not a rejection, and the reviewer can see what the files are.

This PR does none of these; option 3 stands until the owner decides.

**How the submission gets new versions.** The directory scans the newest commit of its tracked branch or tag on a
schedule, or on push with the webhook, or on *Check for new commits*. A tracked branch takes new commits as they
merge; a tracked tag stays on its commit until the tag is changed. Which one this submission tracks is
publisher-only. A version that was not rejected is fixed by pushing to the tracked ref and checking for new commits;
only a rejected submission is resubmitted. Each new version is scanned again and can be held again.

**Safest action after 2.0.0 is released** (owner, in the portal; nothing here does it):

1. Open the submission and read why it is held, and any requested changes.
2. If it tracks `main` or a branch, let the directory pick up the release commit (or *Check for new commits*); if it
   tracks the `v1.1.1` tag, change the tracked tag to `v2.0.0`.
3. Do not withdraw it: a held version is waiting for a person, not refused, and the submission continues with new
   versions. A withdrawn submission still counts toward the organization's daily submission limit.
4. In the data-handling step, point to `PRIVACY.md` and the README's "Security and privacy".

No change here guarantees approval: the reviewer applies the Software Directory Policy, which the scan does not
cover.

## After the 2.0.0 release

| Where | Who | What |
|---|---|---|
| PyPI, GitHub Releases, MCP Registry, `.mcpb` | the publish run | done by `release.yml` ([release.md](release.md)) |
| Claude Code and Codex marketplace | nobody | already on 2.0.0 (see above) |
| Anthropic's directory | owner, portal | the steps above |
| MCPRush | owner, Studio | check the Versions tab shows 2.0.0; declare tool access; review the text |
| Glama | owner | check the re-indexed README, tools and variables; re-index from Admin if stale |
| MCP clients pinned to `uvx buddie@1.x` | their users | nothing buddie can change |
