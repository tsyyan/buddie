# buddie

<!-- mcp-name: io.github.tsyyan/buddie -->

[![CI](https://github.com/tsyyan/buddie/actions/workflows/ci.yml/badge.svg)](https://github.com/tsyyan/buddie/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/buddie)](https://pypi.org/project/buddie/)
[![Python](https://img.shields.io/pypi/pyversions/buddie)](https://pypi.org/project/buddie/)
[![License](https://img.shields.io/github/license/tsyyan/buddie)](LICENSE)
[![Release](https://img.shields.io/github/v/release/tsyyan/buddie)](https://github.com/tsyyan/buddie/releases)
[![MCP Registry](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fregistry.modelcontextprotocol.io%2Fv0%2Fservers%2Fio.github.tsyyan%252Fbuddie%2Fversions%2Flatest&query=%24.server.version&label=MCP%20Registry)](https://registry.modelcontextprotocol.io/v0/servers/io.github.tsyyan%2Fbuddie/versions/latest)
[![Plugin](https://img.shields.io/badge/plugin-Claude%20Code%20%C2%B7%20Codex-informational)](#install)

**buddie verifies the evidence behind AI agent reports.** When an agent quotes a page, or says a PR is merged, CI is
green or tests passed, buddie checks that claim against primary evidence: the bytes of the cited page, the
repository, the GitHub API and the session transcript. Every check ends in a receipt that anyone can re-run. In
Claude Code and Codex its hook can send an answer with a false claim back to the agent before you read it.

buddie checks claims written in forms it recognises, and only those. It does not tell whether an answer is true:
`PASS` means that the checks that ran found nothing false and nothing left open.

## Why buddie exists

An agent's account of its own work is easy to accept and expensive to re-check. An altered quote, a test run that
never happened or a PR described as merged while it is still open all read as evidence when nobody re-opens the
source. In 929 checkable quotations from published deep-research reports, **212 (22.8 %) were altered or absent from
the page they cited** ([research](#research-and-benchmarks)). In multi-agent work every hand-off restates such claims,
and a wrong one travels on.

buddie checks the account against records the agent did not write. No model takes part in the check, so the agent
being checked cannot argue its way past it.

## How a check looks

| The agent writes | buddie checks it against | Result |
|---|---|---|
| “elevated error rates on the API between 14:58 and 15:41 UTC” with a link to the status page | the visible text of a SHA-256 snapshot of **that** page | `FAIL`: not on the page; the closest passage says 14:59 |
| `⚓ pr:OWNER/REPO#12=merged@SHA` | the GitHub API: the PR's state and merge commit | holds, or `FAIL` if the PR is open or merged as another commit |
| `⚓ run:pytest -q => 41 passed` | the session transcript: a tool call that ran it and printed that | `FAIL`: the call printed `1 failed, 40 passed` |
| a quotation whose page cannot be read | nothing to compare with | `GAPS`: named as not checked |
| prose with no quotation and no anchor | nothing buddie recognises | `EMPTY`: no check took place |

| Outcome | Means | It does **not** mean |
|---|---|---|
| `PASS` | every quotation and anchor that was checked holds | that the report is true, or that unchecked claims hold |
| `FAIL` | a quotation is not in its source, or an anchor or work claim does not hold | that the rest of the report is wrong |
| `GAPS` | something could not be checked (source unreadable, GitHub offline, an anchor in another repo), and the receipt says what | a failure |
| `EMPTY` | the text had nothing buddie checks | a pass |

## What buddie verifies

| Claim in a report | Checked against | When it does not hold |
|---|---|---|
| A quotation in quotation marks with its link in the same sentence | the visible text of a SHA-256 snapshot of that link | `NOT_FOUND`, with the closest passage |
| A number or date in a sentence with a link | the visible text of that link's snapshot | a gap by default; a failure with `--numbers fail` |
| `⚓ path#sha256`, `⚓ path@commit` | the file's bytes in the repository, or the file at that commit | `BROKEN` |
| `⚓ pr:OWNER/REPO#N=merged@SHA`, `⚓ ci:OWNER/REPO@SHA=success` | the GitHub API: PR state and merge commit; every check run and status on that full commit | `BROKEN`; `UNCHECKABLE` if GitHub's answer is ambiguous or names another commit |
| `⚓ run:CMD => OUTPUT` | the Claude Code session transcript: a tool call that ran `CMD` with `OUTPUT` in **its result** | `BROKEN`, also when the agent typed the output itself (`echo "41 passed"`) |
| "step N is done", "the user agreed" (opt-in, `buddie.toml`) | the task queue at a commit, the accepted plans, the user's own messages | `BROKEN` |

The agent writes the anchors (the [skills](skills/buddie/SKILL.md) teach it how). Work stated in prose without an
anchor ("merged", "tests passed") is listed in the receipt, and a project can require anchors for it.

## What buddie does not verify

- **Whether a quotation supports the claim around it.** buddie checks that the words are on the cited page, not that
  they mean what the report says. A real quote attached to the wrong event passes.
- **Paraphrase, unquoted claims and claims without an anchor.** They are not detected by any check. Numbers are
  checked only in a sentence with a link.
- **Whether code is correct.** `ci:` says which checks passed on a commit; `run:` says a command printed something.
  A green CI on weak tests stays weak, and a command that prints a prepared file passes.
- **Pages that change.** A verdict holds for the snapshot hash and time it names. `pr:` and `ci:` describe GitHub now;
  `merged@SHA` and a `ci:` on a full SHA pin them to a commit.
- **Sessions of agents other than Claude Code** for `run:`: the transcript format is Claude Code's, undocumented and
  read as is. In Codex, Claude Desktop and over MCP, `run:` anchors are reported as unchecked.
- **Whether agents misstate less with buddie.** The gate returns false reports; whether that changes how often agents
  write them is not yet measured ([research](docs/research.md#scope-of-these-results)).

## Install

| Client | What you get | Gate |
|---|---|---|
| [Claude Code](#claude-code) | hook, MCP tools, skills, commands | **enforced**: a false claim goes back to the agent |
| [Codex](#codex) | Stop hook, MCP tools, skills | **enforced** at `Stop`; `run:` unchecked |
| [Claude Desktop](#claude-desktop) | MCP tools | advisory: you or the model decide what to do with `FAIL` |
| [Any MCP client](#mcp-server) | MCP tools over stdio | advisory |
| [CLI and CI](#cli) | `buddie verify`, exit 1 on `FAIL` | your pipeline decides |
| claude.ai, ChatGPT, the Claude API | a remote server you host ([deploy.md](docs/deploy.md)) | advisory; quotes, numbers, `pr:`/`ci:` only |

### Claude Code

```
/plugin marketplace add tsyyan/buddie
/plugin install buddie@buddie
```

The hook checks the text that leaves the session: the final answer at `Stop`, and messages sent with `SendMessage`.
On `FAIL` it returns the answer to the model with the reasons. Optional: a GitHub token for `pr:`/`ci:` anchors,
which the plugin asks for and stores as a secret. Levels, the intro mode and what the hook reads:
[docs/claude-code.md](docs/claude-code.md). Without Claude Code, `python3 run.py verify REPORT.md --repo .` runs from
a clone with nothing installed.

### Codex

```bash
codex plugin marketplace add tsyyan/buddie
```

```bash
codex plugin add buddie@buddie
```

[docs/install-codex.md](docs/install-codex.md) covers the hook, the MCP-only setup and what works there.

### Claude Desktop

Download `buddie-<version>.mcpb` from the [releases](https://github.com/tsyyan/buddie/releases) and open it
([docs/install-claude-desktop.md](docs/install-claude-desktop.md)). Each release's `SHA256SUMS` lets you check the
file.

### MCP server

For any client that starts a command (stdio), with [uv](https://docs.astral.sh/uv/):

```bash
uvx buddie serve
```

`uvx buddie@2.0.0 serve` pins a version. The tools: `verify_report`, `snap`, `source_text`, and `summary`, which only
has data with the Claude Code hook's journal.

### CLI

```bash
pip install buddie
```

`buddie verify REPORT.md` prints the blocking items and a summary line and exits 1 on `FAIL`, so it can gate a CI job
or a hand-off. `pipx install buddie` keeps it out of your environment. Python 3.11 or newer; no dependencies.

## Quick start

The examples live in the repository:

```bash
git clone https://github.com/tsyyan/buddie
```

A report with two altered quotations, checked against a stored snapshot of the page it cites (no network):

<!-- readme-example: quickstart -->
```bash
cd buddie/examples/quickstart
buddie-verbatim add https://status.example.com/incidents/42 page.html
buddie verify report.md --no-fetch
```

```
BLOCK quote L3.1 not found in https://status.example.com/incidents/42: “elevated error rates on the API between 14:58 and 15:41 UTC” (closest 0.98: “elevated error rates on the API between 14:59 and 15:41 UTC”)
BLOCK quote L7.1 not found in https://status.example.com/incidents/42: “the root cause was a misconfigured load balancer” (closest 0.50: “. The rest of the article discusses unrelated bac”)
buddie FAIL: quotes 1/3 found, 2 not found
```

A claim about work, checked against a session transcript:

<!-- readme-example: work -->
```bash
cd buddie/examples/work
buddie verify report.md --transcript session.jsonl --no-github
```

```
BLOCK anchor line 3 ⚓ run:pytest -q => 41 passed: output has no '41 passed'; it ends: ….......................................... 1 failed, 40 passed in 3.1s
note  pr:/ci:/run: anchors show what happened (PR state, checks on a commit, a command and its output), not that the code is correct
buddie FAIL: effects 0/1 hold, 1 broken
```

A wrong digit shows up as a close passage (similarity ≈ 0.98), an invented sentence as a distant one (≈ 0.5). On
your own report, `buddie verify REPORT.md` fetches the pages it cites; `--json receipt.json` writes the receipt.

## Verification modes and the protected policy

- **Levels.** Each class of claim (`quotes`, `anchors`, `final`, `prose`, `numbers`, `work`, …) is `block`, `warn`
  or `off` in the hook. A fresh install blocks only what is false; `buddie init` writes `buddie.toml` with stricter
  defaults and starts an **intro mode** in which every would-be return is only a warning
  ([claude-code.md](docs/claude-code.md)).
- **Profiles** choose which checks run: `developer` (repo, PR, CI, `run:`, work claims), `research` (quotes and
  numbers), `complete`, or `custom` (`--profile`, MCP `profile`). What a profile leaves out is not checked, and
  receipt-v1 says so ([profiles.md](docs/profiles.md)).
- **The protected policy** is a file only an administrator can write (`/etc/buddie/policy.toml`,
  `<ProgramData>\buddie\policy.toml`). Everything else buddie reads, `buddie.toml`, the hook's environment and the
  plugin's options, is writable by the agent, which runs as the same user. While the policy is in force nothing the
  agent writes can lower its floors; an unprotected or invalid file makes buddie run on its strictest limits. It
  applies to the hooks, which enforce; the CLI and MCP tools report and are not gated
  ([policy.md](docs/policy.md)).

## Receipts and reproducibility

- **Receipts** are [in-toto Statements](https://github.com/in-toto/attestation): the subject is the SHA-256 of the
  checked text, the predicate lists every verdict with the snapshot's SHA-256 and offset. **receipt-v0** is the
  default everywhere. **receipt-v1**, on request (`--receipt v1`, MCP `"receipt": "v1"`), also records what ran,
  what did not and why, the coverage (`FULL`, `PARTIAL`, `UNKNOWN`, `NONE`) and where the evidence came from, against
  a published JSON Schema ([receipts.md](docs/receipts.md)).
- **Snapshots** are stored by the SHA-256 of their bytes, so a verdict names exactly what was read.
- **Freshness**: `buddie freshness` says whether CI or repository evidence is about the revision a claim concerns
  (`CURRENT`, `STALE`, `UNKNOWN`), apart from whether it passed ([freshness.md](docs/freshness.md)).
- **Environment snapshots**: `buddie snapshot` records what buddie itself observed of the place a check ran in,
  unsigned and kept apart from what you state ([environment.md](docs/environment.md)).
- **Releases** ship the wheel, the sdist and the Desktop bundle with `release-manifest.json` and `SHA256SUMS`,
  built once from the tagged commit ([release.md](docs/release.md)).

## Integrations and distribution

| Channel | How buddie gets there | Notes |
|---|---|---|
| [PyPI](https://pypi.org/project/buddie/) | the release workflow, trusted publishing | `pip install buddie`, `uvx buddie` |
| [GitHub Releases](https://github.com/tsyyan/buddie/releases) | the release workflow | wheel, sdist, `.mcpb`, `SHA256SUMS` |
| Claude Code and Codex marketplace | this repository (`.claude-plugin/marketplace.json`) | updates with each version bump on `main` |
| [MCP Registry](https://registry.modelcontextprotocol.io/v0/servers/io.github.tsyyan%2Fbuddie/versions/latest) | the release workflow (`server.json`) | points clients at the PyPI package |
| [Glama](https://glama.ai/mcp/servers/tsyyan/buddie), [MCPRush](https://mcprush.com/tsyyan/buddie-mcp) | directories that index the repository and the package | listings, not separate builds |
| Anthropic's plugin directory | submitted, in review | not listed yet |

Which channel serves which version, how each updates and what to do after a release:
[docs/distribution.md](docs/distribution.md). Every surface, what it returns and how to troubleshoot it:
[docs/integrations.md](docs/integrations.md).

## Security and privacy

- **What leaves your machine:** the pages a report cites (to snapshot them; `BUDDIE_FETCH=0` uses stored snapshots
  only) and `api.github.com` for `pr:`/`ci:` anchors, or the GitHub Enterprise API a protected policy names
  (`BUDDIE_GITHUB=0`: none). Nothing else: no telemetry, no model
  calls, no account. buddie runs locally; the remote server is one you host.
- **Your GitHub token** is optional, taken only from the plugin's setting or `BUDDIE_GITHUB_TOKEN`, and sent only to
  the GitHub API. buddie never reads an ambient `GITHUB_TOKEN`.
- **The transcript** is read in place by the Claude Code hook to check `run:` anchors, never copied or sent; a
  plugin setting turns it off. The local journal keeps hashes and verdicts, not the text.
- **Execution:** buddie runs no code from the repository it checks. Its git ignores the repository's hooks, filters
  and config-named programs; `buddie.toml` patterns run in a separate, time-limited process
  ([security.md](docs/security.md)).
- **Trust boundary:** files and settings the agent can write cannot be trusted to configure the check; the protected
  policy is the one input it cannot change. Code already running as your user, and a replaced Python or git on
  `PATH`, are outside what buddie can defend against ([adversarial.md](docs/adversarial.md)).

Everything read, sent and kept: [PRIVACY.md](PRIVACY.md).

## Research and benchmarks

| Finding | Result | Data |
|---|---|---|
| Quotations in published deep-research reports (o3 Deep Research, Perplexity, Grok, Doubao, Claude 3.7 Sonnet) altered or absent from the cited page | **212 of 929 (22.8 %, 95 % CI 20–26 %)**; buddie flagged 207 | [E008](results/E008-drb2-fresh), [E010](results/E010-ydc-o3), [E011](results/E011-drb1-claude), [E012](results/E012-search-misses) |
| Cited numbers not in their source (DeepResearch Bench I) | 28 of 103 (27.2 %) | [E009](results/E009-drb1-numbers) |
| False `NOT_FOUND` of the quote check, out of sample | 10 of 440 (2.3 %) | [method](docs/verbatim-method.md) |
| False `NOT_FOUND` on a new genre (Search Arena answers) | **29 of 423 (6.9 %)**, mostly words the agent itself put in quotation marks | [E014](results/E014-search-arena) |
| Plugin evals: a false quote, `pr:` or `ci:` claim passed on by an orchestrator | the person got the truth in every trap run with buddie, in none without; about twice the turns | [evals](evals/README.md) |

The labellers were Claude subagents working blind to the verdicts, not humans; rules were frozen by commit before
each out-of-sample run. The ≤ 2 % false-`NOT_FOUND` target is not demonstrated for arbitrary answers. Sets, method,
limits and how to reproduce: [docs/research.md](docs/research.md), [results/](results/README.md).

## Documentation

| Topic | Page |
|---|---|
| The Claude Code plugin: levels, intro mode, what the hook reads | [claude-code.md](docs/claude-code.md) |
| Every integration, enforcement vs advice, troubleshooting | [integrations.md](docs/integrations.md) |
| Codex, Claude Desktop, a hosted server | [install-codex.md](docs/install-codex.md), [install-claude-desktop.md](docs/install-claude-desktop.md), [deploy.md](docs/deploy.md) |
| Receipts v0 and v1 | [receipts.md](docs/receipts.md) |
| Profiles and the protected policy | [profiles.md](docs/profiles.md), [policy.md](docs/policy.md) |
| Freshness and environment snapshots | [freshness.md](docs/freshness.md), [environment.md](docs/environment.md) |
| Environment variables, the quote module | [configuration.md](docs/configuration.md), [verbatim-verdicts.md](docs/verbatim-verdicts.md) |
| Security model and adversarial tests | [security.md](docs/security.md), [adversarial.md](docs/adversarial.md) |
| Releases, distribution, catalog listings | [release.md](docs/release.md), [distribution.md](docs/distribution.md), [catalogs.md](docs/catalogs.md) |
| What 2.0 guarantees and how it was tested | [release-hardening.md](docs/release-hardening.md) |
| Changes | [CHANGELOG.md](CHANGELOG.md) |

## Status

buddie 2.0.0 is prepared and not yet released; PyPI and the other channels serve 1.1.1. 2.0 keeps the 1.x interfaces
and receipt-v0 as the default; a few behaviours changed on purpose, among them `fact=` and out-of-repo file anchors,
which are no longer checked ([CHANGELOG.md](CHANGELOG.md)). The interfaces (the receipts, the CLI, the MCP tools,
`buddie.toml`) follow semantic versioning.

This repository was called `verbatim` until October 2026; `verbatim` is now buddie's quote module
(`buddie.verbatim`, command `buddie-verbatim`), and old links redirect.

## Contributing, license, citation

Contributions: [CONTRIBUTING.md](CONTRIBUTING.md). License: [Apache-2.0](LICENSE), with third-party notices in
[NOTICE](NOTICE). To cite buddie, see [CITATION.cff](CITATION.cff).
