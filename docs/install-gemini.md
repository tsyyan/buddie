# buddie in Gemini CLI

From 2.1.0 the released plugin on the branch `plugin-stable` is also a Gemini CLI extension
(`gemini-extension.json`, `GEMINI.md`). You need Python 3.11 or newer as `python3` on `PATH`.

```bash
gemini extensions install https://github.com/tsyyan/buddie --ref plugin-stable
```

Gemini asks you to confirm the extension and offers one optional setting, a GitHub token for `pr:` and `ci:`
anchors on private repositories or above 60 lookups an hour. It is stored as `BUDDIE_GITHUB_TOKEN`; buddie never
reads an ambient `GITHUB_TOKEN`.

The extension brings:

- **the MCP server** `buddie` (`python3 -I run.py serve` in the extension's folder) with `verify_report`, `snap`,
  `source_text` and `environment_snapshot` (the machine categories you granted, [environment.md](environment.md#diagnostics));
- **`GEMINI.md`**, the context that tells the agent when to call `verify_report`, to quote only from snapshots and
  to state repo, PR and CI facts as anchors.

There is **no gate**: Gemini CLI reads hooks from `hooks/hooks.json` in its own format, and the package has none for
it yet, so nothing holds a false answer back automatically. The agent calls the tools; the receipt line under an
answer is what it copied from the tool's result.

## Check it

```bash
gemini mcp list
```

`buddie` should be listed as connected (the list is printed on stderr). In a session, ask: "verify this report with
buddie: …".

## Update and remove

```bash
gemini extensions update buddie
gemini extensions uninstall buddie
```

## Privacy

As in Claude Code: the server downloads the pages a report cites and asks the GitHub API about `pr:`/`ci:` anchors;
the machine is read only in the categories you granted. See [PRIVACY.md](../PRIVACY.md).
