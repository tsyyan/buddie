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
| Windows | `<ProgramData>\buddie\policy.toml` | the file and every directory above its real path are owned by SYSTEM, Administrators or TrustedInstaller. No ACE that applies to them lets Everyone, Authenticated Users, Users, INTERACTIVE, Guests, OWNER RIGHTS or this user change or replace them. When the hook is not elevated, `AccessCheck` with its own token agrees (`buddie/winacl.py`) |

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

On Windows, an administrator who creates `%ProgramData%\buddie` from an elevated shell gets Administrators as its
owner, and ProgramData's default ACL lets Users read the file and add new files to the directory. Neither lets them
replace the file. If the owner comes out as a single account instead (some tools set the creating user), fix it:

```bash
icacls "%ProgramData%\buddie" /setowner *S-1-5-32-544 /T
```

Deny ACEs are not subtracted, so a file can be judged unprotected when it is in fact protected, never the other way
round. Only plain allow and deny ACEs are read: an allow ACE of any other type that applies to the file or a directory
above it (object, callback or conditional, compound) makes the policy *invalid*, as does anything else the check
cannot read or decide. Protection is established or not claimed. The default ACLs of `%ProgramData%` and the
system directories carry only plain ACEs.
An elevated hook (an administrator's token) is outside the threat model, as root is on POSIX. For it, only the owner
and the ACL are judged.

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

The hook reads the policy once per event (`policy.snapshot()` in `hook.main`). The gate, the return state, the free
command and the journal's words all judge by that one reading, even if the file is replaced during the event. The CLI
reads it anew on each command.

## A trusted launcher

Claude Code runs the plugin's hook as `sh "${CLAUDE_PLUGIN_ROOT}/hooks/run.sh" hook`. What that launcher can and
cannot promise:

- **It finds Python on `PATH`.** A project's `.claude/settings.json` can set `PATH` for hooks, so an agent can put
  its own `python3` first, one that always succeeds. The launcher cannot tell, and neither can the protected policy,
  which takes Python to read.
- **It runs Python isolated (`-I`)**, for the version probe as well as for buddie. `PYTHONPATH`, `PYTHONSTARTUP` and
  the user's site-packages, which project settings can also set, load no code into it. Optional modules installed
  only in the user's site-packages (brotli) are therefore not used by the hook.
- **Without Python 3.11+ it does not pass the answer as checked.** A Stop's answer goes back once with the reason
  (exit 2). The Stop that Claude Code re-enters with (`stop_hook_active`) goes on, and a `systemMessage` tells the
  person the answer was not checked, so this never loops. Other events go on with the reason on stderr. This is an
  observable failure, not enforcement: the shell launcher does not read the protected policy and cannot know
  whether one is installed.
- **The plugin's own files are the user's.** A plugin installed under the user's home can be edited by the agent,
  `run.sh` and buddie's code included.

Enforcement that does not depend on the agent's reach needs all of these at once:

1. buddie installed where only an administrator can write. For example, `sudo pip install buddie==<version>` into a
   system Python, or a root-owned checkout in `/opt/buddie`.
2. A hook command with absolute paths for the interpreter and buddie, such as
   `/usr/bin/python3 -I /opt/buddie/run.py hook`, defined in Claude Code settings the agent cannot edit. Check your
   Claude Code version's documentation for its administrator-managed settings and how they take precedence over
   project settings. buddie cannot verify that from inside a hook.
3. The protected policy.

The plugin as distributed gives observable failures and the policy's limits within its threat model. It does not give
that guarantee.

## What it does not cover

- **The hook's own launch and code**: see "A trusted launcher". A replaced `python3` on `PATH`, or edited plugin files,
  bypass buddie entirely. The policy cannot see them.
- **Where evidence comes from.** `BUDDIE_REPOS` (which checkouts anchors are judged against), `VERBATIM_STORE` and
  `BUDDIE_STORES` (which snapshots quotes are judged against) and `BUDDIE_LOG` come from the hook's environment, which
  the agent can set. They cannot turn an unchecked claim into a checked one: a missing repo or snapshot is a gap. But
  they choose the evidence a claim is judged on, and an agent that controls a store controls what "found" means.
  Authorizing evidence sources is planned for PR #29.
- **buddie's state and journal** live under the user's home directory, which the agent can write. An agent that
  forges the return state can make a pre-written `buddie:` line count as written after a return. A policy with
  `disclosure = false` closes that path: then only a fix lets a returned answer out.
- **A root or administrator agent** is outside this model. It can write the policy too.
- **CLI and MCP calls** produce receipts and do not block, so the policy does not change them. A receipt reports what
  was checked, whatever the policy says about gating.
