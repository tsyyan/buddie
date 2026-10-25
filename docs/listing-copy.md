# Buddie: listing copy and local installation

Checked against release 2.0.0 on 2026-10-25. This is reusable copy, not a claim that a directory has approved it.

## Identity

- Name: **Buddie**; package and plugin id: `buddie`.
- Short description: Evidence checks and permission-scoped environment awareness for AI agents.
- Repository: https://github.com/tsyyan/buddie
- Official MCP Registry name: `io.github.tsyyan/buddie`.
- License: Apache-2.0; Python 3.11 or newer; no runtime dependencies.
- Release: https://github.com/tsyyan/buddie/releases/tag/v2.0.0
- Package: https://pypi.org/project/buddie/2.0.0/
- Privacy: https://github.com/tsyyan/buddie/blob/v2.0.0/PRIVACY.md

## Description

Buddie checks supported quotations and repository/GitHub claims against primary evidence, without a model
in the check. It returns receipts that identify failed and unchecked claims. Its environment tool observes
only the local categories the person has granted. It runs locally over MCP stdio; no Buddie account or hosted
endpoint is required. Automatic answer gating uses a separate Claude Code or Codex hook integration.

## Five MCP tools

| Tool | Purpose and scope |
|---|---|
| verify_report | Checks supported quotes, numbers and anchors; returns PASS, FAIL, GAPS or EMPTY. Unchecked prose is not certified. |
| snap | Fetches public URLs and writes content-addressed snapshots locally. |
| source_text | Reads stored snapshot text, optionally around matches. |
| summary | Summarizes the Claude Code hook journal; other clients need that journal for useful data. |
| environment_snapshot | Observes granted local environment categories; the call itself grants no permission. |

## Local install

With uv installed, start the version-pinned stdio server:

```sh
uvx buddie@2.0.0 serve
```

Generic MCP client configuration (adapt the outer structure to the client):

```json
{"mcpServers":{"buddie":{"command":"uvx","args":["buddie@2.0.0","serve"]}}}
```

Alternatively, `pip install buddie==2.0.0`, then `buddie serve`.
For Claude Desktop, open the released
[buddie-2.0.0.mcpb](https://github.com/tsyyan/buddie/releases/download/v2.0.0/buddie-2.0.0.mcpb).
The [getting-started guide](getting-started.md) covers plugin installation and environment grants.

No GitHub token is required for public evidence within API limits. Optional credentials use
`BUDDIE_GITHUB_TOKEN`, not ambient `GITHUB_TOKEN`. URL fetching and snapshot writes should be reflected in
directory access labels; read-only MCP hints do not mean there is no network or local storage activity.

MCP-only installation does not install an answer gate. Session execution checks require a supported transcript;
diagnostics describes the machine running the server. A remote deployment describes its host, not the user's PC.
