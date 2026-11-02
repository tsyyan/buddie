# buddie in GitHub Copilot CLI

From 2.1.0 the released plugin on the branch `plugin-stable` is also a Copilot CLI plugin
(`.github/plugin/plugin.json`, marketplace from `.claude-plugin/marketplace.json`). You need Python 3.11 or newer as
`python3` on `PATH`.

```bash
copilot plugin marketplace add tsyyan/buddie@plugin-stable
copilot plugin install buddie@buddie
```

The plugin brings:

- **the MCP server** `buddie` (`python3 -I run.py serve` in the plugin's folder) with `verify_report`, `snap`,
  `source_text` and `environment_snapshot` (the machine categories you granted, [environment.md](environment.md#diagnostics));
- **the skills** `buddie`, `verbatim`, `environment` and `buddie-discovery`, which teach the agent to quote from
  snapshots, to state repo, PR and CI facts as anchors and to check its answer with `verify_report`.

There is **no gate yet**: Copilot CLI's hook events are not tested here, so the package installs no hook for it, and
nothing holds a false answer back automatically.

For `pr:` and `ci:` anchors on private repositories or above 60 lookups an hour, set `BUDDIE_GITHUB_TOKEN` in the
environment Copilot starts in; buddie never reads an ambient `GITHUB_TOKEN`.

## Check it

In a session, ask: "verify this report with buddie: …". The tool's result ends with a receipt line.

## Privacy

As in Claude Code: the server downloads the pages a report cites and asks the GitHub API about `pr:`/`ci:` anchors;
the machine is read only in the categories you granted. See [PRIVACY.md](../PRIVACY.md).
