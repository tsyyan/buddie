"""Bounded child processes, and git run so that nothing the agent can write decides what it executes (docs/security.md).

Every program buddie starts goes through run(): a fixed argument list, nothing on stdin, stderr discarded, a timeout,
a bound on the bytes read from its output whether they are kept or streamed to a consumer, and its whole process
tree stopped when it is over (a process group on Linux and macOS, a job object on Windows). The caller always gets
an answer within the timeout and a few seconds of cleanup: ("ok", exit code, output), or "timeout",
"output_limit" or "unavailable" with no exit code. A hook event also sets a budget for all its programs together
(deadline): a repository that makes each one slow cannot hold the hook past its own timeout, after which the host
would let the answer out unchecked.

git(). The repository, its .git and the hook's environment are the agent's to write; the process running buddie
may hold the person's GitHub token (the plugin's setting), which the agent does not. So git:
  - gets an environment of its own: PATH (to find it; Windows also needs SYSTEMROOT and WINDIR) and git's own
    settings, never another variable of buddie's (no token, no GIT_DIR, no GIT_CONFIG_*, no proxy);
  - reads no system or global configuration, except the `safe.directory` entries the person set there, passed on
    the command line so that a repository git would refuse to read before is still read;
  - has switched off, on the command line (which wins over every config file), what a repository's config can make
    the commands buddie runs execute: core.fsmonitor, every filter driver's clean, smudge and process command
    (git_filters, for `git status`), and signature verification; and no protocol, so no fetch;
  - is the git that PATH finds: part of the host's trusted base, as the Python running buddie is.
"""
from __future__ import annotations

import contextvars
import functools
import os
import shutil
import signal
import subprocess
import threading
import time
from collections import namedtuple
from contextlib import contextmanager

Result = namedtuple("Result", "state code out")  # state: ok, timeout, output_limit, unavailable

TIMEOUT = 10.0                 # seconds per program, unless the caller says otherwise
OUTPUT = 2**20                 # bytes of output kept in memory
STREAM = 64 * 2**20            # bytes of output a consumer may be given
CLEANUP = 5.0                  # seconds to wait for a stopped process tree and its output pipe
_DEADLINE: contextvars.ContextVar = contextvars.ContextVar("buddie_runner_deadline", default=None)


@contextmanager
def deadline(seconds: float):
    """A budget for every program run inside the block together (one hook event): each gets at most what is left,
    and none starts once it is spent ("timeout"). An outer, shorter budget stays in force."""
    end = time.monotonic() + seconds
    outer = _DEADLINE.get()
    token = _DEADLINE.set(end if outer is None else min(outer, end))
    try:
        yield
    finally:
        _DEADLINE.reset(token)


def _allowed(timeout: float) -> float:
    end = _DEADLINE.get()
    return timeout if end is None else min(timeout, end - time.monotonic())


CREDENTIAL_PREFIXES = ("CLAUDE_PLUGIN_OPTION_",)  # the plugin's settings: the person's, given to buddie alone
CREDENTIAL_NAMES = ("BUDDIE_GITHUB_TOKEN", "BUDDIE_HTTP_TOKEN")


def without_credentials(environ=None) -> dict:
    """buddie's environment for a program that needs it (a command the person names, pdftotext), less what buddie
    holds for itself: the plugin's settings (its GitHub token among them) and buddie's own tokens."""
    environ = os.environ if environ is None else environ
    return {k: v for k, v in environ.items()
            if not k.upper().startswith(CREDENTIAL_PREFIXES) and k.upper() not in CREDENTIAL_NAMES}


# --- stopping a process tree ----------------------------------------------------------------------------------------

def _windows_job(proc):
    """A job object holding `proc`, which ends every process in it when it is closed or terminated (None when it
    cannot be made). A child that `proc` starts before it is assigned escapes it: git and the shells buddie starts
    run a moment before they start anything."""
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", ctypes.c_ulonglong * 6),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not (k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))  # extended limits
                and k32.AssignProcessToJobObject(job, int(proc._handle))):
            k32.CloseHandle(job)
            return None
        return job
    except Exception:  # noqa: BLE001 - no job object: proc.kill() still ends the process itself
        return None


def _close_job(job, terminate: bool) -> None:
    if job is None:
        return
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    if terminate:
        k32.TerminateJobObject(job, 1)
    k32.CloseHandle(job)  # KILL_ON_JOB_CLOSE: a process left in it (one that kept the pipe) ends now


def _stop(proc, job) -> None:
    """End the process and what it started: its process group (Linux, macOS: it leads a session of its own, so the
    group is still there while it is unreaped), its job (Windows)."""
    if os.name == "nt":
        _close_job(job, terminate=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        proc.kill()
    except OSError:
        pass


def run(argv, *, env: dict, timeout: float = TIMEOUT, limit: int | None = None, consume=None, cwd=None,
        shell: bool = False) -> Result:
    """One program, bounded (see the module's docstring). `limit`: bytes of output read at most (default OUTPUT,
    or STREAM with a consumer); more stops the program ("output_limit"). consume: a function given each piece of
    the output instead of keeping it; when it returns False the output is refused and the program stopped
    ("output_limit"). shell: `argv` is one command line for the system's shell (only for a command the person
    named); otherwise a list run as is."""
    allowed = _allowed(timeout)
    if allowed <= 0:
        return Result("timeout", None, b"")
    limit = (STREAM if consume is not None else OUTPUT) if limit is None else limit
    flags = {"start_new_session": True} if os.name != "nt" else {}
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                env=env, cwd=cwd, shell=shell, **flags)
    except (OSError, ValueError):
        return Result("unavailable", None, b"")
    job = _windows_job(proc) if os.name == "nt" else None
    out, seen, refused = bytearray(), [0], threading.Event()

    def read():
        try:
            while chunk := proc.stdout.read(65536):
                seen[0] += len(chunk)
                if seen[0] > limit:
                    refused.set()
                    return
                if consume is not None:
                    if consume(chunk) is False:
                        refused.set()
                        return
                else:
                    out.extend(chunk)
        except (OSError, ValueError):  # the pipe closed under it: the tree was stopped
            return

    reader = threading.Thread(target=read, daemon=True)
    started = time.monotonic()
    reader.start()
    reader.join(allowed)
    state = "timeout" if reader.is_alive() else "output_limit" if refused.is_set() else "ok"
    code = None
    if state == "ok":
        try:
            code = proc.wait(max(0.0, allowed - (time.monotonic() - started)))
        except subprocess.TimeoutExpired:  # the output ended, the program did not
            state = "timeout"
    if state != "ok":
        _stop(proc, job)
        reader.join(CLEANUP)  # a process outside the tree may still hold the pipe: the reader is left to it
        try:
            proc.wait(CLEANUP)
        except subprocess.TimeoutExpired:
            pass
        return Result(state, None, bytes(out))
    _close_job(job, terminate=False)
    try:
        proc.stdout.close()
    except OSError:
        pass
    return Result("ok", code, bytes(out))


# --- git ------------------------------------------------------------------------------------------------------------

# what git reads from its own environment, set here; everything else of buddie's environment stays out of git's
GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_ATTR_NOSYSTEM": "1",
           "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1",
           "GIT_ALLOW_PROTOCOL": "none", "GIT_NO_REPLACE_OBJECTS": "1", "LC_ALL": "C", "LANG": "C"}
GIT_INHERITED = ("PATH", "SYSTEMROOT", "WINDIR")  # where git is; Windows needs its system directory to start it
# what a repository's config could make these commands execute, switched off on the command line (which wins over
# every config file); filter drivers are found per repository and switched off the same way (git_filters)
GIT_SAFE = ("-c", "core.fsmonitor=", "-c", "core.untrackedCache=false", "-c", "core.ignoreStat=false",
            "-c", "safe.bareRepository=explicit", "-c", "log.showSignature=false")
# where the person's own git configuration is found, for its safe.directory entries alone (safe_directories)
_CONFIG_PLACES = ("HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "XDG_CONFIG_HOME", "PROGRAMDATA", "ALLUSERSPROFILE")


def git_env() -> dict:
    env = {k: os.environ[k] for k in GIT_INHERITED if k in os.environ}
    env.update(GIT_ENV)
    return env


def git_executable() -> str | None:
    return shutil.which("git", path=git_env().get("PATH"))


@functools.lru_cache(maxsize=1)
def safe_directories() -> tuple[str, ...]:
    """`-c safe.directory=…` for each entry of the person's system and global git configuration: git reads a
    repository another user owns only when one of these names it, and buddie's git reads no system or global
    configuration otherwise. Only this key is taken, only from those two scopes (git itself ignores it in a
    repository's own config), and `git config --get-all` runs nothing."""
    import tempfile
    exe = git_executable()
    if exe is None:
        return ()
    env = {k: os.environ[k] for k in GIT_INHERITED + _CONFIG_PLACES if k in os.environ}
    env.update({k: v for k, v in GIT_ENV.items() if k not in ("GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL")})
    out = []
    for scope in ("--system", "--global"):
        got = run([exe, "--no-pager", "config", scope, "--null", "--get-all", "safe.directory"], env=env,
                  cwd=tempfile.gettempdir())
        if got.state != "ok" or got.code != 0:
            continue
        for value in got.out.decode("utf-8", "surrogateescape").split("\0"):
            if value and "\n" not in value:
                out += ["-c", f"safe.directory={value}"]
    return tuple(out)


def git_filters(root, exe: str | None = None) -> list[str] | None:
    """`-c` arguments that switch off every filter driver the repository's config names (clean, smudge, process),
    or None when that cannot be done: a driver's name holds "=" (it cannot be given on a command line), or the
    config cannot be read. git status is then not run: it would run a clean filter for a file whose stat changed."""
    exe = exe or git_executable()
    if exe is None:
        return None
    got = run([exe, "--no-pager", *GIT_SAFE, *safe_directories(), "-C", str(root), "config", "-z", "--name-only",
               "--get-regexp", r"^filter\."], env=git_env())
    if got.state != "ok" or got.code not in (0, 1):  # 1: no such key
        return None
    args, seen = [], set()
    for name in got.out.decode("utf-8", "surrogateescape").split("\0"):
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


UNNEUTRALIZED = "unneutralized_filter"


def git(root, *args: str, timeout: float = TIMEOUT, limit: int | None = None, consume=None,
        filters: bool = False) -> Result:
    """`git -C root ARGS`, bounded and hardened (see the module's docstring). filters=True: for a command that may
    run a filter driver (git status), every driver the repository's config names is switched off first, and when
    that cannot be done the command is not run (Result("unneutralized_filter", None, b""))."""
    exe = git_executable()
    if exe is None:
        return Result("unavailable", None, b"")
    extra = []
    if filters:
        extra = git_filters(root, exe)
        if extra is None:
            return Result(UNNEUTRALIZED, None, b"")
    return run([exe, "--no-pager", *GIT_SAFE, *safe_directories(), *extra, "-C", str(root), *args], env=git_env(),
               timeout=timeout, limit=limit, consume=consume)


def git_text(root, *args: str, **kw) -> str | None:
    """git's output as UTF-8 text (git writes paths and commit messages as UTF-8, whatever the locale), or None when
    git did not answer or failed."""
    got = git(root, *args, **kw)
    return got.out.decode("utf-8", "replace") if got.state == "ok" and got.code == 0 else None
