# Integrations: what exists, what it does, what to expect

This page lists every way to run buddie that this repository ships, as its manifests and code define them (not as
older docs describe them), and what each one does: install, configuration, how a check is run, its output and
errors, receipt versions, the protected policy, evidence provenance and platforms.

## Enforcement or advice

Two kinds of integration, and the difference matters:

- **Enforcement: the hooks** (Claude Code, Codex). buddie checks the agent's answer before it reaches you. A false
  claim is sent back to the agent with the reason; the answer goes out once it is fixed or the unverified part is
  disclosed. Levels per class (`block`, `warn`, `off`), profiles and the protected policy's floors apply here
  ([policy.md](policy.md), [profiles.md](profiles.md)).
- **Advice: the CLI, MCP tools, the remote server and the Python API.** buddie checks a text when asked and returns
  a receipt. Nothing is held back: the caller (you, an orchestrator, an agent) decides what to do with `FAIL`. The
  protected policy does not gate these: they report, and the receipt says what was checked.

## The surfaces

| Surface | Defined by | Starts | Receipt | Protected policy |
|---|---|---|---|---|
| Claude Code plugin: hooks | `.claude-plugin/plugin.json`, `hooks/hooks.json`, `hooks/run.sh` | `sh run.sh hook` (python3, python or `py -3`, isolated `-I`) | v0, in the journal | **enforced**: floors, `[evidence]`, one reading per event |
| Claude Code plugin: MCP | `.mcp.json` | `python3 run.py serve` | v0; v1 with `receipt: "v1"` | not a gate |
| Claude Code plugin: skills, commands | `skills/`, `commands/` | instructions for the agent: `/buddie:check`, `/buddie:init`, `/buddie:status` | (uses the CLI) | (as the CLI) |
| Codex plugin: Stop hook | `.codex-plugin/plugin.json`, `integrations/codex/hooks.json` | `python3 -I run.py hook` (`python -I` on Windows) | v0, in the journal | **enforced**, as the Claude Code hook |
| Codex plugin: MCP | `.codex-plugin/plugin.json` `mcpServers` | `python3 run.py serve`, `BUDDIE_DEFAULT_REPOS=none` | v0; v1 on request | not a gate |
| Codex without the plugin | `integrations/codex/config.toml` | your `~/.codex/config.toml` table | as MCP | not a gate |
| Claude Desktop bundle | `manifest.json` (`.mcpb`) | `python3 run.py serve` (`python` on Windows) | v0; v1 on request | not a gate |
| MCP registry entry | `server.json` | `uvx buddie serve` (PyPI) | as MCP | not a gate |
| Remote MCP server | `Dockerfile`, `render.yaml`, `buddie serve --http` | Streamable HTTP at `/mcp` | **v0 only** | not a gate |
| ChatGPT (via the remote server) | `integrations/chatgpt/` | your remote server's URL | v0 only | not a gate |
| CLI | `pyproject.toml` `buddie`, `buddie-verbatim` | `buddie verify report.md` | v0; v1 with `--receipt v1` | not a gate |
| Python API | `buddie.verify`, `buddie.receipts` | `verify(text)`, `assessment(text, …)` | v0; v1 with `receipts.render(a, "v1")` | not a gate |
| Evidence freshness | `buddie freshness`, `buddie.freshness` | `buddie freshness ci --repo R --pr N --evidence SHA` | none: a separate document ([freshness.md](freshness.md)) | not a gate |
| Environment snapshot | `buddie snapshot`, `buddie.environment` | `buddie snapshot --report report.md` | none: a separate document ([environment.md](environment.md)) | not a gate |
| Environment diagnostics | `buddie snapshot --category`, MCP `environment_snapshot` (local servers only), `buddie.diagnostics` | `buddie snapshot --category system.os --category hardware.gpu` | none: environment-diagnostics-v1 ([environment.md](environment.md#diagnostics)) | `[environment] allow` is a ceiling on the person's grants |

## Audit (PR #32)

Each surface was checked against the code on `main` at `0f864ec`. What was found:

| # | Surface | Finding | Kind | Severity | Status |
|---|---|---|---|---|---|
| 1 | Claude Code MCP (`.mcp.json`) | The plugin's GitHub token was handed to the MCP server as `BUDDIE_GITHUB_TOKEN`, a name that may go to an API the environment names (`BUDDIE_GITHUB_API`, which a project's settings can set). The hook gets the same token under the plugin's own name and never sends it there (#29) | defect, security | high | **fixed**: `.mcp.json` passes it as `CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN` |
| 2 | CLI `buddie verify` | A directory or a non-UTF-8 report ended in a traceback with exit 1, the exit code of a FAIL | defect | medium | **fixed**: exit 2 with the reason, as a missing report always was |
| 3 | MCP instructions | "PASS means every quote was found and every anchor holds": wrong under a profile, and PASS never makes a report true | documentation | medium | **fixed** |
| 4 | `buddie status` | Did not mention an active or invalid protected policy, though an invalid one makes the hook return every answer | UX gap | low | **fixed**: a `policy:` line when a policy file exists |
| 5 | README, plugin setting | "the token is sent only to api.github.com": a protected policy's `github_api` is the other place now. The README's table also listed `GITHUB_TOKEN`, which buddie never reads | documentation | low | **fixed** |
| 6 | Claude Code in a checkout of this repo | Claude Code loads the repo's `.mcp.json` as a project MCP server; `${CLAUDE_PLUGIN_ROOT}` is not set there, so it starts `/run.py` and fails | developer UX | low | documented (CONTRIBUTING.md); a fix needs the plugin path confirmed in Claude Code |
| 7 | Claude Code and Codex MCP on Windows | Both start `python3`, with no Windows variant (the Desktop bundle has one, the hooks fall back to `python` and `py -3`): with only python.org's `python`/`py`, these MCP servers do not start. The hooks still work | platform | low | documented; per-platform commands in these manifests are not verified here |
| 8 | MCP servers (plugin, Codex, Desktop) | Run Python without `-I`, unlike the hooks | hardening | low | deferred: not a gate, but noted |

Checked and holding, with tests:
- **Floors and scope:** the policy's floors in both hooks; no surface lowers verification scope without saying so (CLI note, MCP text, Coverage, receipt-v1 scope); an empty selection is never a pass.
- **Receipts:** the receipt version cannot change a gate decision. Remote MCP takes no `profile`, `modules`, `checks` or `receipt` argument.
- **Provenance:** caller-supplied evidence is never collector-observed, and unavailable evidence is a gap.
- **Secrets:** no token in receipts, errors or the journal.
- **Environment:** the environment and the repo's files are never protected authority.

## First-time setup

**Claude Code** (enforcement), inside Claude Code:

```
/plugin marketplace add tsyyan/buddie
/plugin install buddie@buddie
```

The hooks need Python 3.11 or later as `python3`, `python` or `py -3`. Without it, a Stop's answer goes back once
with "nothing was checked", and then goes on with a message to you: it is never passed as checked. Check the result
with `/buddie:status` or `buddie status`. To configure a project, run `buddie init` (writes `buddie.toml` with the
full checks and the intro mode).

**The CLI** (advice):

```bash
pip install buddie
```

```bash
buddie verify report.md
```

Exit 0: no FAIL (PASS, GAPS or EMPTY). Exit 1: FAIL. Exit 2: the input could not be used (a missing, unreadable or
non-UTF-8 report, an unknown profile, check or receipt version).

Codex: [install-codex.md](install-codex.md). Claude Desktop: [install-claude-desktop.md](install-claude-desktop.md).
The remote server and ChatGPT: [deploy.md](deploy.md).

## Choosing what is checked

```bash
buddie profiles
```

```bash
buddie verify report.md --profile research
```

```bash
buddie verify report.md --profile custom --modules github --checks quote
```

`buddie profiles` and `buddie modules` list what exists. Under a profile the CLI prints a `note` line naming what
was not checked and how many claims of that kind the text holds. For a project, use `buddie.toml` `[verify]`
([profiles.md](profiles.md)).

## Reading the result

| Word | Where | Means |
|---|---|---|
| `PASS` | v0, v1 | the checks that ran established no failure. Not "the report is true": only claims in a checked form (a quotation with its link, an anchor) are checked |
| `FAIL` | v0, v1 | a checked claim is false: a quotation not on its page, a broken anchor, a contradicted work claim |
| `GAPS` | v0, v1 | something could not be checked to the end (page unreadable, repo or GitHub out of reach) |
| `UNKNOWN` | v1 | a verdict buddie does not recognize (v0 counts it as GAPS) |
| `EMPTY` | v0, v1 | nothing of a checked kind in the text: nothing was verified |
| `NOT_RUN` | v1 | no check ran (v0 says EMPTY) |

To see what ran, ask for receipt-v1 (`--receipt v1`, MCP `receipt: "v1"`). Its `scope.coverage` is `FULL` (every
check ran), `PARTIAL` (some left out on purpose), `UNKNOWN` (some unavailable, for example work claims without a
`[mandate]`) or `NONE` (nothing ran). `FULL` is about which checks ran, not about how many of the report's claims
they could find ([receipts.md](receipts.md)).

## Troubleshooting

| Symptom | Cause | What to do |
|---|---|---|
| `buddie: no Python 3.11+ … nothing was checked` | the hook found no Python 3.11+ | install Python 3.11+ so that `python3`, `python` or `py -3` finds it |
| every answer returned with "buddie.toml cannot be read" | `buddie.toml` is not TOML or UTF-8, or `[verify]` names an unknown profile, module or check | `buddie status` shows the reason; fix the file |
| every answer returned with "the protected policy cannot be used" | the policy file is invalid or not protected | `buddie policy check` shows why; an administrator fixes it |
| `pr:`/`ci:` anchors always `UNCHECKABLE` | `BUDDIE_GITHUB=0`, the network forbidden by the policy, GitHub's rate limit, or a private repo without a token | set the plugin's GitHub token, or check `BUDDIE_GITHUB` |
| `run:` anchors always `UNCHECKABLE` | transcript reading is off (`read_transcript`), or the session log is not a Claude Code one | turn transcript reading on (Claude Code) |
| `buddie verify: … not UTF-8` / `… is a directory` | the report given cannot be read as text (exit 2) | pass a UTF-8 file, or `-` for stdin |
| buddie's MCP server does not start (Windows) | only `python`/`py` is installed, and the manifest starts `python3` | install Python so that `python3` exists, or add the server yourself with `python` |
| buddie's MCP server fails in a clone of this repo | Claude Code loads the repo's `.mcp.json` as a project server, where `${CLAUDE_PLUGIN_ROOT}` is not set | see CONTRIBUTING.md |
