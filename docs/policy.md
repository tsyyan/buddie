# Protected policy

buddie checks what an AI agent hands in. The agent runs as the same operating-system user as buddie's hook, so
anything that user can write is the agent's to change: the repo's `buddie.toml`, the hook's environment (Claude Code
passes a project's `.claude/settings.json` `env` to hooks), the plugin's options, buddie's own journal and state. None
of these can tell buddie that *a person* decided something.

The protected policy is a file only an administrator can write. While it is in force, nothing the agent can write
weakens what it requires.

## Where it lives

| System | Path | Protected when |
|---|---|---|
| Linux, macOS | `/etc/buddie/policy.toml` | owned by root and not writable by group or others, and the same holds for every directory above its real path |
| Windows | `<ProgramData>\buddie\policy.toml` | this user cannot open it for writing through its ACL. A read-only attribute alone does not count, because its owner can clear it |

The path is fixed in code. No environment variable or argument moves it. On Windows, buddie asks the system for
ProgramData (`SHGetFolderPathW`) instead of reading `%ProgramData%`, which a process can set.

buddie never writes the file. To install one:

```bash
buddie policy template > policy.toml
```

```bash
sudo install -d -o root -m 0755 /etc/buddie
```

```bash
sudo install -o root -m 0644 policy.toml /etc/buddie/policy.toml
```

On Windows, copy it from an elevated shell into `%ProgramData%\buddie\`. To check it from any shell:

```bash
buddie policy check
```

```bash
buddie policy show
```

`check` exits 1 when the file is there but cannot be used. `show` lists the effective levels for the repo around
the current directory and what the policy refused there. To change or remove the policy, edit or delete the file
with the same rights. It takes effect at the next hook run, because buddie keeps no copy of it.

## What it says

```toml
version = 1
transcript = "project"     # "required" | "forbidden" | "project"
journal_text = "forbidden" # "forbidden" | "project"
disclosure = true          # may a `buddie:` line let a returned answer out (after the return)
network = "allowed"        # "allowed" | "forbidden"
# final_mark = "…"         # the policy's own final mark
# free_command = "…"       # the launch gate's free command; BUDDIE_FREE is ignored under a policy

[gates]                    # floors: the weakest level a lower source may set, per class
anchors = "block"
quotes = "block"

[project]                  # what buddie.toml and the hook's environment may still decide
intro = false
final_mark = false
state = false
```

The rules:
- **A floor is a minimum.** `buddie.toml`, `BUDDIE_GATES` and plugin options may set a class to a stricter level,
  never to a weaker one. A weaker setting is raised to the floor and logged as refused.
- **What the project may not decide is the policy's.** With `[project] intro = false`, an `[intro]` section in
  `buddie.toml` does not turn returns into warnings. With `final_mark = false`, neither `[mandate] final_mark` nor
  `BUDDIE_FINAL` can change which answers count as final, including an empty mark that turns the final rule off.
  With `state = false`, `BUDDIE_STATE=0` does not stop buddie from telling a `buddie:` line written before a return
  from one written after it.
- **Nothing below the policy grants collection or execution.**
  - `journal_text = "forbidden"` keeps conversation words out of the journal, whatever `buddie.toml` or
    `BUDDIE_JOURNAL_TEXT` say.
  - `transcript = "forbidden"` keeps the session log closed, and `"required"` keeps it open.
  - Under a policy, only its own `free_command` is run.
  - `network = "forbidden"` stops page fetches and GitHub lookups.
- **The policy never makes buddie more permissive than it is without one.** If a policy somehow appeared that its
  administrator did not write, the worst it could do is leave things as they would be with no policy at all.

Every key is checked. An unknown key, a value outside its list, an unknown `version` or a `final_mark` that is not a
regular expression makes the whole file unusable. A key that does not do what its author meant must not pass
unnoticed.

## Its three states

| State | When | What buddie does |
|---|---|---|
| absent | no file | as before 2.0: `buddie.toml` and the environment decide, unprotected |
| active | a protected, valid file | the limits above apply |
| invalid | a file that is there but not protected, unreadable, not UTF-8, not TOML, or not a valid policy | buddie runs on its strictest limits: every class that judges a claim blocks, nothing is granted to lower sources. The gate returns each answer with the reason. A `buddie:` line after that return tells the reader and lets the answer out, unless the policy could have forbidden that: an invalid policy keeps `disclosure` on so a session is not stuck |

An unconfigured installation is *absent*, not *invalid*. Nothing changes for it.

## Who can set what

| Source | Trust | Examples | Under an active policy |
|---|---|---|---|
| protected policy | highest | `/etc/buddie/policy.toml` | sets floors and what the rest may decide |
| transport | | the remote server's dropped arguments and Budget | unchanged |
| hook environment, plugin options | the person's, *and reachable by the agent through project settings* | `BUDDIE_GATES`, `BUDDIE_FINAL`, `BUDDIE_STATE`, `BUDDIE_FREE`, `CLAUDE_PLUGIN_OPTION_*` | within the policy's limits |
| call arguments | the caller's: a person at a CLI, or the agent through an MCP tool | `--anchors-only`, `numbers`, `repos` | unchanged: CLI and MCP produce receipts, they do not gate |
| buddie's defaults | | `DEFAULTS`, `ZERO_CONFIG` | below the floors |
| repo | lowest, agent-writable | `buddie.toml` | within the policy's limits |

Runtime observations (a page's text, a tool's result, a model's message, a `buddie:` line) never set policy. A
`buddie:` line is a disclosure to the reader, not a permission.

## What it does not cover

- **The hook's own launch.** `hooks/run.sh` finds Python on `PATH`, and a project's settings can change `PATH`. An
  agent that replaces `python3` with a program that always succeeds bypasses buddie entirely. Only the person's
  Claude Code settings outside the project, or a managed installation, can rule that out.
- **buddie's state and journal** live under the user's home directory, which the agent can write. An agent that
  forges the return state can make a pre-written `buddie:` line count as written after a return. A policy with
  `disclosure = false` closes that path: then only a fix lets a returned answer out.
- **A root or administrator agent** is outside this model. It can write the policy too.
- **CLI and MCP calls** produce receipts and do not block, so the policy does not change them. A receipt reports what
  was checked, whatever the policy says about gating.
