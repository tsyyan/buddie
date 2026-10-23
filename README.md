# buddie

<!-- mcp-name: io.github.tsyyan/buddie -->

[![CI](https://github.com/tsyyan/buddie/actions/workflows/ci.yml/badge.svg)](https://github.com/tsyyan/buddie/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/buddie)](https://pypi.org/project/buddie/)
[![Python](https://img.shields.io/pypi/pyversions/buddie)](https://pypi.org/project/buddie/)
[![License](https://img.shields.io/github/license/tsyyan/buddie)](LICENSE)
[![Release](https://img.shields.io/github/v/release/tsyyan/buddie)](https://github.com/tsyyan/buddie/releases)
[![MCP Registry](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fregistry.modelcontextprotocol.io%2Fv0%2Fservers%2Fio.github.tsyyan%252Fbuddie%2Fversions%2Flatest&query=%24.server.version&label=MCP%20Registry)](https://registry.modelcontextprotocol.io/v0/servers/io.github.tsyyan%2Fbuddie/versions/latest)

**buddie verifies the evidence behind AI agent reports.**

When an agent writes "the page says …", "the PR is merged", "CI is green" or "tests passed", buddie checks that claim
against primary evidence: the cited page, the repository's files and git history, GitHub's record of the PR and its
checks, and the session's record of what ran. No language model takes part in the check, so the agent cannot talk it
into a different verdict. Every check ends in a receipt that records what was checked against which evidence.

In Claude Code and Codex, buddie can check an answer before you see it and send it back to the agent when a claim
does not hold. Everywhere else it is a tool that you or the agent call.

## Release status

| | Version |
|---|---|
| Latest release: PyPI, GitHub Releases, the Desktop bundle, the MCP Registry | **1.1.1** |
| Described in this README | **2.0.0**, prepared, not yet released |

Features marked *(2.0)* are not in 1.1.1. Until 2.0.0 is released they come only from this repository's source: the
plugin marketplace installs its default branch, and `pip install git+https://github.com/tsyyan/buddie` installs that
branch as a package. Each release updates this section ([docs/release.md](docs/release.md)).

## See it work

A report quotes a status page wrongly twice. buddie checks each quotation against a snapshot of the page it links to
(from a clone of this repository, no network):

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

The exit code is 1. A wrong digit shows up as a close passage (0.98), an invented sentence as a distant one (0.50).
With `--json receipt.json` the same check is also written as a receipt: an
[in-toto Statement](https://github.com/in-toto/attestation) whose predicate gives each verdict and the snapshot it was
read from. An excerpt:

<!-- readme-receipt: quickstart -->
```json
{
  "predicateType": "https://github.com/tsyyan/buddie#receipt-v0",
  "predicate": {
    "outcome": "FAIL",
    "line": "buddie FAIL: quotes 1/3 found, 2 not found",
    "quotes": [
      {
        "id": "L3.1",
        "verdict": "NOT_FOUND",
        "url": "https://status.example.com/incidents/42",
        "sha256": "cc696ce5cfcc04abf2aeef81f82f0b5a668dd0953f9c9f36c02748ed0fdeb2b1",
        "closest": {"ratio": 0.983, "text": "elevated error rates on the API between 14:59 and 15:41 UTC"}
      }
    ]
  }
}
```

A claim about work, checked against the session's own record of the command:

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

Both examples print exactly this with 1.1.1 and with 2.0.0, and `tests/test_readme.py` runs them on Linux, macOS and
Windows.

**Checking again.** A receipt names the evidence a verdict rests on: a snapshot's SHA-256, a commit, a check run, the
time. Running the check again reproduces the verdict only while that evidence is unchanged and still at hand. A stored
snapshot can be re-read for as long as you keep it, but a live page, a PR's state or a branch can change, and a session
transcript exists only on the machine that wrote it. The receipt does not contain the page.

## What buddie checks

| The report says | Checked against |
|---|---|
| a quotation, in quotation marks, with its link | the visible text of a SHA-256 snapshot of **that** link |
| a number in a sentence with a link | the same snapshot |
| `⚓ path#sha256` or `⚓ path@commit` | the file in your repository, or at that commit |
| `⚓ pr:OWNER/REPO#N=merged@SHA` | GitHub: the PR's state and merge commit |
| `⚓ ci:OWNER/REPO@SHA=success` | GitHub: every check run and status on that commit |
| `⚓ run:CMD => OUTPUT` | the Claude Code transcript: a call that ran `CMD` and printed `OUTPUT` |
| "step 3 is done", "the user agreed" (opt-in) | the project's task queue, accepted plans and the user's own messages |

The agent writes the anchors, and buddie's [skill](skills/buddie/SKILL.md) teaches it how. Every result is one of four
outcomes:

| Outcome | Means | Is not |
|---|---|---|
| `PASS` | everything that was checked holds | proof that the report is true |
| `FAIL` | a quotation is not in its source, or an anchor does not hold | a judgement on the rest |
| `GAPS` | something could not be checked, and the receipt names it | a pass |
| `EMPTY` | there was nothing buddie checks | a pass |

A claim buddie does not recognise (paraphrase, work stated without an anchor) is not checked at all. Lines that state
work in prose are listed in the receipt as such, so you can see what went unchecked.

## What you get

| Capability | What it does for you |
|---|---|
| Quotation checks | catch a quote that was altered, invented or taken from another page, with the closest real passage |
| Source snapshots | store each cited page by the SHA-256 of its bytes, so a verdict names exactly what was read |
| Repository anchors | tie "this file" and "that commit" to the bytes in your checkout |
| PR and CI checks | confirm merged or open, passing or failing, on the commit the claim names |
| Execution evidence | confirms that the session transcript shows a command printing what the report says (Claude Code) |
| Typed findings | each blocking item says what failed and why, so the agent can fix or disclose it |
| The gate | returns an answer with a false claim to the agent before you read it, with the reasons (Claude Code, Codex) |
| Verification profiles *(2.0)* | run only the checks you need: `developer`, `research`, `complete` or `custom` |
| Protected policy *(2.0)* | an administrator's file that settings the agent can write cannot weaken |
| Receipt v1 *(2.0)* | adds what ran, what did not and why, coverage and provenance; v0 stays the default |
| Evidence freshness *(2.0)* | says whether CI or repository evidence is about the revision a claim concerns |
| Environment snapshots *(2.0)* | record what buddie itself observed of where a check ran |
| Hardened execution *(2.0)* | no repository code runs; git ignores repository hooks and filters; patterns are time-limited |

<details>
<summary>Which interface has what</summary>

| | Claude Code plugin | Codex plugin | Desktop, stdio MCP | CLI | Remote server |
|---|---|---|---|---|---|
| quotes, numbers | yes | yes | yes | yes | yes |
| `path#`, `path@` | yes | yes, given `repos` | yes, given `repos` | yes | no |
| `pr:`, `ci:` | yes | yes | yes | yes | public repos |
| `run:` | yes | unchecked | unchecked | with `--transcript` | no |
| gate before you read | yes | at `Stop` | no | exit code | no |
| receipt v1 *(2.0)* | MCP tool | MCP tool | yes | `--receipt v1` | no (v0) |
| protected policy *(2.0)* | enforced | enforced | not a gate | not a gate | not a gate |

Every surface in detail: [docs/integrations.md](docs/integrations.md).

</details>

## Install

| Where you work | Install | You get | Gate |
|---|---|---|---|
| [Claude Code](#claude-code) | plugin, from this repository's marketplace | hook, MCP tools, skills, commands | **yes** |
| [Codex](#codex) | plugin, from this repository's marketplace | Stop hook, MCP tools, skills | **yes**, at `Stop` |
| [Claude Desktop](#claude-desktop) | the `.mcpb` bundle | MCP tools | no |
| [Any MCP client](#any-mcp-client) | `uvx buddie serve` | MCP tools over stdio | no |
| [Terminal or CI](#terminal-or-ci) | `pip install buddie` | `buddie verify` | exit code |
| [From source](#from-source) | a clone | all of the above, 2.0 | as installed |

buddie needs Python 3.11 or newer and has no dependencies.

### Claude Code

```
/plugin marketplace add tsyyan/buddie
/plugin install buddie@buddie
```

From a shell: `claude plugin marketplace add tsyyan/buddie`, then `claude plugin install buddie@buddie`. The plugin
installs this repository's `main` (2.0.0 today). Its hook checks the final answer at `Stop` and messages sent with
`SendMessage`; on `FAIL` the answer goes back to the agent with the reasons. Optional: a GitHub token for `pr:` and
`ci:`, which the plugin asks for and keeps as a secret. Levels, the intro mode and what the hook reads:
[docs/claude-code.md](docs/claude-code.md). buddie is not listed in Anthropic's plugin directory yet: a submission is
in review.

### Codex

```bash
codex plugin marketplace add tsyyan/buddie
```

```bash
codex plugin add buddie@buddie
```

Codex runs plugin hooks after you review them in `/hooks`. `run:` anchors stay unchecked there, because Codex's
session log is not Claude Code's transcript. Setup and the MCP-only route: [docs/install-codex.md](docs/install-codex.md).

### Claude Desktop

Download `buddie-<version>.mcpb` from the [releases](https://github.com/tsyyan/buddie/releases) (1.1.1 today) and open
it. Desktop has no hooks, so Claude has to call `verify_report` itself, and `run:` is unchecked.
[docs/install-claude-desktop.md](docs/install-claude-desktop.md).

### Any MCP client

For a client that starts a command (stdio), with [uv](https://docs.astral.sh/uv/):

```bash
uvx buddie serve
```

This runs the latest release on PyPI (1.1.1 today); `uvx buddie@2.0.0 serve` will pin 2.0.0 once it is released. A
remote server you host for claude.ai or ChatGPT: [docs/deploy.md](docs/deploy.md).

### Terminal or CI

```bash
pip install buddie
```

`buddie verify REPORT.md` fetches the pages the report cites, checks it, prints the blocking items and a summary, and
exits 0 when nothing failed (`PASS`, `GAPS` or `EMPTY`), 1 on `FAIL` and 2 when the input cannot be used. A CI step
that needs `PASS` should read the receipt's outcome, not only the exit code. `--json FILE` writes the receipt;
`--receipt v1` *(2.0)* writes receipt v1.

### From source

```bash
git clone https://github.com/tsyyan/buddie
```

`python3 run.py verify REPORT.md --repo .` runs from the clone with nothing installed, and `pip install .` installs
2.0.0. Contributing: [CONTRIBUTING.md](CONTRIBUTING.md).

## MCP tools

| Tool | Does |
|---|---|
| `verify_report` | checks a report (text or file) and returns its receipt: v0, or v1 on request *(2.0)* |
| `snap` | snapshots URLs into the store, so quotes can be taken from and checked against the same bytes |
| `source_text` | the visible text of a snapshot, or the matches of a pattern with context: copy quotes from here |
| `summary` | Claude Code only: the code-built summary of finished subagents, from the hook's journal |

Every stdio server (the Claude Code and Codex plugins, Desktop, `uvx buddie serve`) lists all four; `summary` has data
only with the Claude Code hook. The remote server has the first three. **The MCP tools and the CLI advise**: they
report, and you or the agent decide what to do with `FAIL`. **The hooks enforce**: they check the answer itself and
hold it back. The protected policy applies to the hooks only.

## Enforcement and the protected policy

The hook checks the answer the agent hands you. What it blocks is set per class of claim (`block`, `warn` or `off`):

- **A fresh install** blocks only what is false: a quotation not on its page, an anchor that does not hold.
- **`buddie init`** writes `buddie.toml` with stricter defaults (anchors on final answers, prose work claims) and
  starts an **intro mode**, in which each would-be return is only a warning until you have seen it work.
- **Profiles** *(2.0)* choose which checks run (`--profile`, MCP `profile`). What a profile leaves out is not
  checked, and receipt v1 says so ([docs/profiles.md](docs/profiles.md)).
- **The protected policy** *(2.0)* is a file only an administrator can write (`/etc/buddie/policy.toml`, or
  `<ProgramData>\buddie\policy.toml` on Windows). The agent runs as your user, so it can change `buddie.toml`, the
  hook's environment and the plugin's settings; while the policy is in force, none of those can lower its limits. An
  unprotected or invalid policy file makes buddie run on its strictest limits ([docs/policy.md](docs/policy.md)).

## Security and privacy

- **It runs locally.** Snapshots, the journal and settings stay on your machine. No telemetry, no model calls, no
  account; a remote server exists only if you host one.
- **It fetches the pages a report cites**, to snapshot them, whenever it checks a report with links (`BUDDIE_FETCH=0`
  or `--no-fetch`: stored snapshots only). No text of your session is sent with those requests.
- **It calls GitHub** for `pr:` and `ci:` anchors: `api.github.com`, or the GitHub Enterprise API a protected policy
  names (`BUDDIE_GITHUB=0` or `--no-github`: none).
- **Your GitHub token** is optional, taken from the plugin's setting or `BUDDIE_GITHUB_TOKEN`, and sent only to that
  API. buddie never reads an ambient `GITHUB_TOKEN`.
- **The Claude Code transcript** is read in place to check `run:` anchors; it is never copied or sent, and a plugin
  setting turns reading it off. The journal keeps hashes and verdicts, not your text.
- **What buddie cannot prevent:** code that already runs as your user, a replaced `python3` or `git` on `PATH`, an
  agent that rewrites the plugin's files or turns the plugin off in settings it can write, and an agent running as
  root or administrator. Without root, the protected policy is the one input the agent cannot change
  ([docs/policy.md](docs/policy.md#what-it-does-not-cover)).

Everything read, sent and kept: [PRIVACY.md](PRIVACY.md). Execution boundaries and tested attacks:
[docs/security.md](docs/security.md), [docs/adversarial.md](docs/adversarial.md).

## Limitations

- **buddie is not a truth detector.** It checks claims written in the forms above against their evidence. A claim in
  any other form is not checked.
- **`PASS` is scoped.** It covers the quotations and anchors that were checked, against the evidence that was read;
  with a profile, only the checks the profile ran.
- **`GAPS` is not success.** It means something could not be checked; the receipt says what. The CLI exits 0 on it.
- **A real quote can still mislead.** buddie checks that the words are on the cited page, not that they support the
  sentence around them.
- **Evidence ages.** A verdict holds for the snapshot hash and time it names; `pr:` and `ci:` describe GitHub now
  unless pinned to a commit. `buddie freshness` *(2.0)* says when evidence is about another revision.
- **Advice is advice.** The MCP tools and the CLI change nothing unless something acts on their result.
- **The gate covers what the client sends it:** Claude Code's `Stop` and `SendMessage`, Codex's `Stop`. Desktop and
  other clients have no hook, and `run:` is checked only against a Claude Code transcript.
- **The gate is not a lock.** It returns an answer; the agent then fixes the claim or says, in a line starting with
  `buddie:`, what is unverified, and the answer goes out with that line. A broken `pr:`, `ci:` or `run:` anchor has
  to be fixed or removed, and a protected policy can require a fix for everything. If the check cannot run at all (no Python, a timeout), the answer goes back once and then out
  with a note that nothing was checked: it is never passed as checked.
- **Local evidence is local.** Repository anchors, `run:` and work claims are checked against files on your machine:
  the checkout, the transcript, the task queue. buddie shows what those files say; an agent that can write them can
  change what they say.
- **A receipt is an evidence record.** It says what was checked and found, not that code is correct: a green CI on
  weak tests stays weak, and a command that prints a prepared file passes `run:`.
- **Whether agents misstate less with buddie** is not yet measured ([docs/research.md](docs/research.md)).

## Research

In 929 checkable quotations from published deep-research reports, **212 (22.8 %) were altered or absent from the page
they cited**; buddie flagged 207 of them. Out of sample, its quote check wrongly reports `NOT_FOUND` for 2.3 % of real
quotations, and for 6.9 % on a new genre (Search Arena answers), mostly words the agent itself put in quotation marks.
The labellers were Claude subagents working blind to the verdicts.

<details>
<summary>The data sets</summary>

| Finding | Result | Data |
|---|---|---|
| quotations altered or absent (o3 Deep Research, Perplexity, Grok, Doubao, Claude 3.7 Sonnet) | 212 of 929 (22.8 %, 95 % CI 20–26 %) | [E008](results/E008-drb2-fresh), [E010](results/E010-ydc-o3), [E011](results/E011-drb1-claude), [E012](results/E012-search-misses) |
| cited numbers not in their source | 28 of 103 (27.2 %) | [E009](results/E009-drb1-numbers) |
| false `NOT_FOUND`, out of sample | 10 of 440 (2.3 %) | [method](docs/verbatim-method.md) |
| false `NOT_FOUND`, Search Arena | 29 of 423 (6.9 %) | [E014](results/E014-search-arena) |
| plugin evals: a false quote, `pr:` or `ci:` claim passed on | the truth reached the person in every trap run with buddie, in none without | [evals](evals/README.md) |

</details>

Method, limits and how to reproduce: [docs/research.md](docs/research.md).

## Documentation

| Topic | Read |
|---|---|
| Getting started on each surface | [integrations.md](docs/integrations.md#first-time-setup) |
| Claude Code: levels, intro mode, what the hook reads | [claude-code.md](docs/claude-code.md) |
| Configuration and environment variables | [configuration.md](docs/configuration.md) |
| Writing checkable claims and anchors | [skills/buddie](skills/buddie/SKILL.md), [verbatim-verdicts.md](docs/verbatim-verdicts.md) |
| Profiles and the protected policy | [profiles.md](docs/profiles.md), [policy.md](docs/policy.md) |
| Receipts v0 and v1 | [receipts.md](docs/receipts.md) |
| Freshness and environment snapshots | [freshness.md](docs/freshness.md), [environment.md](docs/environment.md) |
| Security and privacy | [security.md](docs/security.md), [adversarial.md](docs/adversarial.md), [PRIVACY.md](PRIVACY.md) |
| Codex, Claude Desktop, a hosted server | [install-codex.md](docs/install-codex.md), [install-claude-desktop.md](docs/install-claude-desktop.md), [deploy.md](docs/deploy.md) |
| Research and evaluations | [research.md](docs/research.md), [evals](evals/README.md) |
| Releases and distribution | [release.md](docs/release.md), [distribution.md](docs/distribution.md), [CHANGELOG.md](CHANGELOG.md) |

## Status, contributing, license

2.0 keeps the 1.x interfaces and receipt v0 as the default ([release status](#release-status)); the behaviour that
changed on purpose is listed in the [CHANGELOG](CHANGELOG.md), with what 2.0 guarantees and how it was
tested in [docs/release-hardening.md](docs/release-hardening.md). The receipts, the CLI, the MCP tools and
`buddie.toml` follow semantic versioning. This repository was called `verbatim` until October 2026; `verbatim` is now
buddie's quote module (`buddie-verbatim`).

Contributions: [CONTRIBUTING.md](CONTRIBUTING.md). License: [Apache-2.0](LICENSE), third-party notices in
[NOTICE](NOTICE). Citation: [CITATION.cff](CITATION.cff).
