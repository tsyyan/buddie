# Security: execution boundaries

buddie runs a few programs: git (anchors, the work queue, the session's stores, environment snapshots), a command
the person names for the launch gate, `pdftotext` for PDF pages, and `certutil` for the browser access mode. This
page says who controls each, what each could be made to do, and what buddie does about it. The protected policy and
evidence provenance are in [policy.md](policy.md) and [architecture.md](architecture.md).

## Who controls what

The agent under check runs as the person's OS user. Everything that user can write is the agent's: the repository,
its `.git` (config, index, hooks, objects), the user's own git configuration, buddie's state and journal, and the
hook's environment (Claude Code passes a project's `.claude/settings.json` `env` to hooks). The process running
buddie may hold what the agent does not: the plugin's GitHub token (`CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN`), given to
the hook and to the plugin's MCP server. Only the protected policy, a file the agent cannot write, is the person's
own word.

**Trusted base.** The Python that runs buddie and the git, `pdftotext` and `certutil` that PATH finds are part of
the host's trusted base: a hook's PATH is resolved before buddie runs, and a host that lets the agent set the hook's
PATH has handed it the hook. buddie does not pin executables; keep the agent from writing the hook's environment
(Claude Code's managed settings) where that matters.

## Execution-boundary audit

| Path | Executable | Arguments | Environment | Working directory | Config the child reads | Secrets in the parent | Can start programs | Network | Bounded (output, time, tree) | On failure |
|---|---|---|---|---|---|---|---|---|---|---|
| `stores.changed_sources` (hook: the session's `sources/` stores) | git from PATH | fixed | **before:** the hook's, whole. **Now:** git's own (below) | `-C repo` | **before:** system, global, repo (filters, fsmonitor run). **Now:** repo only, with every command it names off | the plugin's token | **before: yes** (SEC-01). **Now:** no | **before:** a partial clone could fetch. **Now:** no protocol | **before:** 20 s, output in memory. **Now:** 20 s, streamed with a cap, tree stopped | **before:** an empty list, silent. **Now:** what was found and why the rest is missing, said and journaled |
| `anchors._git` (`path@commit`), `anchors.find_repos` | git | fixed | **before:** inherited (GIT_DIR steered the repo, SEC-08). **Now:** git's own | `-C repo` | repo | the token | no command of the repo's runs (probed, below) | no | **before:** no timeout. **Now:** 10 s, bounded | **before:** a timeout on the second question was BROKEN. **Now:** UNCHECKABLE |
| `mandate.read` (`git show REV:PATH`), `Mandate.appeared` (`git log`), `_missing_rev` | git | fixed (REV from the text, as one argv item) | as above | `-C repo` | repo | the token | no | no | **before:** none, unbounded output. **Now:** 10 to 30 s, 16 MiB | **before:** git failing was "no commit" (BROKEN). **Now:** UNCHECKABLE |
| `promises` (`rev-parse`, `show -s`, `log --grep`, `remote get-url`) | git | fixed | as above | `-C repo` | repo | the token | no | no | **before:** none. **Now:** bounded | an absent answer |
| `environment` (snapshots, #33) | git | fixed | git's own (from #33) | `-C root` | repo, filters and fsmonitor off | the token (CLI, API) | no | no | **before:** a consumer's output had no cap (SEC-02), a timeout could wait on a pipe a child held (SEC-03). **Now:** bounded | `unavailable` with a reason |
| `promises.free_now` (the launch gate's free command) | the system shell | **the command line**: the protected policy's `free_command`, or without a policy `BUDDIE_FREE` (the hook's environment: a project can set it) | **before:** the hook's, the token in it (SEC-09). **Now:** the hook's without buddie's credentials | the repo | whatever the command reads | the token | yes, by design: it is a command | yes, by design | **before:** 20 s, but on Windows the wait after the kill was unbounded. **Now:** 20 s, tree stopped | no answer: not free |
| `patterns` worker (PR #36): `buddie.toml` `[mandate]` patterns | the Python running buddie (`-I`) | fixed: the worker's code; each request a pattern and a text as JSON | buddie's without credentials | default | none | the token | no | no | 1 s per match, 10 s per hook event, killed past it | `PatternTimeout`: the gate returns the answer |
| `verbatim.textlayer.pdf_text` | `pdftotext` from PATH | fixed, a temporary file | **before:** inherited. **Now:** without buddie's credentials | default | its own | the token | no | no | 120 s (or the check's budget), output file capped | the page is unreadable (a gap) |
| `verbatim.access._trust_extra_ca` (browser mode only) | `certutil` from PATH | fixed, `VERBATIM_BROWSER_CA` | inherited | default | NSS db | — | no | no | none | ignored |

The free command is a command by design: the person names it (with a policy, only the policy's own), and it may do
what the person's tools do. What changed is that it no longer receives the plugin's token, and cannot hold the hook.

## Findings

| Id | Finding | Attacker needs | Boundary crossed | Severity | Status |
|---|---|---|---|---|---|
| SEC-01 | The hook's `git status` (session stores) ran commands the repository's config names (a filter's `clean`, `core.fsmonitor`) in the hook's environment, so they read the plugin's GitHub token | write access to the repo's `.git/config` (the agent has it) | agent code runs with the person's credential | **high** | **fixed** |
| SEC-02 | `environment._run` with a consumer had no output cap; `_Hidden` buffered an entry with no end without bound | a repository with a huge or malformed index | memory and time of the checker | medium | **fixed** |
| SEC-03 | A timeout killed only the direct child: a grandchild holding the output pipe kept the reader alive; the free command's timeout on Windows waited for the pipe without bound; nothing bounded an event's git calls together | a repository (or free command) whose programs stall | a hook held past the host's timeout lets the answer out unchecked | medium | **fixed** |
| SEC-04 | Every git buddie ran outside snapshots inherited the hook's environment (`GIT_CONFIG_*` could switch on fsmonitor anywhere; `GIT_EXTERNAL_DIFF`, `GIT_SSH_COMMAND`, …) and the user's global configuration | the hook's environment (a project's settings) | as SEC-01 | high (same impact as SEC-01) | **fixed** |
| SEC-08 | `GIT_DIR` (and `GIT_WORK_TREE`, `GIT_OBJECT_DIRECTORY`, …) in the environment chose the repository git read: a commit only an agent-made repository has made `path@commit` hold, past `repos = "event"` | the hook's environment | the protected policy's evidence selection | medium | **fixed** |
| SEC-09 | The free command (without a policy, from `BUDDIE_FREE`, which a project can set) ran in the hook's environment with the plugin's token | the hook's environment | agent-named command with the person's credential | **high** | **fixed** |
| SEC-10 | A git that did not answer (timeout, missing, an unreadable repository) was taken as an answer: `path@commit` BROKEN, a queue at a commit BROKEN ("no commit") | a slow or unreadable repository | a false contradiction (the answer goes back), never a false pass | low | **fixed** |
| SEC-11 | `pdftotext` (bytes from the web) got the token in its environment | a PDF exploiting pdftotext | trusted base | low | **fixed** (environment without credentials) |
| — | `certutil` adds `VERBATIM_BROWSER_CA` to the user's NSS database (browser mode only, CLI or MCP `access`) | the environment of the CLI or MCP server | the user's own NSS trust, which the agent can change itself | informational | deferred, documented |
| — | PATH chooses Python and git | the hook's environment | the trusted base | informational | documented above (host's to protect) |

Reproductions are in `tests/test_security_hardening.py`. Each runs what buddie ran before (the same git command,
the same inherited environment), shows it succeed, and shows the hook path (for SEC-01, the hook as Claude Code starts
it, `run.py hook` with a Stop event, the token in its environment) run nothing, disclose nothing, still find the
ordinary changed store, and not turn a store it could not list into a PASS.

## How git runs now (`buddie/runner.py`)

- **Environment.** `PATH`, and on Windows `SYSTEMROOT` and `WINDIR`, and git's own settings: `GIT_CONFIG_NOSYSTEM=1`,
  `GIT_CONFIG_GLOBAL` the null device, `GIT_ATTR_NOSYSTEM=1`, `GIT_OPTIONAL_LOCKS=0` (git status does not write the
  index), `GIT_TERMINAL_PROMPT=0`, `GIT_ALLOW_PROTOCOL=none` and `GIT_NO_LAZY_FETCH=1` (no fetch), and
  `GIT_NO_REPLACE_OBJECTS=1`. No other variable of buddie's: no token, no `GIT_DIR`, no `GIT_CONFIG_*`, no proxy.
- **Configuration.** The repository's own, and from the system and global configuration only the person's
  `safe.directory` entries, passed as `-c safe.directory=…` (read with `git config --system/--global --get-all`,
  which runs nothing), so a checkout another user owns that the person allowed is still read. A repository's own
  `safe.directory` is ignored, by git and here.
- **Switched off on the command line** (which wins over every config file): `core.fsmonitor`, the untracked cache,
  `core.ignoreStat`, implicit bare repositories, signature display; and for `git status` every filter driver the
  repository's config names (`clean`, `smudge`, `process`; found with `git config --get-regexp`, includes followed).
  A driver whose name cannot be passed that way (it holds `=`) means git status is not run.
- **Bounds.** 10 seconds per command (20 for git status, 30 for history), at most 1 MiB of output kept or 64 MiB
  streamed to a consumer that keeps only what it needs, the program's whole tree stopped at the end (a process group
  on Linux and macOS; a job object on Windows, which ends a process left in it once git exits), and every git and
  the free command of a hook event within one budget of 40 seconds: the gating hooks have 60 to 120 before the host
  stops them. (`pdftotext` keeps its own timeout, under the check's fetch budget.)

What buddie's git commands reach was probed with a repository configured to run a marker for each mechanism
(filters, fsmonitor, textconv, external diff, signature verification, pager, hooks, an alias over a builtin, ssh, a
credential helper) and the environment adding `GIT_EXTERNAL_DIFF`, `GIT_PAGER`, `GIT_SSH_COMMAND` and
`GIT_CONFIG_*`. Before: `git status` ran the clean filter and fsmonitor, `git ls-files -v` ran fsmonitor, and the
environment's `GIT_CONFIG_*` reached every command. Now none runs (one test per command). Textconv, external diff
and signature verification were not reached by these commands; aliases cannot override a builtin; no command buddie
runs uses hooks, ssh or credential helpers. They are not claimed dangerous here, and the ones reachable are off.

## Behaviour that changed

- **The session's `sources/` stores.** Listed by git status as before (now `-z`, without rename detection, without
  submodules: git status in a submodule would read the submodule's own config). When they cannot all be listed
  (git missing or not answering, a filter that cannot be switched off), the hook says which repo and why when it
  returns quotes, and the journal line carries `stores_unavailable`. A directory that is not a repository has
  nothing to list, as before. A quote whose store was not found is judged on the others or fetched: a gap or a
  failure, never a pass it would not have had.
- **System and global git configuration** no longer apply to buddie's git, except `safe.directory`: `core.autocrlf`
  from them, git-lfs filters installed globally and the like do not run. For git status this errs towards a file
  shown changed. Anchors and history read objects, which they do not change.
- **A git that does not answer** is `UNCHECKABLE`, never `BROKEN`.
- **The free command** runs without `CLAUDE_PLUGIN_OPTION_*`, `BUDDIE_GITHUB_TOKEN` and `BUDDIE_HTTP_TOKEN`; the rest
  of the environment is as before. Its process tree is stopped after 20 seconds on every system.
- **One more git call per Stop** in a repository: the listing of filter drivers before git status.
- Nothing else: receipts v0 and v1, the 819 gate scenarios, profiles, the protected policy, the CLI's exit codes, MCP
  and the remote server are unchanged.

## Environment diagnostics

`buddie snapshot --category` and the MCP tool `environment_snapshot` start programs to describe the machine (versions,
GPU, containers). They follow the rules above and some of their own ([environment.md](environment.md#diagnostics)):
only methods the category declares, fixed argument lists, an allowlisted environment (no tokens, `*_OPTIONS`,
`LD_PRELOAD`, `DYLD_*`, `DOCKER_HOST`), the system's temporary directory as working directory, `PATH` searched by
buddie with absolute entries only, batch and PowerShell scripts not run, a deadline and a program budget per request,
only version- or model-shaped output kept. What is collected is decided by the person's grants and the protected
policy, never by the request. The grants file is the user's and so writable by a same-user agent: it states intent,
it is not a barrier. Only a protected policy is a ceiling such an agent cannot raise, and without one there is no
independent boundary ([environment.md](environment.md#diagnostics), "What each of these is worth against an agent").

## Remaining limits

- **Process trees.** A program that leaves its process group (Linux, macOS: a new session) or starts a child before
  it is put in its job (Windows: the moment between start and assignment) can outlive the stop. buddie still returns
  within the timeout and the cleanup wait; the reader thread is left to such a process.
- **`clean` and the index.** The index's cached file times, `.gitignore` and `info/exclude` are the agent's
  ([environment.md](environment.md)).
- **Snapshots are not evidence.** `environment.problems()` checks consistency and takes nothing but plain JSON data;
  a consistent snapshot may be written by hand, and no check reads one.
- **The trusted base** (PATH, Python, git, pdftotext) is the host's to protect.
