# buddie in Claude Desktop

Claude Desktop installs local MCP servers from MCP Bundles (`.mcpb`, formerly Desktop Extensions). buddie's bundle
holds the server and nothing else. It needs no packages, only **Python 3.11 or newer** on your machine: `python3` on
macOS and Linux, `python` on Windows.

## Install

1. Get `buddie-<version>.mcpb`: from the release page of [tsyyan/buddie](https://github.com/tsyyan/buddie/releases),
   or build it from a clone:

   ```bash
   npx --yes @anthropic-ai/mcpb@2.1.2 pack . buddie.mcpb
   ```

2. Open the file, or drag it onto Claude Desktop (Settings → Extensions), and press Install.
3. Optional settings:
   - **Snapshot folder**: where page snapshots are kept (default `~/.cache/buddie/store`).
   - **GitHub token**: used only for `pr:` and `ci:` anchors. Without it GitHub allows 60 lookups an hour, and
     private repos cannot be checked.

Then ask Claude to check a report, for example: "verify this report with buddie before we use it".

The build command is an explicit package download you run yourself; it is not executed by Buddie's MCP server or
hooks. From an inspected clone, `python3 run.py serve` (Windows: `python run.py serve`) runs locally without a
package launcher. Both token names are restricted to GitHub.com or an administrator's protected HTTPS Enterprise
API; `BUDDIE_GITHUB_API` alone never authorizes token delivery. Leave the optional token blank, or remove it and
revoke it at GitHub. See [PRIVACY.md](../PRIVACY.md) for endpoints, storage and proxy trust assumptions.

## What works here

| | Claude Desktop | Claude Code plugin |
|---|---|---|
| `verify_report`, `snap`, `source_text` | yes | yes |
| quotes against page snapshots, numbers with a link | yes | yes |
| `pr:`, `ci:` on GitHub | yes | yes |
| `path#sha256`, `path@commit` | yes, when Claude passes `repos` (folders on your machine) | yes, the repo around the session |
| `run:` (a command and its output) | **unchecked**: Desktop has no session transcript, so these anchors come out `UNCHECKABLE` and the receipt is `GAPS` | yes |
| gate on the final answer (hook) | no: Desktop has no hooks, so Claude has to call `verify_report` | yes |
| `summary` | listed, but it reads the Claude Code hook journal, so it has nothing to show here | yes |
| `environment_snapshot` | yes: the categories you granted ([environment.md](environment.md#diagnostics)) | yes |

## Privacy

The server runs on your machine. It downloads the pages a report cites and asks the GitHub API about `pr:` and `ci:`
anchors, with your token if you gave one. Nothing else leaves the machine. Details are in
[PRIVACY.md](../PRIVACY.md).

## Troubleshooting

- **The extension does not start**: check that `python3 --version` (Windows: `python --version`) prints 3.11 or
  newer. Claude Desktop's extension logs show the error.
- **`pr:`/`ci:` anchors come out as GAPS with "GitHub unreachable" or a 403**: you hit the anonymous rate limit. Add a
  token in the extension's settings.
