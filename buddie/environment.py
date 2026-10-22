"""Environment snapshots: what buddie itself observed of the place a check ran in, and when (docs/environment.md).

A snapshot is a record of one observation, made by buddie's own code in this process:

  runtime      the interpreter running buddie: Python version and implementation, operating system, architecture
  repository   the git repository around the root: the commit HEAD names, whether the working tree differs from
               it (clean, dirty), how many entries git status lists, the origin remote with credentials taken out
  artifacts    files the caller names under the root: sha256 and length of the bytes read, or why they were not
  report       the sha256 a receipt names as its subject for the same report text, to pair the two documents
  supplied     what the caller says about itself (a command, an exit status): kept apart, never checked, never
               promoted to an observation

Each observed fact says what it rests on (`basis`): "buddie" (buddie's own process reported it: the interpreter,
the protected policy's status) or "agent_writable" (buddie read it from a place the agent under check can write: the
repo, its .git, the files in it). A fact buddie could not observe is "unavailable" with a reason code and no value;
nothing is filled in for it. Caller-supplied facts are "caller_supplied" and stay under `supplied`.

What a snapshot does not say. A commit SHA names a commit; it does not say the tree was clean (that is `worktree`),
who made it, or that the code at it was run. A command in `supplied` is a caller's word, not an execution. An
artifact's sha256 identifies the bytes read during the observation; it does not say the file still holds them, or
held them before. Nothing here is signed: a snapshot is buddie's report of what it saw, made by whoever ran buddie,
and anyone can write one by hand. buddie never reads a snapshot back as evidence for a check.

How it is collected. Nothing goes to the network. Files are opened as file anchors are (anchors._inside, _open:
inside the root, no symlink out of it, no hard link, a plain file), read with a size limit, and checked before and
after the read: a file that changed while being read gets no digest. git runs from a fixed argument list, without
a shell, with a short timeout and a bound on its output, in an environment of its own (no variable of buddie's but
PATH, and none of git's own configuration but the repository's) and with every command the repository's config can
name switched off (core.fsmonitor, filter drivers): a repository's .git/config is the agent's to write, and the
process running buddie may hold a token the agent does not.

Standard library only; nothing here imports a transport (tests/test_environment.py).
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

FORMAT = "https://github.com/tsyyan/buddie#environment-v0"
OBSERVED, UNAVAILABLE = "observed", "unavailable"
BUDDIE, AGENT_WRITABLE, CALLER_SUPPLIED = "buddie", "agent_writable", "caller_supplied"

MAX_ARTIFACTS = 256           # artifacts read per snapshot; the rest are not looked at (a limitation says so)
MAX_TOTAL_BYTES = 2**30       # bytes read for all artifacts of one snapshot
CHUNK = 2**20
GIT_TIMEOUT = 10.0            # seconds per git command
GIT_OUTPUT = 2**20            # bytes of git's output read per command
MAX_SUPPLIED = 64
MAX_SUPPLIED_CHARS = 1024
SUPPLIED_KEY = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
# what git reads from its own environment, set here; everything else of buddie's environment stays out of git's
GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_ATTR_NOSYSTEM": "1",
           "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1",
           "GIT_ALLOW_PROTOCOL": "none", "GIT_NO_REPLACE_OBJECTS": "1", "LC_ALL": "C", "LANG": "C"}
GIT_INHERITED = ("PATH", "SYSTEMROOT", "WINDIR")  # where git is; Windows needs its system directory to start it
# what a repository's config could make git run during these commands, switched off on the command line (which wins
# over every config file); filter drivers are found per repository and switched off the same way (_git_filters)
GIT_SAFE = ("-c", "core.fsmonitor=", "-c", "core.untrackedCache=false", "-c", "core.ignoreStat=false",
            "-c", "safe.bareRepository=explicit")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fact(value=None, basis: str = BUDDIE, reason: str | None = None) -> dict:
    """An observed fact (`value`), or an unavailable one (`reason`, no value): never both, never neither."""
    if reason is not None:
        return {"status": UNAVAILABLE, "value": None, "basis": basis, "reason": reason}
    return {"status": OBSERVED, "value": value, "basis": basis, "reason": None}


# --- runtime --------------------------------------------------------------------------------------------------------

def runtime() -> dict:
    """The interpreter running buddie, as it reports itself. No host name, user, path or environment variable."""
    reported = {"python_version": platform.python_version(), "python_implementation": sys.implementation.name,
                "os": platform.system(), "architecture": platform.machine()}
    return {k: fact(v) if isinstance(v, str) and v else fact(reason="not_reported") for k, v in reported.items()}


# --- git ------------------------------------------------------------------------------------------------------------

def _git_env() -> dict:
    env = {k: os.environ[k] for k in GIT_INHERITED if k in os.environ}
    env.update(GIT_ENV)
    return env


def _run(argv: list[str], consume=None) -> tuple[str, int | None, bytes]:
    """("ok", exit code, output) of one command, or ("timeout" | "output_limit" | "unavailable", None, output so far).
    No shell, nothing on stdin, stderr discarded, at most GIT_OUTPUT bytes read, killed after GIT_TIMEOUT. consume:
    a function given each piece of the output instead of keeping it (no bound on the length, the timeout holds)."""
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                env=_git_env(), shell=False)
    except OSError:
        return "unavailable", None, b""
    out, over = bytearray(), threading.Event()

    def read():
        while chunk := proc.stdout.read(65536):
            if consume is not None:
                consume(chunk)
                continue
            if len(out) + len(chunk) > GIT_OUTPUT:
                over.set()
                proc.kill()
                break
            out.extend(chunk)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(GIT_TIMEOUT)
    if reader.is_alive():
        proc.kill()
        reader.join(5)  # a child git started may still hold the pipe: the reader is a daemon, left to end with it
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            pass
        return "timeout", None, bytes(out)
    code = proc.wait()
    proc.stdout.close()
    return ("output_limit", None, bytes(out)) if over.is_set() else ("ok", code, bytes(out))


def _git_filters(git: str, root: Path) -> list[str] | None:
    """`-c` arguments that switch off every filter driver the repository's config names (clean, smudge, process),
    or None when a driver's name cannot be given on a command line (it holds "="): then git status is not run."""
    state, code, out = _run([git, "--no-pager", *GIT_SAFE, "-C", str(root), "config", "-z", "--name-only",
                             "--get-regexp", r"^filter\."])
    if state != "ok":
        return None
    if code not in (0, 1):  # 1: no such key
        return None
    args, seen = [], set()
    for name in out.decode("utf-8", "surrogateescape").split("\0"):
        if not name.startswith("filter.") or name.count(".") < 2:
            continue
        driver = name[len("filter."):name.rindex(".")]
        if not driver or "=" in driver:
            return None
        if driver not in seen:
            seen.add(driver)
            args += ["-c", f"filter.{driver}.clean=", "-c", f"filter.{driver}.smudge=",
                     "-c", f"filter.{driver}.process=", "-c", f"filter.{driver}.required=false"]
    return args


class _Hidden:
    """Counts the index entries `git ls-files -v -z` tags assume-unchanged (a lowercase tag) or skip-worktree (S, s):
    git status does not compare their files, so a tree with one is not shown clean. The index is the agent's to
    write, as the rest of .git is."""

    def __init__(self):
        self.count, self._rest = 0, b""

    def __call__(self, chunk: bytes) -> None:
        entries = (self._rest + chunk).split(b"\0")
        self._rest = entries.pop()
        self.count += sum(1 for e in entries if e[:1].islower() or e[:1] == b"S")


def origin_url(url: str) -> tuple[str | None, str | None]:
    """(the remote's URL without credentials, query or fragment, None) or (None, why it is not given): a local path
    is not given (it would name a place on this machine), nor anything that does not parse as a remote."""
    url = url.strip()
    if not url or len(url) > 512 or any(ord(c) < 32 for c in url):
        return None, "unrecognized_url"
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", url):
        try:
            p = urlsplit(url)
            port = p.port
        except ValueError:
            return None, "unrecognized_url"
        if p.scheme.lower() == "file" or not p.hostname:
            return None, "local_path"
        return f"{p.scheme.lower()}://{p.hostname}{f':{port}' if port else ''}{p.path}", None
    if m := re.match(r"^(?:[^@/\\]+@)?([A-Za-z0-9][A-Za-z0-9.-]+):(?![/\\])(.+)$", url):  # git@host:owner/repo
        return f"{m[1]}:{m[2]}", None
    return None, "local_path"


def repository(root: Path, clock=_now) -> tuple[dict, list[str]]:
    """(the repository facts, limitations) for the git repository around `root`. Every fact rests on what the agent
    can write (basis agent_writable): its .git, its files, and the git executable PATH finds."""
    unavailable = lambda why: {k: fact(basis=AGENT_WRITABLE, reason=why)  # noqa: E731
                               for k in ("head", "worktree", "changes", "origin")}
    git = shutil.which("git", path=_git_env().get("PATH"))
    if git is None:
        return {"observed_at": clock(), **unavailable("git_unavailable")}, []
    base = [git, "--no-pager", *GIT_SAFE, "-C", str(root)]
    state, code, out = _run([*base, "rev-parse", "--show-toplevel"])
    if state != "ok":
        return {"observed_at": clock(), **unavailable(state)}, []
    if code != 0:
        return {"observed_at": clock(), **unavailable("not_a_repository")}, []
    limits = []
    try:
        if Path(out.decode("utf-8", "surrogateescape").strip()).resolve() != root.resolve():
            limits.append("repository_wider_than_root")
    except OSError:
        limits.append("repository_wider_than_root")
    facts = {}
    state, code, out = _run([*base, "rev-parse", "--verify", "--quiet", "HEAD^{commit}"])
    head = out.decode("ascii", "replace").strip()
    if state != "ok":
        facts["head"] = fact(basis=AGENT_WRITABLE, reason=state)
    elif code != 0:
        facts["head"] = fact(basis=AGENT_WRITABLE, reason="no_commit")
    else:
        facts["head"] = (fact(head, AGENT_WRITABLE) if SHA.match(head) else
                         fact(basis=AGENT_WRITABLE, reason="git_error"))
    filters = _git_filters(git, root)
    if filters is None:
        facts["worktree"] = facts["changes"] = fact(basis=AGENT_WRITABLE, reason="unneutralized_filter")
    else:
        state, code, out = _run([git, "--no-pager", *GIT_SAFE, *filters, "-C", str(root), "status",
                                 "--porcelain=v1", "-z", "--untracked-files=normal", "--ignore-submodules=all",
                                 "--no-renames"])
        if state == "output_limit":  # more entries than are read: not clean, however many
            facts["worktree"] = fact("dirty", AGENT_WRITABLE)
            facts["changes"] = fact(basis=AGENT_WRITABLE, reason="output_limit")
        elif state != "ok" or code != 0:
            facts["worktree"] = facts["changes"] = fact(basis=AGENT_WRITABLE,
                                                        reason=state if state != "ok" else "git_error")
        else:
            n = out.count(b"\0")
            facts["worktree"] = fact("dirty" if n else "clean", AGENT_WRITABLE)
            facts["changes"] = fact(n, AGENT_WRITABLE)
            if not n:  # "clean" only when git status looked at every tracked file
                hidden = _Hidden()
                state, code, _ = _run([*base, "ls-files", "-v", "-z"], consume=hidden)
                if state != "ok" or code != 0 or hidden.count:
                    why = state if state != "ok" else "git_error" if code != 0 else "index_hides_entries"
                    facts["worktree"] = fact(basis=AGENT_WRITABLE, reason=why)
    state, code, out = _run([*base, "config", "--get", "remote.origin.url"])
    if state != "ok":
        facts["origin"] = fact(basis=AGENT_WRITABLE, reason=state)
    elif code != 0:
        facts["origin"] = fact(basis=AGENT_WRITABLE, reason="no_remote")
    else:
        url, why = origin_url(out.decode("utf-8", "replace"))
        facts["origin"] = fact(url, AGENT_WRITABLE) if why is None else fact(basis=AGENT_WRITABLE, reason=why)
    return {"observed_at": clock(), **facts}, limits


# --- artifacts ------------------------------------------------------------------------------------------------------

def guarded_open() -> bool:
    """Whether a file can be opened here so that a path part swapped for a symlink after the check is refused
    (anchors._open: no-follow, part by part, on Linux and macOS; the handle's final path on Windows)."""
    if os.name == "nt":
        return True
    return bool(getattr(os, "O_NOFOLLOW", 0)) and os.open in os.supports_dir_fd and hasattr(os, "O_DIRECTORY")


def _record(index: int, path: str | None, reason: str | None = None, digest: str | None = None,
            size: int | None = None, at: str | None = None) -> dict:
    return {"request": index, "path": path, "status": OBSERVED if reason is None else UNAVAILABLE,
            "sha256": digest, "bytes": size, "observed_at": at, "basis": AGENT_WRITABLE, "reason": reason}


def _same(a: os.stat_result, b: os.stat_result) -> bool:
    """The same file, unchanged as far as stat tells: length, modification time, the inode change time (POSIX; on
    Windows st_ctime is the creation time) and the file's identity where the system gives one."""
    if a.st_size != b.st_size or a.st_mtime_ns != b.st_mtime_ns:
        return False
    if os.name != "nt" and a.st_ctime_ns != b.st_ctime_ns:
        return False
    return not (a.st_ino and b.st_ino) or (a.st_ino, a.st_dev) == (b.st_ino, b.st_dev)


def artifact(root: Path, rel, index: int, budget: list[int], clock=_now) -> dict:
    """One named file under `root`: its sha256 and length, read once with stat before and after, or why not. The
    path is given back only when it names a place inside the root: a path that leads out is not repeated."""
    from buddie import anchors as anc
    if type(rel) is not str or not rel or len(rel) > 4096 or "\0" in rel:
        return _record(index, None, "invalid_path")
    try:
        rel.encode("utf-8")
    except UnicodeEncodeError:
        return _record(index, None, "invalid_path")
    name = "/".join(p for p in rel.replace("\\", "/").split("/") if p not in ("", "."))
    target = anc._inside(root, rel)
    if target == anc.OUTSIDE:
        return _record(index, None, "outside_root")
    if target is None:
        return _record(index, name, "missing")
    resolved = root.resolve()
    try:
        if not stat.S_ISREG(os.stat(target).st_mode):
            return _record(index, name, "not_a_plain_file")
    except OSError:
        return _record(index, name, "unreadable")
    fd = anc._open(target, resolved)
    if fd is None:
        try:  # only to tell an unreadable file from a refused one; the bytes are never read through this
            os.close(os.open(target, os.O_RDONLY | getattr(os, "O_BINARY", 0)))
        except PermissionError:
            return _record(index, name, "unreadable")
        except OSError:
            pass
        return _record(index, name, "not_a_plain_file")
    try:
        before = os.fstat(fd)
        if before.st_size > anc.MAX_FILE_BYTES:
            return _record(index, name, "too_large")
        if before.st_size > budget[0]:
            return _record(index, name, "total_limit")
        h, size = hashlib.sha256(), 0
        while chunk := os.read(fd, CHUNK):
            size += len(chunk)
            if size > anc.MAX_FILE_BYTES or size > budget[0]:
                budget[0] -= size
                return _record(index, name, "too_large" if size > anc.MAX_FILE_BYTES else "total_limit")
            h.update(chunk)
        budget[0] -= size
        after = os.fstat(fd)
        try:
            now = os.stat(target)
        except OSError:
            return _record(index, name, "changed_during_read")
        if size != before.st_size or not _same(before, after) or not _same(after, now):
            return _record(index, name, "changed_during_read")
        return _record(index, name, None, h.hexdigest(), size, clock())
    except OSError:
        return _record(index, name, "unreadable")
    finally:
        os.close(fd)


def artifacts(root: Path, names, clock=_now) -> tuple[list[dict], list[str]]:
    """(records, limitations) for the files named: each name once, at most MAX_ARTIFACTS, MAX_TOTAL_BYTES in all.
    Ordered by path, then the refused requests (no path given back) by their position in the request."""
    names = list(names)
    limits = [] if guarded_open() else ["artifact_open_unguarded"]
    if len(names) > MAX_ARTIFACTS:
        limits.append("artifact_count_limit")
    out, seen, budget = [], set(), [MAX_TOTAL_BYTES]
    for i, rel in enumerate(names[:MAX_ARTIFACTS]):
        rec = artifact(root, rel, i, budget, clock)
        if rec["path"] is not None:
            if rec["path"] in seen:
                continue
            seen.add(rec["path"])
        out.append(rec)
    out.sort(key=lambda r: (r["path"] is None, r["path"] or "", r["request"]))
    return out, limits


# --- supplied -------------------------------------------------------------------------------------------------------

def supplied_facts(supplied) -> dict:
    """The caller's own statements, as given: lowercase keys, JSON scalars of the exact built-in types (a subclass
    that would print as something else is refused). Raises ValueError for anything else."""
    if supplied is None:
        return {}
    if type(supplied) is not dict:
        raise ValueError("supplied: a dict of key -> string, number, boolean or null")
    if len(supplied) > MAX_SUPPLIED:
        raise ValueError(f"supplied: at most {MAX_SUPPLIED} entries")
    out = {}
    for k, v in supplied.items():
        if type(k) is not str or not SUPPLIED_KEY.match(k):
            raise ValueError(f"supplied: key {k!r} is not lowercase letters, digits, '_', '.', '-' (64 at most)")
        if v is not None and type(v) not in (str, int, float, bool):
            raise ValueError(f"supplied: {k} is a {type(v).__name__}, not a string, number, boolean or null")
        if type(v) is float and (v != v or v in (float("inf"), float("-inf"))):
            raise ValueError(f"supplied: {k} is not a finite number")
        if type(v) is str and (len(v) > MAX_SUPPLIED_CHARS or "\0" in v):
            raise ValueError(f"supplied: {k} is over {MAX_SUPPLIED_CHARS} characters or holds NUL")
        out[k] = v
    return dict(sorted(out.items()))


# --- the snapshot ---------------------------------------------------------------------------------------------------

def collect(root=None, artifacts_named=(), *, report: str | None = None, supplied=None, clock=None) -> dict:
    """An environment snapshot (environment-v0) of `root` (default: the working directory): the runtime, the
    repository, the named artifacts (paths relative to the root), the sha256 of `report` (the text a receipt was
    made for: the same digest as its subject), and the caller's own statements kept apart under `supplied`. clock:
    a function giving the timestamps (tests). Raises ValueError when the root is not a directory or `supplied` is
    not acceptable; anything buddie cannot observe is unavailable."""
    from buddie import __version__, policy
    clock = clock or _now
    given = supplied_facts(supplied)
    if report is not None and type(report) is not str:
        raise ValueError("report: the report's text")
    root, origin = (Path.cwd(), "working_directory") if root is None else (Path(root), "argument")
    if not root.is_dir():
        raise ValueError("root is not a directory")
    started = clock()
    with policy.held() as loaded:  # one reading of the protected policy; it is recorded, and it grants nothing here
        status = loaded.status.value
        repo, repo_limits = repository(root, clock)
        files, file_limits = artifacts(root, artifacts_named, clock)
    return {
        "format": FORMAT,
        "collector": {"buddie": __version__, "policy": status},
        "started_at": started,
        "finished_at": clock(),
        "root": {"origin": origin},
        "runtime": runtime(),
        "repository": repo,
        "artifacts": files,
        "report": None if report is None else {"sha256": hashlib.sha256(report.encode("utf-8")).hexdigest()},
        "supplied": given,
        "limitations": sorted(set(repo_limits + file_limits)),
    }


def dumps(snapshot: dict) -> str:
    """A snapshot as canonical JSON: keys sorted, UTF-8 as it is, the same bytes for the same snapshot."""
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def line(snapshot: dict) -> str:
    """One line for a person."""
    repo = snapshot["repository"]
    if repo["head"]["status"] == OBSERVED:
        tree = repo["worktree"]["value"] or f"tree {repo['worktree']['reason']}"
        n = repo["changes"]["value"]
        where = f"head {repo['head']['value'][:12]} ({tree}{f', {n} changes' if n else ''})"
    else:
        where = f"repository {repo['head']['reason']}"
    files = snapshot["artifacts"]
    seen = sum(a["status"] == OBSERVED for a in files)
    out = f"buddie snapshot: {where}; {seen} of {len(files)} artifacts observed"
    if snapshot["limitations"]:
        out += f"; limitations: {', '.join(snapshot['limitations'])}"
    return out


# --- consistency ----------------------------------------------------------------------------------------------------

REASONS = {"not_reported", "git_unavailable", "not_a_repository", "no_commit", "timeout", "output_limit",
           "unavailable", "git_error", "unneutralized_filter", "no_remote", "local_path", "unrecognized_url",
           "invalid_path", "outside_root", "missing", "not_a_plain_file", "unreadable", "too_large", "total_limit",
           "changed_during_read", "index_hides_entries"}
LIMITATIONS = {"repository_wider_than_root", "artifact_open_unguarded", "artifact_count_limit"}
TOP = {"format", "collector", "started_at", "finished_at", "root", "runtime", "repository", "artifacts", "report",
       "supplied", "limitations"}
_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _fact_problems(where: str, f, bases) -> list[str]:
    if type(f) is not dict or set(f) != {"status", "value", "basis", "reason"}:
        return [f"{where}: not a fact (status, value, basis, reason)"]
    out = [] if f["basis"] in bases else [f"{where}: basis {f['basis']!r}"]
    if f["status"] == OBSERVED:
        if f["value"] is None or f["reason"] is not None:
            out.append(f"{where}: observed with no value, or with a reason")
    elif f["status"] == UNAVAILABLE:
        if f["value"] is not None or f["reason"] not in REASONS:
            out.append(f"{where}: unavailable with a value, or with an unknown reason")
    else:
        out.append(f"{where}: status {f['status']!r}")
    return out


def problems(doc) -> list[str]:
    """What makes `doc` not a consistent environment-v0 snapshot: its shape, and rules a shape cannot say (an
    unavailable fact has no value, an observed artifact has its digest, nothing caller-supplied is outside
    `supplied`). Consistency, not authenticity: a consistent snapshot may still be written by hand."""
    if type(doc) is not dict:
        return ["not an object"]
    out = []
    if set(doc) != TOP:
        return [f"keys: missing {sorted(TOP - set(doc))}, unknown {sorted(set(doc) - TOP)}"]
    if doc["format"] != FORMAT:
        out.append(f"format is not {FORMAT}")
    col = doc["collector"]
    if type(col) is not dict or set(col) != {"buddie", "policy"} or col.get("policy") not in (
            "absent", "active", "invalid") or type(col.get("buddie")) is not str:
        out.append("collector: buddie (version) and policy (absent, active, invalid)")
    for k in ("started_at", "finished_at"):
        if type(doc[k]) is not str or not _TIME.match(doc[k]):
            out.append(f"{k}: not a UTC time")
    if doc["root"] not in ({"origin": "argument"}, {"origin": "working_directory"}):
        out.append("root: origin argument or working_directory, and nothing else")
    rt = doc["runtime"]
    if type(rt) is not dict or set(rt) != {"python_version", "python_implementation", "os", "architecture"}:
        out.append("runtime: python_version, python_implementation, os, architecture")
    else:
        out += [p for k, f in sorted(rt.items()) for p in _fact_problems(f"runtime.{k}", f, {BUDDIE})]
    repo = doc["repository"]
    if type(repo) is not dict or set(repo) != {"observed_at", "head", "worktree", "changes", "origin"}:
        out.append("repository: observed_at, head, worktree, changes, origin")
    else:
        if type(repo["observed_at"]) is not str or not _TIME.match(repo["observed_at"]):
            out.append("repository.observed_at: not a UTC time")
        for k in ("head", "worktree", "changes", "origin"):
            out += _fact_problems(f"repository.{k}", repo[k], {AGENT_WRITABLE})
        h, w, c = repo["head"], repo["worktree"], repo["changes"]
        if type(h) is dict and h.get("status") == OBSERVED and not (type(h["value"]) is str and SHA.match(h["value"])):
            out.append("repository.head: not a commit id")
        if type(w) is dict and w.get("status") == OBSERVED and w["value"] not in ("clean", "dirty"):
            out.append("repository.worktree: clean or dirty")
        if type(c) is dict and c.get("status") == OBSERVED:
            if type(c["value"]) is not int or c["value"] < 0:
                out.append("repository.changes: a count")
            elif type(w) is dict and w.get("status") == OBSERVED and (w["value"] == "clean") != (c["value"] == 0):
                out.append("repository.changes: disagrees with worktree")
    arts = doc["artifacts"]
    if type(arts) is not list:
        out.append("artifacts: a list")
    else:
        keys = {"request", "path", "status", "sha256", "bytes", "observed_at", "basis", "reason"}
        for i, a in enumerate(arts):
            where = f"artifacts[{i}]"
            if type(a) is not dict or set(a) != keys:
                out.append(f"{where}: {', '.join(sorted(keys))}")
                continue
            if type(a["request"]) is not int or a["request"] < 0 or a["basis"] != AGENT_WRITABLE:
                out.append(f"{where}: request (a position) and basis agent_writable")
            if a["status"] == OBSERVED:
                if not (type(a["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", a["sha256"])
                        and type(a["bytes"]) is int and a["bytes"] >= 0 and type(a["path"]) is str
                        and type(a["observed_at"]) is str and _TIME.match(a["observed_at"]) and a["reason"] is None):
                    out.append(f"{where}: observed needs path, sha256, bytes, observed_at and no reason")
            elif a["status"] == UNAVAILABLE:
                if a["sha256"] is not None or a["bytes"] is not None or a["observed_at"] is not None \
                        or a["reason"] not in REASONS:
                    out.append(f"{where}: unavailable has a reason and no digest, length or time")
            else:
                out.append(f"{where}: status {a['status']!r}")
        named = [a["path"] for a in arts if type(a) is dict and a.get("path") is not None]
        if len(named) != len(set(named)):
            out.append("artifacts: a path twice")
    rep = doc["report"]
    if rep is not None and not (type(rep) is dict and set(rep) == {"sha256"} and type(rep["sha256"]) is str
                                and re.fullmatch(r"[0-9a-f]{64}", rep["sha256"])):
        out.append("report: null or {sha256}")
    try:
        supplied_facts(doc["supplied"])
    except ValueError as error:
        out.append(str(error))
    lim = doc["limitations"]
    if type(lim) is not list or any(x not in LIMITATIONS for x in lim) or lim != sorted(set(lim)):
        out.append("limitations: known codes, sorted, each once")
    return out
