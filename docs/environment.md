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
| MCP, the remote server, the hook | not exposed: a snapshot names local files and repository state, which is not handed to an agent's tools without its own security review | |

The protected policy does not gate a snapshot, as it does not gate `buddie verify`. A snapshot reads none of the
places a policy can set aside (`BUDDIE_REPOS`, snapshot stores, the journal), uses no network and no proxy, and
writes nothing but the `--json` file you name, so no policy setting, valid or not, makes it do more. It records the
policy's status. No policy key was added.

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
