# buddie in Claude Code

What the Claude Code plugin brings, how its hook decides, and what it reads. Install:
[README](../README.md#claude-code). The hook is the enforcing surface; the MCP tools, the CLI and the other clients
advise ([integrations.md](integrations.md)).

## The plugin

The plugin brings four things:

- **a hook** (`hooks/hooks.json`) on `PreToolUse` for messages that leave the session (`SendMessage`)
  and on `Stop`; [`examples/hooks/projects.json`](../examples/hooks/projects.json) adds matchers for other reply tools.
  On `FAIL` it returns the report to the model with the reasons, before anyone reads it. Since 0.6 it
  also counts live subagents (`SubagentStart`/`SubagentStop`); when none is left, the orchestrator is asked once for
  a summary built by code and a choice card for the next steps, and the person's pick (`AskUserQuestion`) goes to the
  journal, where the anchor `choice:<id>=<step>` is checked;
- **an MCP server** (stdio, no SDK): `verify_report`, `snap`, `source_text`, `summary`;
- **skills**: [`skills/buddie`](../skills/buddie/SKILL.md) for executors and orchestrators,
  [`skills/verbatim`](../skills/verbatim/SKILL.md) for quoting from snapshots;
- **commands** you run yourself: `/buddie:check [file or text]` checks a text now (your last answer by default),
  `/buddie:status` shows what is checked in this project and what was returned lately, `/buddie:init` turns on the
  project's full checks (`buddie.toml`, starting in intro mode).

The hook runs through `hooks/run.sh`, which starts the first of `python3`, `python` and `py -3` that is Python 3.11+,
so it works on Linux, macOS and Windows (Claude Code runs hooks there in Git Bash).

Optional setting: a GitHub token for `pr:`/`ci:` anchors (the plugin asks for it and stores it as a secret; it is
sent only to api.github.com, or to the GitHub API an administrator's protected policy names: never to one the
environment names). Without it GitHub allows 60 lookups an hour and private repos can't be checked.

The same destination restriction applies to the explicit `BUDDIE_GITHUB_TOKEN` used by CLI and CI. An
environment-configured `BUDDIE_GITHUB_API` receives no token. For authenticated GitHub Enterprise, an administrator
sets `[evidence] github_api = "https://github.example.com/api/v3"` in the
[protected system policy](policy.md); do not put this grant in project `buddie.toml`. Invalid policy or an unsafe
endpoint fails closed. The policy's owner must trust that endpoint, its TLS and any configured proxy.
The plugin option takes precedence when both token names are present. Clear the option or unset the environment
variable to avoid authentication; revoke the token in GitHub settings to invalidate it.

The plugin starts `run.py serve` and the checked-in hook launcher locally; it does not download code during
startup. Python 3.11+ and, for hooks, a POSIX shell must already be installed. Optional browser access is installed
only when you choose it and is not required for basic operation. See [privacy and credential flows](../PRIVACY.md).
For the Directory audit and remaining packaging review items, see [compliance audit](claude-directory-audit.md).

Without Claude Code: `python3 run.py verify REPORT.md --repo .` from a clone works without installing anything.

## Levels and the intro mode

At `Stop`, the answer is already displayed and cannot be retracted. A failed verification asks the agent for
corrected lines without repeating that answer. Supported `PreToolUse` message checks still run before delivery.

**Right after installing** (no `buddie.toml` in the repo), the hook returns an answer only for what is false: a
quote that is not on the page it links to, or an anchor that does not hold. An answer with no quotes and no anchors
passes untouched, and so does one whose source could not be read. Numbers of cited sentences that are not on their
page only warn. Asking for anchors on every final answer, prose about work and the context limit are a project's
choice, made with `buddie init`.

`buddie init` writes `buddie.toml` in the repo with the default level of each class of claims and turns the intro
mode on. Each class is `block` (the text goes back to the model), `warn` (the text leaves; you see what the gate would
have said) or `off`:

| Class | What | With `buddie.toml` | Without |
|---|---|---|---|
| `anchors` | a broken anchor: `path@commit`, `path#sha256`, `pr:`, `ci:`, `run:` | `block` | `block` |
| `quotes` | a quote not on its source | `block` | `block` |
| `final` | a final answer with no anchor, or a count line without one | `block` | `off` |
| `prose` | work claimed in prose ("merged", "tests passed") with no anchor on the line | `warn` | `off` |
| `numbers` | a number of a cited sentence not in its source | `warn` | `warn` |
| `work` | a claim about the work queue that does not hold (`[mandate]`) | `block` | `block` |
| `summary` | return a `Stop` once for the summary of the subagents' results | `off` | `off` |
| `promises` | return a `Stop` for a promise whose condition holds | `off` | `off` |
| `context` | a reply or a subagent launch past the context limit (`BUDDIE_CONTEXT_LIMIT`, 200k) | `block` | `off` |

```toml
[gates]
prose = "block"

[intro]
finals = 20
```

In the intro mode nothing is returned: each would-be return is a warning that says what it would have returned. It
ends by itself after `finals` final answers with no false return reported; `buddie intro --false` reports one and
restarts the count, `buddie intro` shows where it stands, `buddie enforce` ends it now. Without `buddie.toml` the
"Without" column applies and there is no intro: nothing that is merely unanchored is returned, so there is nothing
to get used to.

## The loop

The hook also learns from its own returns; none of it is written by the model:

- **How the gate was passed.** A return logs `reasons`; the next attempt of the same tool in the session logs `gate`:
  per flagged line `proved`, `removed` or `kept`, and the way through (`proof`, `removal`, `mixed`, `disclosure`,
  `returned`).
- **Lessons at start.** On `SessionStart` the hook prints a summary of past sessions' journal: how many messages came
  back, for what, and the shape of a line that passes (at most ten lines).
- **Ready anchors.** A return offers `pr:`, `ci:` and `run:` anchors that already hold (checked now), to copy onto the
  line instead of rewording it.
- **Measure.** `buddie journal measure --sessions 10`: the share of sessions whose first checked message passed, and
  how returns were passed (proof vs removal).
- **Context gate.** Past `BUDDIE_CONTEXT_LIMIT` tokens of context a non-final reply is returned with a reminder to hand
  the result over; final answers, hand-offs to another session and `Stop` are never held.

## The transcript and the journal

**The transcript.** The hook reads the current session's transcript (`transcript_path`, and its subagents' files next
to it) because a claim about a command can only be checked against what the session actually ran:
`⚓ run:pytest -q => 41 passed` holds only if the transcript shows that call with that output. It also takes the
token count for the context gate, snapshot stores the session named, and the commands behind ready anchors from
there; the final answer at `Stop` comes from the event itself (`last_assistant_message`), and from the transcript only
when the event has none. It reads the file in place; nothing from it is copied into the journal or sent anywhere. No
other session, no memory, no chat history is read. To turn it off, set the plugin's "Read the session transcript"
option to off, `BUDDIE_TRANSCRIPT=0`, or `[transcript] read = false` in `buddie.toml`: answers are still checked,
and `run:` anchors are reported as unchecked.

**The journal.** Each check appends one line to `BUDDIE_LOG` (`~/.cache/buddie/hook.jsonl`): time, session id, tool,
outcome, counts of verdicts, exit code and the SHA-256 of the checked text. It never holds the text. Promise lines
(«launch №N after PR #M») keep the row, the condition and the sentence's SHA-256; choice lines (the person's pick on a
summary card or an `ask_decision` card) keep hashes of the picked steps and the numbers of a typed answer, and a
decision card line keeps its options' label hashes and queue numbers, which is enough for `choice:<id>=<step>` to be
checked. `[journal] text = true` in `buddie.toml` (or `BUDDIE_JOURNAL_TEXT=1`) also keeps
those sentences and answers. `BUDDIE_LOG=0` turns the journal off; lessons at `SessionStart` then have nothing to sum.

What is read, sent and kept, in full: [PRIVACY.md](../PRIVACY.md).
