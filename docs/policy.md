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
  - Under a policy, only its own `free_command` is run. With or without one, the command gets the hook's
    environment without the plugin's settings and buddie's tokens, and its process tree is stopped after 20
    seconds ([security.md](security.md)).
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

## Evidence

A check is only as good as what it is judged on. The hook takes evidence from places it is told about, and the
agent can tell it about most of them:

| Variable | What it chooses | Who can set it |
|---|---|---|
| `BUDDIE_REPOS` | the checkouts `path#sha256` and `path@commit` are judged against | the hook's environment |
| `VERBATIM_STORE`, `BUDDIE_STORES` | the snapshot stores quotes and numbers are judged against | the hook's environment |
| (none) | stores the session named in its tool calls, `./.verbatim`, `sources/` the repos changed | the session itself |
| `BUDDIE_LOG`, `BUDDIE_SHARED_LOG` | where the journal goes, or that it is off | the hook's environment |
| `HTTPS_PROXY` and friends, `SSL_CERT_FILE`, `SSL_CERT_DIR` | who stands between the hook and a page or GitHub | the hook's environment |
| `BUDDIE_GITHUB_API` | which server answers `pr:` and `ci:` (and receives the token) | the hook's environment |

None of these is a person's decision, so none is taken as one once the policy's `[evidence]` table says so:

```toml
[evidence]
repos = "event"          # only the git checkout around the event; BUDDIE_REPOS is set aside
stores = "observed"      # quotes and numbers judged only on bytes the hook fetches in this check
journal = "fixed"        # ~/.cache/buddie/hook.jsonl (and the cloud's shared folder); BUDDIE_LOG=0 does not turn it off
collector = "isolated"   # the hook's fetches go direct, TLS verified without SSL_CERT_FILE / SSL_CERT_DIR
github_api = "https://github.example.com/api/v3"   # GitHub Enterprise only; BUDDIE_GITHUB_API is set aside
```

**Each key left out keeps the behaviour without a policy** (`"environment"`, `"session"`, no `github_api`). That is
different from the keys above, whose defaults are restrictive, and it is deliberate: a policy written before
`[evidence]` existed decides exactly as it did. `buddie policy template` writes the restrictive values, except
`stores`, which stays `"session"` because `"observed"` changes results (below). Refusals are journaled by name:
`evidence.repos`, `evidence.stores`, `evidence.journal`, `evidence.collector`, `evidence.github_api`.

What each key guarantees, and what it does not:
- **`repos = "event"`** makes anchors be judged against the checkout the session is in, not a decoy that makes them
  hold. The checkout is still the agent's to write: a file it edits, it can make match. The change then shows in
  that repo's own diff, where the person looks.
- **`stores = "observed"`** is the one that closes forged snapshots. Every snapshot store on the machine is a
  directory the agent can write, and a snapshot is only bytes with a hash: a hash names bytes, not who served them.
  With `"observed"` the hook makes an empty store for the check, fetches each cited page itself, and deletes the
  store afterwards, so a quote is found only if the page says it now. The cost: a page that changed since it was
  quoted, or that refuses the hook, is a gap (`NOT_FOUND` or `SOURCE_UNAVAILABLE`), where a session snapshot would
  have held. With `BUDDIE_FETCH=0` or `network = "forbidden"` nothing is fetched and every quote is a gap, never a
  pass.
- **`journal = "fixed"`** keeps the record where the person looks for it and keeps the hook's environment from
  turning it off. It does not make the journal tamper-evident: the agent can edit a file in the user's home.
- **`collector = "isolated"`** makes the hook's own fetches (pages, GitHub) ignore proxies from the environment and
  from the user's system settings, and the CA locations the environment names, so a local proxy cannot answer for
  a site. TLS is verified against the system's CA store as installed (see "The collector's scope"), which on
  Windows includes the user's own root store; a CA the person was prompted to add there is trusted. `http://`
  pages are not authenticated by anyone. An installation that needs a proxy to reach the web cannot use
  `"isolated"`.
- **`github_api`** fixes the server `pr:` and `ci:` are asked of, and where either token may be sent (below).

### The GitHub token

`github_get` sends a token only where it belongs:
- `BUDDIE_GITHUB_TOKEN` comes from the hook's environment, as `BUDDIE_GITHUB_API` does, so it may go to that API.
- The plugin's token setting (`CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN`) is the person's. It goes only to
  `api.github.com` or the policy's `github_api`, never to an API the environment named: otherwise an agent could
  name its own server and receive it. A GitHub Enterprise installation that uses the plugin setting names its API
  in the policy.
- The token is an unredirected header, which urllib never copies to a redirect's target. An answer from another
  origin than the API's (scheme, host and port) is not taken, and the anchor stays unchecked. A redirect on the
  API's own origin (a renamed repo) is asked again there, with the token.
- Requests go through the opener installed in the process: the remote server's guarded one, the hook's isolated
  collector, or urllib's default.

### Provenance

Separately from the policy, buddie records how far each finding's evidence is known (`core.Provenance`, internal:
receipt-v0 does not change, and no verdict or gate decision depends on it).

*Collector observed* means one thing: buddie's own collector received these bytes during this check, over TLS,
from the endpoint buddie chose, with nothing the environment set in between for the whole check. It says who
answered. It does not say the answer is true, and a page can be observed and wrong.
- **A snapshot** is observed only when this check's `Store.fetch` asked the cited `https://` URL and the response
  ended on `https://`. Everything else is *unknown*: snapshots already on disk (whatever their index says), bytes a
  caller `add()`ed, plain `http://` pages (anyone on the path may have answered), and copies from the access
  cascade (archives, relays, a browser, which take other routes). For a redirected page, the host that answered is
  the one the request ended at; buddie does not judge the redirect chain. Only what buddie's own store classes
  (`Store`, `UnionStore`) fetch during the check counts: a subclass a caller hands in may record any bytes as
  fetched, and a store's `collected` set filled before the check proves nothing.
- **A `pr:`/`ci:` answer** is observed only when buddie's own `github_get` asked it, not a function a caller handed
  in, of `api.github.com` or the policy's `github_api`, with the network clean for the check. With
  `BUDDIE_GITHUB_API`, a proxy or a CA override from the environment, or a caller's function, it is *caller
  supplied*. A policy's `github_api` counts as observed because the administrator named it: buddie trusts the
  administrator's choice of endpoint, not anything about the endpoint itself.
- **Which callback is buddie's own** is decided by identity, never by anything the callback carries:
  `effects.github_get` itself, or a wrapper buddie's own code registered (`remote.public_github`, which only filters
  `github_get`'s answers). Handing verify a callback, whatever its attributes, adds nothing to that list. Code that
  runs inside buddie's interpreter could still change buddie itself; that is outside what provenance can describe.
- **"Nothing in between"** is judged before and after the check (`evidence.network_clean`). Both must hold, so a
  collector that another thread starts or ends meanwhile cannot make an unclean fetch look clean.

### The collector's scope

The isolated collector changes urllib's opener for the whole process while it is active: every urllib request of
the process goes direct and verifies TLS against the system's CA store. The hook runs one process per event, so that
scope is the event. Collectors nest and may overlap across threads. The first to start installs the opener, the
last to end restores the one before, under a lock, after an exception too. Two overlapping collectors share one
isolated opener. The CA store is built from OpenSSL's compiled-in file and directory, and on Windows the system's
CA and ROOT stores; `SSL_CERT_FILE` and `SSL_CERT_DIR` are never read, and `os.environ` is never changed for it.
Not covered:
- `OPENSSL_CONF` and similar variables that OpenSSL reads when it starts;
- a CA in the user's own Windows root store;
- a Python interpreter installed where the agent can write (see "A trusted launcher").

## Environment diagnostics

`[environment] allow = [...]` is the ceiling on what the person's grants may open for environment diagnostics
([environment.md](environment.md), "Diagnostics"): category ids, or `"baseline"` for the low-sensitivity ones. An
ACTIVE policy without the table allows none, as for every other grant of collection; an INVALID policy allows none.
It only narrows: a category the person did not grant stays denied whatever the policy lists. An unknown category id
makes the policy INVALID. `roots` bounds the directories the path-scoped categories (`hardware.storage`,
`development.project`, `development.repository`) may read, on top of the person's grants file, which the agent can
edit; without it an active policy lets them read none.

```toml
[environment]
allow = ["baseline", "development.project"]
roots = ["/home/alice/projects"]
```

## What it does not cover

- **The hook's own launch and code**: see "A trusted launcher". A replaced `python3` on `PATH`, or edited plugin files,
  bypass buddie entirely. The policy cannot see them.
- **Local evidence is never trusted**, with or without `[evidence]`: repos, session snapshots, the journal and the
  session transcript (`run:`, `choice:`) are files the agent can write. `[evidence]` controls who *chooses* them and
  lets quotes be judged on fresh fetches; it does not make a local file the person's word.
- **buddie's state and journal** live under the user's home directory, which the agent can write. An agent that
  forges the return state can make a pre-written `buddie:` line count as written after a return. A policy with
  `disclosure = false` closes that path: then only a fix lets a returned answer out.
- **A root or administrator agent** is outside this model. It can write the policy too.
- **CLI and MCP calls** produce receipts and do not block, so the policy does not change them. A receipt reports what
  was checked, whatever the policy says about gating.
