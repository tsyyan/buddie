# Getting started: every surface

Every way to install buddie, what each gives you, the MCP tools, and how enforcement and the protected policy
work. The [README](../README.md#get-started) has the short path; what each surface does in detail is in
[integrations.md](integrations.md).

Features marked *(2.0)* are new in 2.0.0 and are not in 1.1.1 or earlier
([release status](../README.md#release-status)).

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
installs this repository's `main` (2.0.3 today). Its hook checks the final answer at `Stop` and messages sent with
`SendMessage`; on `FAIL` the answer goes back to the agent with the reasons. Optional: a GitHub token for `pr:` and
`ci:`, which the plugin asks for and keeps as a secret. Levels, the intro mode and what the hook reads:
[claude-code.md](claude-code.md). buddie is not listed in Anthropic's plugin directory yet: a submission is
in review.

### Codex

```bash
codex plugin marketplace add tsyyan/buddie
```

```bash
codex plugin add buddie@buddie
```

Codex runs plugin hooks after you review them in `/hooks`. `run:` anchors stay unchecked there, because Codex's
session log is not Claude Code's transcript. Setup and the MCP-only route: [install-codex.md](install-codex.md).

### Claude Desktop

Download `buddie-<version>.mcpb` from the [releases](https://github.com/tsyyan/buddie/releases) (2.0.3 today) and open
it. Desktop has no hooks, so Claude has to call `verify_report` itself, and `run:` is unchecked.
[install-claude-desktop.md](install-claude-desktop.md).

### Any MCP client

For a client that starts a command (stdio), with [uv](https://docs.astral.sh/uv/):

```bash
uvx buddie serve
```

This runs the latest release on PyPI (2.0.3 today); `uvx buddie@2.0.3 serve` pins that version. A
remote server you host for claude.ai or ChatGPT: [deploy.md](deploy.md).

### Terminal or CI

```bash
pip install buddie
```

`buddie verify REPORT.md` fetches the pages the report cites, checks it, prints the blocking items and a summary, and
exits 0 when nothing failed (`PASS`, `GAPS` or `EMPTY`), 1 on `FAIL` and 2 when the input cannot be used. A CI step
that needs `PASS` should read the receipt's outcome, not only the exit code. `--json FILE` writes the receipt;
`--receipt v1` *(2.0)* writes receipt v1. Environment diagnostics (`buddie snapshot --category`) is *(2.0)*.

### From source

```bash
git clone https://github.com/tsyyan/buddie
```

`python3 run.py verify REPORT.md --repo .` runs from the clone with nothing installed, and `pip install .` installs
2.0.3. Contributing: [CONTRIBUTING.md](../CONTRIBUTING.md).

## MCP tools

| Tool | Does |
|---|---|
| `verify_report` | checks a report (text or file) and returns its receipt: v0, or v1 on request *(2.0)* |
| `snap` | snapshots URLs into the store, so quotes can be taken from and checked against the same bytes |
| `source_text` | the visible text of a snapshot, or the matches of a pattern with context: copy quotes from here |
| `summary` | Claude Code only: the code-built summary of finished subagents, from the hook's journal |
| `environment_snapshot` | *(2.0)* observes the parts of this machine a task needs (OS, CPU, memory, GPU, Python, runtimes, ...), only the categories you granted ([environment.md](environment.md#diagnostics)) |
| `feedback_start` | checks a report and opens a verification feedback chain: feedback-v1 with bounded actions ([feedback.md](feedback.md#mcp)) |
| `feedback_resolve` | checks a corrected text against the chain's open feedback with the chain's own options and records the decision |
| `feedback_accept` | before a final report from a chain is accepted: whether it is the text the chain verified (an edited report, or one from an unverified chain, is refused) |

Every stdio server (the Claude Code and Codex plugins, Desktop, `uvx buddie serve`) lists all eight; `summary` has data
only with the Claude Code hook, and `environment_snapshot` collects nothing until you grant categories. The remote
server has the first three. **The MCP tools and the CLI advise**: they
report, and you or the agent decide what to do with `FAIL`. **The hooks enforce**: they check the answer itself and
hold it back. The protected policy applies to the hooks only.

## Enforcement and the protected policy

The hook checks the answer the agent hands you. What it blocks is set per class of claim (`block`, `warn` or `off`):

- **A fresh install** blocks only what is false: a quotation not on its page, an anchor that does not hold.
- **`buddie init`** writes `buddie.toml` with stricter defaults (anchors on final answers, prose work claims) and
  starts an **intro mode**, in which each would-be return is only a warning until you have seen it work.
- **Profiles** *(2.0)* choose which checks run (`--profile`, MCP `profile`). What a profile leaves out is not
  checked, and receipt v1 says so ([profiles.md](profiles.md)).
- **The protected policy** *(2.0)* is a file only an administrator can write (`/etc/buddie/policy.toml`, or
  `<ProgramData>\buddie\policy.toml` on Windows). The agent runs as your user, so it can change `buddie.toml`, the
  hook's environment and the plugin's settings; while the policy is in force, none of those can lower its limits. An
  unprotected or invalid policy file makes buddie run on its strictest limits ([policy.md](policy.md)).

## Versions, contributing, license

2.0 keeps the 1.x interfaces and receipt v0 as the default ([release status](../README.md#release-status)); the behaviour that
changed on purpose is listed in the [CHANGELOG](../CHANGELOG.md), with what 2.0 guarantees and how it was
tested in [release-hardening.md](release-hardening.md). The receipts, the CLI, the MCP tools and
`buddie.toml` follow semantic versioning. This repository was called `verbatim` until October 2026; `verbatim` is now
buddie's quote module (`buddie-verbatim`).

Contributions: [CONTRIBUTING.md](../CONTRIBUTING.md). License: [Apache-2.0](../LICENSE), third-party notices in
[NOTICE](../NOTICE). Citation: [CITATION.cff](../CITATION.cff).
