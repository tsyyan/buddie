# Environment snapshots

A receipt says what buddie checked in a text. An environment snapshot says what buddie itself observed of the
place the check ran in: the interpreter, the git repository, the files you name. It describes one observation at
one time, made by buddie's code in its own process. It is not a check, it is not signed, and buddie never reads a
snapshot back as evidence.

```bash
buddie snapshot --artifact dist/buddie-2.0.0-py3-none-any.whl --report report.md --json snapshot.json
```

```python
from buddie import environment
snap = environment.collect(".", ["dist/buddie-2.0.0-py3-none-any.whl"], report=text, supplied={"command": "pytest -q"})
environment.dumps(snap)      # canonical JSON
environment.problems(snap)   # [] for a consistent snapshot (consistency, not authenticity)
```

## What is observed, and what each fact rests on

| Section | Fields | Basis | How |
|---|---|---|---|
| `runtime` | `python_version`, `python_implementation`, `os`, `architecture` | `buddie`: the interpreter running buddie reports it | `platform`, `sys.implementation` |
| `collector` | `buddie` (version), `policy` (`absent`, `active`, `invalid`) | `buddie` | the protected policy, read once ([policy.md](policy.md)) |
| `repository` | `head` (the commit id HEAD names), `worktree` (`clean`, `dirty`), `changes` (entries git status lists), `origin` (the remote's URL without credentials) | `agent_writable`: the repo, its `.git`, and the git that PATH finds are the agent's to change | git, hardened (below) |
| `artifacts` | per file: `path`, `sha256`, `bytes`, `observed_at` | `agent_writable`: files in the root | read by buddie, bounded, checked before and after |
| `report` | `sha256` of the report text | (a digest of what you passed) | the same digest as its receipt's `subject` |
| `supplied` | whatever the caller states: a command, an exit status | `caller_supplied` | kept as given, never checked, never moved into another section |

Every observed fact is `{"status", "value", "basis", "reason"}`. A fact buddie could not observe is
`"status": "unavailable"` with a `reason` and `"value": null`: nothing is filled in for it, and the reader sees why.
Reasons: `not_reported`, `git_unavailable`, `not_a_repository`, `no_commit`, `timeout`, `output_limit`, `git_error`,
`unneutralized_filter`, `index_hides_entries`, `no_remote`, `local_path`, `unrecognized_url`; for artifacts
`invalid_path`, `outside_root`, `missing`, `not_a_plain_file`, `unreadable`, `too_large`, `total_limit`,
`changed_during_read`. `limitations` lists what held for the whole snapshot: `repository_wider_than_root` (the root
is inside a repository, whose facts are about all of it), `artifact_open_unguarded` (this platform cannot open a
file without following a path part swapped for a symlink), `artifact_count_limit` (more artifacts named than are
read).

Not collected: environment variables, the user, the host name, the home directory, absolute paths, the root's own
path (`root.origin` says only whether it was an argument or the working directory), file contents, the list of
changed files. A path is given back only when it names a place inside the root; a refused one (`../x`, `/etc/x`, a
symlink out) is identified by its position in the request (`request`).

## What a snapshot proves, and what it does not

It shows what buddie's code reported when it ran, to whoever reads the document. Within that:

- **A commit id is not a clean tree.** `head` names a commit; whether the files differ from it is `worktree`, a fact
  of its own. Neither says who made the commit or that its code was run.
- **`clean` is git's view, which the agent can shape.** It means git status, under the repository's own ignore
  rules, lists nothing, and no index entry is set to be skipped (assume-unchanged, skip-worktree: then the tree is
  `index_hides_entries`, not clean). The index's cached file times, `.gitignore` and `.git/info/exclude` are the
  agent's to write; `clean` is no proof that no file changed. Submodules are not looked into.
- **A command in `supplied` is a statement, not an execution.** buddie does not run commands for a snapshot and does
  not confirm the ones you name. A `run:` anchor in a report is checked against the session transcript; a snapshot
  adds nothing to that.
- **An artifact path in a request is not an artifact.** Only `"status": "observed"` says the file was read.
- **A digest identifies the bytes read, nothing more.** `sha256` names the bytes buddie read during the
  observation, read in one pass with stat compared before, after, and by path: a file that grew, was rewritten or
  was replaced meanwhile gets no digest (`changed_during_read`). It does not say the file held those bytes before,
  holds them now, or was made by whom. A digest does not make a file immutable.
- **A snapshot is about its own time.** It says nothing of a later state; compare a new snapshot.
- **A snapshot is not an attestation.** It is not signed, and anyone can write a consistent one by hand.
  `environment.problems()` checks that a document is consistent (an unavailable fact has no value, an observed
  artifact has its digest, repository facts rest on `agent_writable`), not that buddie made it.

## How it is collected

**No network.** Nothing is fetched. git runs with `GIT_ALLOW_PROTOCOL=none` and `GIT_NO_LAZY_FETCH=1`, so a partial
clone cannot fetch a missing object.

**git, hardened.** A repository's `.git/config` is the agent's to write, and it can name commands git runs during
`git status`: `core.fsmonitor` and the clean filter of a `filter.<driver>` for files whose stat changed. The process
running buddie may hold the person's GitHub token (the plugin's setting); a planted command would see it. So the
collector runs git as every git buddie starts runs ([security.md](security.md), `buddie/runner.py`):
- from a fixed argument list, without a shell, with nothing on stdin, stderr discarded, a 10-second timeout per
  command, at most 1 MiB of output kept (a longer `git status` is `dirty` with `changes` unavailable) or 64 MiB
  streamed (`git ls-files`, read entry by entry: a longer listing, or an entry over 64 KiB, leaves the tree
  `output_limit`, not `clean`), and the program's whole process tree stopped at the end;
- in an environment of its own: `PATH` (to find git; Windows also needs `SYSTEMROOT`), and git's own settings,
  never a variable of buddie's environment. No system or global git configuration is read (`GIT_CONFIG_NOSYSTEM`,
  `GIT_CONFIG_GLOBAL` set to the null device) but the person's `safe.directory` entries, and
  `GIT_OPTIONAL_LOCKS=0` keeps `git status` from writing the index;
- with switched off on the command line, which wins over every config file, `core.fsmonitor`, the untracked cache,
  `core.ignoreStat`, implicit bare repositories, signature display, and every filter driver the repository's config
  names (its `clean`, `smudge` and `process`). A driver whose name cannot be passed that way (it holds `=`) means
  git status is not run (`unneutralized_filter`).

Because the system and global configuration are not read, `core.autocrlf` from them does not apply: a file whose
stat changed but whose content did not may show as changed. That errs towards `dirty`, never towards `clean`.

**Artifacts.** Named files only: no directory is walked. Each name is resolved as a file anchor's is
(`anchors._inside`): a `..` part, an absolute path, a drive, a stream or a symlink out of the root is
`outside_root`. It is opened as a file anchor is (`anchors._open`): on Linux and macOS each part of the path is
opened under the one before without following symlinks, on Windows the opened handle's final path must be inside
the root; a hard-linked file, a directory or a device is `not_a_plain_file`. At most 256 MiB per file, 1 GiB and 256
files per snapshot. Errors are reason codes, never the operating system's message (which may carry a path).

## Time of check, time of use

The steps are: name a file, resolve it, open it, stat the open file, read it, stat it again, stat the path again.

| | Linux, macOS | Windows |
|---|---|---|
| a path part swapped for a symlink before the open | refused (no-follow, part by part) | refused (final path of the handle) |
| the file replaced (renamed over) during the read | detected (the path names another file) | prevented: an open file cannot be renamed over |
| the file appended to or truncated | detected (length) | detected (length) |
| rewritten in place, same length | detected by modification or change time | detected by modification time |
| rewritten in place within the clock's granularity, same length | not detected | not detected |
| a hard link to a file outside the root | refused | refused |

Where a platform cannot open a file without following a replaced symlink (`artifact_open_unguarded`), the snapshot
says so instead of claiming the guarantee.

## Receipts

Snapshots are a separate document; receipts are unchanged:
- receipt-v0 is byte for byte the same, and so is receipt-v1 and its schema. Neither has a field for a snapshot,
  and none was added: a snapshot is not evidence a finding was judged on.
- Rendering a receipt never collects, and choosing receipt-v1 neither checks nor collects anything more. `buddie
  verify` never collects. Rendering a snapshot (`dumps`, `line`) does not collect again.
- No check reads a snapshot, so a missing or partial one cannot turn into a PASS.
- To pair the two: `buddie snapshot --report report.md` gives `report.sha256`, the digest `buddie verify report.md`
  names as its receipt's `subject`. An artifact's `sha256` is the raw-bytes digest a file anchor uses, so a report
  can carry it as `⚓ path#sha256`, and the receipt then checks it against the repo.

## Interfaces

| Interface | | Advice or enforcement |
|---|---|---|
| `buddie snapshot [--root DIR] [--artifact PATH ...] [--report FILE] [--supply KEY=VALUE ...] [--json FILE]` | the snapshot on stdout, or written to `--json` with one line for a person; exit 0 with a snapshot (unavailable facts included), 2 when the input cannot be used | advice |
| `buddie.environment.collect(root, artifacts, report=, supplied=)` | the snapshot as a dict; `dumps`, `line`, `problems` | advice |
| MCP, the remote server, the hook | the v0 snapshot is not exposed: it names local files and repository state. The local MCP server's `environment_snapshot` gives diagnostics (below), only what the person granted; the remote server and the hook do not | |

The protected policy does not gate a snapshot, as it does not gate `buddie verify`. A snapshot reads none of the
places a policy can set aside (`BUDDIE_REPOS`, snapshot stores, the journal), uses no network and no proxy, and
writes nothing but the `--json` file you name, so no policy setting, valid or not, makes it do more. It records the
policy's status. No policy key gates it; diagnostics (below) have `[environment]`.

## Example

```bash
cd my-project
buddie verify report.md --json receipt.json
buddie snapshot --report report.md --artifact dist/app.whl --supply command="pytest -q" --json snapshot.json
```

```
buddie snapshot: head 1f3c2a9b8e7d (clean); 1 of 1 artifacts observed
```

`snapshot.json` (abridged):

```json
{"format": "https://github.com/tsyyan/buddie#environment-v0",
 "collector": {"buddie": "2.0.0", "policy": "absent"},
 "repository": {"head": {"status": "observed", "value": "1f3c2a9b…", "basis": "agent_writable", "reason": null},
                "worktree": {"status": "observed", "value": "clean", "basis": "agent_writable", "reason": null}},
 "artifacts": [{"path": "dist/app.whl", "status": "observed", "sha256": "9b1e…", "bytes": 48213,
                "basis": "agent_writable", "reason": null}],
 "report": {"sha256": "c0ff…"},
 "supplied": {"command": "pytest -q"}}
```

Read it as: at that time, buddie found HEAD at that commit, git under the repository's own rules listed no change,
`dist/app.whl` held those 48213 bytes while it was read, and the receipt with subject `c0ff…` is for the same
report. The person running it says `pytest -q` was the command; buddie did not see it run.

## Diagnostics

Before an agent tells you "install CUDA 12.4" or "run `py -3.12 -m venv .venv`", it can ask buddie for the parts of
this machine the task needs instead of guessing them: the operating system, the CPU and memory, the GPU and its
driver stack, the Python interpreters, runtimes and package managers present, a project's declared versions, Docker.
buddie observes only the categories the request names **and you granted**, with fixed methods of its own, and says
for each value what it rests on and for each gap why. Nothing is installed or changed. The design and threat model:
[design/environment-diagnostics.md](design/environment-diagnostics.md).

```bash
buddie snapshot --list
```

```bash
buddie snapshot --category system.os --category hardware.gpu --category software.gpu_stack --task "local LLM setup"
```

Over MCP the local server's `environment_snapshot` tool takes the same: `{"categories": ["system.os",
"hardware.gpu"], "task": "local LLM setup"}`, or `{"list": true}` to see the categories and what is granted.

### Categories

| Category | Tier | Linux | macOS | Windows |
|---|---|---|---|---|
| `system.os` | baseline | os-release; WSL and container markers | `mac_ver` | `win32_ver`, edition |
| `system.shell` | baseline | bash, zsh, fish, pwsh `--version`; login shell | the same | bash and pwsh on PATH, Windows PowerShell (no profile), cmd present |
| `system.permissions` | baseline | effective uid 0 | effective uid 0 | `IsUserAnAdmin` |
| `hardware.cpu` | baseline | `/proc/cpuinfo` | `sysctl machdep.cpu.brand_string` | registry `ProcessorNameString` |
| `hardware.memory` | baseline | `/proc/meminfo`; cgroup limit | `sysctl hw.memsize`, `vm_stat` | `GlobalMemoryStatusEx` |
| `hardware.gpu` | baseline | `/sys/class/drm` vendor ids; `lspci` names; `nvidia-smi` for NVIDIA | `system_profiler SPDisplaysDataType` | display adapters in the registry; `nvidia-smi` for NVIDIA |
| `hardware.storage` | sensitive, path | `disk_usage` of a granted directory | the same | the same |
| `software.python` | baseline | python3, python, python3.9 to 3.14 on PATH: version, pip, venv, ensurepip | the same | python, python3 on PATH; `py --list` |
| `software.runtimes` | baseline | node, java, dotnet (runtimes, SDKs), go, rustc | the same | the same |
| `software.package_managers` | baseline | uv, pipx, conda, npm, yarn, pnpm, cargo, brew, apt, dnf, pacman, zypper, apk | uv to cargo, brew | uv to cargo, winget, choco |
| `software.gpu_stack` | baseline | `/proc/driver/nvidia`; `nvidia-smi -q -d COMPUTE` (driver, CUDA); `nvcc`; `/opt/rocm` | Metal family; CUDA and ROCm not applicable | `nvidia-smi`; `nvcc`; ROCm not probed |
| `software.tools` | baseline, named | `--version` of catalog tools (git, curl, cmake, gcc, ffmpeg, ollama, kubectl, and more) | the same | the same |
| `development.containers` | sensitive | docker and podman clients; `docker --context default version` | the same | the same |
| `development.project` | sensitive, path | manifests at the top of a granted directory; `requires-python`, `.python-version`, `engines.node`, `.nvmrc`, `go.mod` | the same | the same |
| `development.repository` | sensitive, path | HEAD, clean or dirty, origin (as the v0 repository facts) | the same | the same |

Answered as **unsupported**, never probed: `network.connectivity` (outbound connections of the request's choosing),
`network.proxy` (other programs' settings, often with credentials), `network.ports` (other services),
`system.applications` (other programs' data). Containers and WSL describe the guest, not the host: `system.os` says
`runtime_context` (`native`, `wsl`, `container`), memory adds a cgroup limit, and a Windows program reached from WSL
(`/mnt/c/...`) is marked `concerns: windows_host`.

### Who decides

What is collected is the intersection of what the request names, what the registry supports on this platform, what
**you** granted, and what an administrator's protected policy allows. A request grants nothing: its `task` is kept as
the caller's word, the MCP tool has no consent argument, and any argument outside its schema (`consent`, `command`)
makes the call an error before anything is collected. A denied category says so and its collector never runs.

Your grants live in `environment.toml` in your user configuration directory (`%APPDATA%\buddie` on Windows,
`$XDG_CONFIG_HOME/buddie` or `~/.config/buddie` elsewhere). `buddie snapshot --grants` shows where and what it
allows; `buddie snapshot --grant-template` prints one to save:

```toml
version = 1
allow = ["baseline"]                       # sensitive categories one by one: "development.project", ...
roots = ["~/projects"]                     # directories the path-scoped categories may look at
```

`baseline` grants the low-sensitivity categories; `hardware.storage`, `development.containers`,
`development.project` and `development.repository` are named one by one, and the three path-scoped ones also need
their directory inside a granted root (a symlink out of it is not followed). Without the file nothing is granted; a
file with an unknown key, a wrong version or an unknown category grants nothing and says why.

An ACTIVE protected policy ([policy.md](policy.md)) sets the ceiling with `[environment] allow = [...]`: a category it
does not list stays denied whatever the grants say, and an active policy without that table allows none; an INVALID
one allows none. Its `roots` bound the directories path-scoped categories may read, whatever roots the grants file
lists (`path_not_allowed_by_policy`). The policy can only narrow: it never grants what you did not.

**The limit of a local grant.** The grants file is yours, and so it is also writable by an agent running as your
user, as are `PATH`, the environment and the project. A grant states what you intend; it does not stop such an agent,
which could also run `nvidia-smi` itself through a shell. Only the protected policy is out of its reach. Diagnostics
give agents without a shell (Claude Desktop, MCP-only clients) a bounded way to learn the machine, and every agent a
structured, attributed one. A client's own tool confirmation is a second step on top, not a replacement.

### The document

`environment-diagnostics-v1`, beside environment-v0, which is unchanged:

| Key | What |
|---|---|
| `request` | a fresh id, the categories asked (valid ids only), rejected ones by position (`unknown_category`, `invalid_category`: a malformed id is not repeated), tools asked, whether a path was given |
| `authorization` | the grants file's and the policy's status, the effective categories |
| `categories` | per category: `status` (`collected`, `partial`, `unavailable`, `denied`, `unsupported`), `reason`, `tier`, `methods` (each attempt: method, why, outcome), `observations` |
| an observation | `status` `observed` (a `value`, its `basis`, the `method`, `observed_at`) or `unavailable` (a `reason`, no value), and `concerns` (`runtime`, or `windows_host` from WSL) |
| `supplied` | the task and anything else the caller states, never promoted to an observation |
| `snapshot` | the environment-v0 snapshot, when `--artifact` or `--report` is given with `--category`; `buddie freshness repo --snapshot` reads it. It is collected as `buddie snapshot` always collects it (the CLI only, never over MCP), not gated by the categories, and the document says so: limitation `snapshot_not_category_gated` |

**Basis** says what a value rests on: `buddie` (its own interpreter), `os_interface` (the OS through Python: platform,
`/proc`, `/sys`, the registry, a system call), `fixed_program` (a program at a fixed system location),
`path_program` (a program found on `PATH`, which the agent can change), `agent_writable` (project files, a
repository). None is attestation; nothing is signed.

**Unavailable is not absent.** `not_found_on_path` means not found where buddie looked; `not_found` means neither at
the standard locations nor on `PATH`; `script_not_run` means a batch or PowerShell script was found and not run (npm,
yarn, pnpm on Windows); `exit_nonzero`, `timeout`, `output_limit` say how a program answered; `inconclusive_output`
means it answered something buddie does not read as a value. The observations are made one after another, not as one
atomic picture of the machine.

### How it is collected

- Only the methods the registry declares for the category; a collector reaching for another category's method fails
  loudly. Within its category a collector may choose: `nvidia-smi` runs only after an NVIDIA adapter is seen. Every
  program run and file read is recorded as its own attempt.
- On Windows, `bash.exe` and `wsl.exe` in the system directory are never run: they start WSL.
- Programs: fixed argument lists in buddie's code, no shell, nothing on stdin, stderr discarded, 10 s and 64 KiB
  each, a 90-second deadline and 96 programs for the whole request, the process tree stopped at a limit
  ([security.md](security.md)). Their environment is an allowlist (where programs are, the user's directories some
  need, a C locale): no token, no `NODE_OPTIONS`, `JAVA_TOOL_OPTIONS`, `LD_PRELOAD`, `DYLD_*`, `DOCKER_HOST`. The
  working directory is the system's temporary directory. `PATH` is searched by buddie, absolute entries only.
- Only version- or model-shaped tokens are kept from an answer: no raw output, no paths. A value that would hold the
  home directory is dropped (`redacted`); a user name alone is not, since it is often the owner in a repository URL. No environment variable,
  process list or command line is collected; `nvidia-smi` is never asked for processes, the Docker daemon only for its
  version, on the local default context.
- Nothing runs in the background, nothing is kept: the document goes to stdout, the `--json` file you name, or the
  MCP caller. The remote HTTP server does not offer the tool.

### Scenarios

| Task | Ask for | What decides the instruction |
|---|---|---|
| Local LLM | `system.os`, `hardware.cpu`, `hardware.gpu`, `hardware.memory`, `software.python`, `software.gpu_stack` | GPU vendor and memory, driver and CUDA versions, Python version and venv support |
| Python project | `software.python`, `development.project` (with the project's directory granted) | which interpreters are there, pip and venv, the project's `requires-python` |
| Docker | `system.os`, `hardware.cpu`, `development.containers` | client present, the local daemon answering or not |

Abridged, from a Windows 11 machine with the baseline granted:

```json
{"format": "https://github.com/tsyyan/buddie#environment-diagnostics-v1",
 "authorization": {"grants": "active", "policy": "absent",
                   "effective": ["hardware.gpu", "hardware.memory", "software.gpu_stack", "system.os"]},
 "categories": {
  "hardware.gpu": {"status": "collected",
   "methods": [{"method": "registry_display", "why": "display_adapters", "outcome": "used"},
               {"method": "nvidia_smi_gpus", "why": "follow_up:nvidia_adapter", "outcome": "ok"}],
   "observations": {"adapters": {"status": "observed", "basis": "fixed_program", "method": "nvidia_smi_gpus",
     "value": [{"vendor": "NVIDIA", "model": "NVIDIA GeForce GTX 1650", "vram_bytes": 4294967296,
                "source": "nvidia_smi_gpus"}]}}},
  "software.gpu_stack": {"status": "partial", "observations": {
     "nvidia_driver": {"status": "observed", "value": "596.49", "basis": "fixed_program"},
     "cuda_driver": {"status": "observed", "value": "13.2", "basis": "fixed_program"},
     "cuda_toolkit": {"status": "unavailable", "reason": "not_found_on_path"}}},
  "development.project": {"status": "denied", "reason": "not_granted", "observations": {}}},
 "supplied": {"task": "configure-local-llm"}}
```

Read it as: the GPU is a 4 GiB GTX 1650 (from `nvidia-smi` at its fixed place), the driver supports CUDA 13.2, the
CUDA toolkit was not found on `PATH` (which is not the same as not installed), and the project was not looked at
because it was not granted.

### What diagnostics do not do

- They do not establish that a machine is what it says: an observation is buddie's report of what it read, from
  sources an agent with your account can influence (`PATH`, the project, the grants file).
- They do not find software outside the places listed: an interpreter that is not on `PATH`, a toolkit in a custom
  directory, a conda environment that is not active.
- They do not describe the host from inside a container or WSL, beyond the WSL interop label.
- Platform coverage: the OS, permission, CPU, memory, Python, project, storage and repository paths run for real in
  CI on Linux, macOS and Windows; the NVIDIA paths ran for real on Windows; the Linux GPU, WSL and container branches
  and the macOS GPU path are tested with recorded answers, not on such machines.
