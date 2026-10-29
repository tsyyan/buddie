# buddie: listing copy and local installation

Checked against release 2.0.4 on 2026-10-29. Reusable copy for every directory and marketplace, so each listing
says the same thing. It is not a claim that a directory has approved it.

## Identity

- **Name: `buddie`**, lowercase, as in the logo's wordmark. The package, the plugin id, the MCP server name and every
  listing title use it. Not "Buddie", "buddie MCP", "buddie: claim checker" or "Buddie — AI Agent Reliability Toolkit".
- **Tagline:** Verify the claim. Know the context.
- **Category phrase** (where a listing has a subtitle or category): AI agent reliability toolkit.
- **Icon:** [`assets/icon.png`](../assets/icon.png), 1024×1024 PNG, the dog from the README logo. Raw URL for forms
  that take one: `https://raw.githubusercontent.com/tsyyan/buddie/main/assets/icon.png`.
- Repository: https://github.com/tsyyan/buddie
- Official MCP Registry name: `io.github.tsyyan/buddie`.
- License: Apache-2.0; Python 3.11 or newer; no runtime dependencies.
- Release: https://github.com/tsyyan/buddie/releases/latest
- Package: https://pypi.org/project/buddie/
- Privacy: https://github.com/tsyyan/buddie/blob/main/PRIVACY.md

## Descriptions

**Short (≤ 100 characters, the MCP Registry's limit):**

> Checks AI agents' claims against primary evidence, with no model; observes only what you grant.

**One paragraph (plugin manifests and marketplaces):**

> Checks what an AI agent reports against primary evidence (quotes against their sources; repo, PR and CI claims
> against git and GitHub; test claims against the session log), with no model in the check, plus permission-scoped
> environment diagnostics. A false claim goes back to the agent with the reason.

**Long (directory pages):**

> buddie checks supported quotations, numbers and repository/GitHub claims in an agent's report against primary
> evidence, without a model in the check, and returns a receipt that names what failed and what could not be checked.
> Its environment tool observes only the local categories the person has granted. It runs locally over MCP stdio; no
> buddie account or hosted endpoint is required. In Claude Code and Codex a hook checks the final answer
> automatically; other clients call the tools.

## Tools and access

Eight MCP tools in 2.0.4. Directories that label access (MCPRush, Glama) should use these labels: `read` alone is
wrong for the tools that fetch pages or write snapshots and feedback state.

| Tool | What it does | Access |
|---|---|---|
| `verify_report` | Checks supported quotations, numbers and anchors; reports failures and gaps without certifying the whole text. | network, write (local snapshots) |
| `snap` | Fetches public URLs and stores content-addressed snapshots locally. | network, write |
| `source_text` | Reads stored snapshot text, optionally around a match. | read |
| `summary` | Summarizes the Claude Code hook journal; other clients have no journal. | read |
| `environment_snapshot` | Observes the local environment categories the person granted; the call grants nothing. | read |
| `feedback_start` | Checks a report and opens a verification feedback chain. | network, write (local chain state) |
| `feedback_resolve` | Checks a corrected text against the chain's open feedback and records the decision. | network, write |
| `feedback_accept` | Whether a final report is exactly the text the chain verified. | read |

Numeric checks compare detected numbers in cited sentences with source snapshots and nearby context; they do not
validate every numeric assertion or establish its semantic truth.

## Local install

```sh
uvx buddie serve
```

Pin a version where a listing prints one (`uvx buddie@2.0.4 serve`), and update the pin with each release.

Generic MCP client configuration (adapt the outer structure to the client):

```json
{"mcpServers":{"buddie":{"command":"uvx","args":["buddie","serve"]}}}
```

Alternatively, `pip install buddie`, then `buddie serve`. For Claude Desktop, open the release's
`buddie-<version>.mcpb`. Claude Code: `/plugin marketplace add tsyyan/buddie`, then `/plugin install buddie@buddie`
(the released plugin from `plugin-stable`). Codex: `codex plugin marketplace add tsyyan/buddie`, then
`codex plugin add buddie@buddie`.

No GitHub token is required for public evidence within API limits. Optional credentials use
`BUDDIE_GITHUB_TOKEN`, not ambient `GITHUB_TOKEN`. MCP-only installation does not install an answer gate. Session
execution checks need a Claude Code transcript; diagnostics describe the machine running the server, so a remote
deployment describes its host, not the user's PC.
