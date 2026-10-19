# buddie in Codex

Codex (CLI, IDE extension, desktop app) can take buddie as a plugin or as a plain MCP server. You need Python 3.11 or
newer: `python3` on macOS and Linux, `python` on Windows.

## As a plugin (recommended)

This repository is also a Codex marketplace: Codex reads `.claude-plugin/marketplace.json` and the plugin's
`.codex-plugin/plugin.json`.

```bash
codex plugin marketplace add tsyyan/buddie
```

```bash
codex plugin add buddie@buddie
```

The plugin brings:

- **the MCP server** `buddie` with `verify_report`, `snap`, `source_text` (started as `python3 run.py serve` in the
  plugin's folder);
- **the skills** `buddie:buddie` and `buddie:verbatim`, which teach the agent to quote from snapshots and to state
  repo, PR and CI facts as anchors;
- **a Stop hook** (`integrations/codex/hooks.json`): a final answer with a quote its source does not contain, or an
  anchor that does not hold, is sent back to the model with the reasons before the turn ends. Codex runs plugin
  hooks only after you review and trust them: open `/hooks` in a session once after installing.

Plugins with hooks cannot be listed in the public plugin directory, so this plugin is installed from the
marketplace above, not from the directory.

## As an MCP server only

Add a table from [`integrations/codex/config.toml`](../integrations/codex/config.toml) to `~/.codex/config.toml`,
or run:

```bash
codex mcp add buddie -- python3 /path/to/buddie/run.py serve
```

Then copy [`integrations/codex/AGENTS.md`](../integrations/codex/AGENTS.md) into your project's `AGENTS.md`, so the
agent knows when to call `verify_report`. A remote buddie ([deploy.md](deploy.md)) is added the same way, with
`url = "https://…/mcp"`.

## What works in Codex

| | Codex | Claude Code |
|---|---|---|
| quotes against page snapshots, numbers with a link | yes | yes |
| `pr:`, `ci:` on GitHub | yes | yes |
| `path#sha256`, `path@commit` | yes, when the agent passes `repos` (the plugin's server does not guess the workspace) | yes |
| gate on the final answer | yes, Stop hook (reads `last_assistant_message`) | yes, Stop and PreToolUse on outgoing messages |
| `run:` (a command and its output) | **not checked**: Codex's session log has another shape than Claude Code's transcript, so `run:` anchors come out `UNCHECKABLE` | yes |
| subagent summary, decision cards | no | yes |

## Check it

```bash
codex mcp get buddie
```

This shows the server with `cwd` in the plugin folder. In a session, ask: "verify this report with buddie: …". With
a false anchor in a final answer, the Stop hook sends the answer back with `buddie FAIL` and the reasons.

## Privacy

As in Claude Code: the server downloads the pages a report cites and asks the GitHub API about `pr:`/`ci:` anchors.
The hook keeps a journal at `~/.cache/buddie/hook.jsonl` with receipts, not text. See [PRIVACY.md](../PRIVACY.md).
