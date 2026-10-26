<!-- mcp-name: io.github.tsyyan/buddie -->

<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/tsyyan/buddie/v2.0.1/assets/brand/buddie-logo-dark.png">
  <img src="https://raw.githubusercontent.com/tsyyan/buddie/v2.0.1/assets/brand/buddie-logo.png" alt="buddie." width="360">
</picture>

### Verify the claim. Know the context.

**Evidence and environment awareness for AI agents.**

[![CI](https://github.com/tsyyan/buddie/actions/workflows/ci.yml/badge.svg)](https://github.com/tsyyan/buddie/actions/workflows/ci.yml)
[![Python](https://img.shields.io/pypi/pyversions/buddie)](https://pypi.org/project/buddie/)
[![License](https://img.shields.io/github/license/tsyyan/buddie)](https://github.com/tsyyan/buddie/blob/v2.0.1/LICENSE)
[![Buddie on Glama](https://glama.ai/mcp/servers/tsyyan/buddie/badges/score.svg)](https://glama.ai/mcp/servers/tsyyan/buddie)
[![Buddie on MCPRush](https://mcprush.com/badge/buddie-mcp/score.svg)](https://mcprush.com/to/buddie-mcp?ref=badge)
[![Listed on mcpservers.org](https://mcpservers.org/badge.svg)](https://mcpservers.org/servers/tsyyan/buddie)

<img src="https://raw.githubusercontent.com/tsyyan/buddie/v2.0.1/assets/brand/readme-hero.png" alt="The buddie dog between a stack of source documents under a magnifying glass and a laptop showing a chip: evidence on one side, the machine on the other.">

</div>

## Why Buddie?

An agent finishes a task and tells you that CI passed, that a source supports its summary, or that your laptop has
CUDA and Python 3.12. It sounds certain, and often it is right. When it is wrong, the mistake hides inside a
confident sentence.

Buddie separates what can be checked from what is only claimed. It checks supported claims against the evidence
itself, gives the agent real observations of your machine instead of guesses, and marks what it could not check as
unchecked. In 929 checkable quotations from published deep-research reports, 212 were altered or absent from the
page they cited; Buddie flagged 207 of them ([research](https://github.com/tsyyan/buddie/blob/v2.0.1/docs/research.md)).

## What Buddie does

**Verify.** Buddie checks supported claims against their evidence: a quotation against the page it links to, a file
or commit against your repository, a merged PR or a green CI run against GitHub, a test result against the session's
record of the command. No language model takes part in the check, so the agent cannot argue its way to a different
verdict.

**Catch mismatches.** In Claude Code and Codex, Buddie's hook checks the agent's answer before it reaches you. When a
claim does not hold, the answer goes back to the agent with the reason, so it can fix the claim or say plainly what
is unverified. Other clients call the same checks through MCP or the command line and decide what to do with the
result.

**Observe.** Before it suggests a command, an agent can ask Buddie for the parts of your machine the task needs: the
operating system, CPU, memory, GPU, Python, runtimes, tools. Buddie reads only the categories you have granted,
changes nothing, and records how each value was observed.

## See it in action

### Verify an agent's claim

An agent reports that it fixed a date parser and that the test suite is green. It marks the claim with a small
anchor, `⚓ run:pytest -q => 41 passed`, that Buddie can check. The session transcript records what the test command
actually printed:

<img src="https://raw.githubusercontent.com/tsyyan/buddie/v2.0.1/assets/demo/verification.svg" alt="Verify, from a real run on the bundled examples/work fixture. Agent claim: the test suite is green, run:pytest -q => 41 passed. Evidence check, session transcript: 1 failed, 40 passed in 3.1s. Verification outcome: FAIL, effects 0/1 hold, 1 broken, exit 1." width="600">

Run it yourself from a clone; the report and transcript are in [`examples/work`](https://github.com/tsyyan/buddie/tree/v2.0.1/examples/work):

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

The files are a teaching fixture: Buddie reads the recorded output rather than rerunning pytest. `--json receipt.json`
also writes a receipt naming the evidence behind the verdict. Quotation, PR and CI examples, and which integration
checks what: [verification guide](https://github.com/tsyyan/buddie/blob/v2.0.1/docs/verification.md).

### Know the environment

An agent is asked to set up a local development environment. Instead of guessing the operating system, GPU or Python
version, it asks Buddie for three categories, which the person has granted:

<img src="https://raw.githubusercontent.com/tsyyan/buddie/v2.0.1/assets/demo/environment.svg" alt="Observe, from a real run on one Windows machine. Task: configure local development environment. Authorized categories: system.os, hardware.gpu, software.python. Observed: OS Windows 11; GPU NVIDIA GeForce GTX 1650, 4 GiB; Python 3.14.6 with pip and venv." width="600">

<!-- readme-diagnostics -->
```bash
buddie snapshot --category system.os --category hardware.gpu --category software.python \
  --task "configure local development environment" --json diagnostics.json
```

```
buddie snapshot: diagnostics of 3 categories (grants active, policy absent; these govern the categories only)
  system.os: collected
    name: Windows 11  [os_interface]
  hardware.gpu: collected
    adapters: [model NVIDIA GeForce GTX 1650, source nvidia_smi_gpus, vendor NVIDIA, vram_bytes 4294967296]  [fixed_program]
  software.python: collected
    buddie_runtime: implementation cpython, pip True, venv True, version 3.14.6  [buddie]
```

Abridged from a run of buddie 2.0.0: the lines shown are unedited, and the machine's other observed values are left
out. `diagnostics.json` holds the full document, with the method and time of each value.

A category you have not granted is reported as denied, and its collector never runs. A value Buddie cannot read is
marked unavailable, with the reason. Diagnostics is read-only and installs nothing; it gives the agent better facts,
not a guarantee that its next command is right. [Categories, grants and the document](https://github.com/tsyyan/buddie/blob/v2.0.1/docs/environment.md#diagnostics).

## Get started

Buddie needs Python 3.11 or newer and has no dependencies.

### Claude Code

The recommended start. The plugin adds the answer check, the MCP tools including environment diagnostics, and
`run:` checks against the session transcript:

```
/plugin marketplace add tsyyan/buddie
/plugin install buddie@buddie
```

It installs this repository's default branch. To allow diagnostics, save the categories you choose as
`environment.toml` in `~/.config/buddie/` (`%APPDATA%\buddie\` on Windows). For the demo above:

<!-- readme-grants -->
```toml
version = 1
allow = ["system.os", "hardware.gpu", "software.python"]
roots = []
```

Levels, the intro mode and what the hook reads: [Claude Code guide](https://github.com/tsyyan/buddie/blob/v2.0.1/docs/claude-code.md).

### Other integrations

- **Codex:** `codex plugin marketplace add tsyyan/buddie`, then `codex plugin add buddie@buddie`, and enable its hook
  in `/hooks`. The check runs at `Stop`; `run:` claims stay unchecked. [Codex guide](https://github.com/tsyyan/buddie/blob/v2.0.1/docs/install-codex.md)
- **Any MCP client:** `uvx buddie serve` starts the stdio server. There is no gate: the agent calls the tools.
  [Integrations](https://github.com/tsyyan/buddie/blob/v2.0.1/docs/integrations.md)
- **Command line and CI:** `pip install buddie`, then `buddie verify REPORT.md --json receipt.json`. It exits 1 on
  `FAIL`; `GAPS` and `EMPTY` exit 0, so a CI step that requires `PASS` should read the receipt's outcome.
- **Claude Desktop:** the `.mcpb` bundle from [Releases](https://github.com/tsyyan/buddie/releases), without a gate.
  [Desktop guide](https://github.com/tsyyan/buddie/blob/v2.0.1/docs/install-claude-desktop.md)

Every surface in detail: [getting started](https://github.com/tsyyan/buddie/blob/v2.0.1/docs/getting-started.md).

### Release status

| | Version |
|---|---|
| Latest release: PyPI, GitHub Releases, the Desktop bundle, the MCP Registry | **2.0.1** |
| Development source described here | **2.0.2**, prepared, not yet released |

Registries give 2.0.1. To inspect the prepared source after review: `pip install git+https://github.com/tsyyan/buddie@hardening/public-release-record`.

Upgrading from 2.0.0 changes nothing; 2.0.1 fixes how the MCP server reads its input on Windows systems whose code
page is not UTF-8. Upgrading from 1.1.1 changes nothing for a 1.x setup. What can differ, and why, is in the
[changelog](https://github.com/tsyyan/buddie/blob/v2.0.1/CHANGELOG.md).

## Documentation

| Topic | Read |
|---|---|
| Install on every surface | [Getting started](https://github.com/tsyyan/buddie/blob/v2.0.1/docs/getting-started.md) |
| What each integration does | [Integrations](https://github.com/tsyyan/buddie/blob/v2.0.1/docs/integrations.md) |
| Checks, outcomes and receipts | [Verification](https://github.com/tsyyan/buddie/blob/v2.0.1/docs/verification.md), [receipts](https://github.com/tsyyan/buddie/blob/v2.0.1/docs/receipts.md) |
| Environment diagnostics | [Environment](https://github.com/tsyyan/buddie/blob/v2.0.1/docs/environment.md#diagnostics) |
| Security and privacy | [Limitations](https://github.com/tsyyan/buddie/blob/v2.0.1/docs/limitations.md), [security](https://github.com/tsyyan/buddie/blob/v2.0.1/docs/security.md), [privacy](https://github.com/tsyyan/buddie/blob/v2.0.1/PRIVACY.md) |
| Contributing | [CONTRIBUTING.md](https://github.com/tsyyan/buddie/blob/v2.0.1/CONTRIBUTING.md) |
| Everything else | [Documentation index](https://github.com/tsyyan/buddie/blob/v2.0.1/docs/README.md) |

## Limitations

Buddie is not a truth detector. It checks claims in the forms it recognises, such as quotations with links and
anchored claims about files, PRs, CI and commands, against the evidence it can read. Paraphrases and unanchored claims
stay unchecked. `PASS` covers only what was checked, and `GAPS` and `EMPTY` are not passes.

The answer check exists only in Claude Code and Codex, and it returns an answer rather than locking it: the agent
fixes the claim or discloses it as unverified. An agent running as your user can edit local evidence, settings and
the diagnostics grants file; only an administrator's protected policy sets limits it cannot raise.

Buddie runs locally, with no model calls and no telemetry. It fetches the pages a report cites and calls GitHub for
PR and CI claims. [All limitations](https://github.com/tsyyan/buddie/blob/v2.0.1/docs/limitations.md) · [Security boundaries](https://github.com/tsyyan/buddie/blob/v2.0.1/docs/security.md) ·
[Privacy](https://github.com/tsyyan/buddie/blob/v2.0.1/PRIVACY.md)

---

<div align="center">

[Apache-2.0](https://github.com/tsyyan/buddie/blob/v2.0.1/LICENSE) · [Changelog](https://github.com/tsyyan/buddie/blob/v2.0.1/CHANGELOG.md) · [Citation](https://github.com/tsyyan/buddie/blob/v2.0.1/CITATION.cff) · [Issues](https://github.com/tsyyan/buddie/issues)

</div>
