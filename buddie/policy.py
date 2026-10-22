"""The protected policy: what the person who administers the machine requires of buddie, out of the agent's reach.

Who can set what. The agent runs as the same OS user as the hook, so everything that user can write is within its
reach: the repo's buddie.toml, the hook's environment (Claude Code passes the project's .claude/settings.json `env`
to hooks), the plugin's options, buddie's own state and journal. None of that can prove that a person decided
something. What the agent cannot write without the person's elevation (sudo, a UAC prompt) is a file owned by the
system in a system directory. That file, and only that file, is the protected policy:

  Linux, macOS  /etc/buddie/policy.toml          owned by root, not writable by group or others, nor any directory
                                                 above it (the real path, after symlinks)
  Windows       <ProgramData>\\buddie\\policy.toml  ProgramData as the system names it (not the %ProgramData%
                                                 variable, which a process can set); the file and every directory
                                                 above it owned by SYSTEM, Administrators or TrustedInstaller, no
                                                 ACE letting a low-privilege principal or this user change or
                                                 replace them, and AccessCheck with this token agreeing
                                                 (buddie/winacl.py)

The location is fixed here; no variable or argument moves it. buddie never writes it: `buddie policy template` prints
one, the person installs it with their own elevation (docs/policy.md).

What it can say. A policy only sets limits for the sources below it (buddie.toml, the environment, plugin options):
a floor for each gate class (they may make a class stricter, never weaker), whether they may turn the intro mode on,
set the final mark, change transcript reading, keep conversation words in the journal, turn return tracking off, or
name a command to run; whether a `buddie:` line may let a returned answer out; whether buddie may use the network;
and where the hook may take its evidence from ([evidence]: which repos, which snapshot stores, where the journal
goes, whether fetches follow the environment's proxy and CA settings, which GitHub API answers pr: and ci:).
With no policy buddie behaves as before. A policy grants nothing that buddie without one would not do, so a policy
someone else managed to plant can at most leave things as they were.

Its three states. ABSENT: no file; the legacy behaviour, unprotected. ACTIVE: a protected, valid file. INVALID: a file
that is there but cannot be trusted or used (writable by this user, unreadable, not UTF-8, not TOML, an unknown
version or key, a bad value): buddie runs with the strictest limits and the gate returns each answer with the reason,
as for a broken buddie.toml, until the person fixes the file. A failure never yields a more permissive policy.
"""
from __future__ import annotations

import contextvars
import os
import stat
import sys
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

VERSION = 1
LEVELS = ("block", "warn", "off")
CLASSES = ("anchors", "quotes", "final", "prose", "numbers", "work", "summary", "promises", "context")


class Status(str, Enum):
    ABSENT = "absent"
    ACTIVE = "active"
    INVALID = "invalid"


@dataclass(frozen=True)
class Policy:
    """Limits for the lower sources. The defaults are what an ACTIVE policy means when it does not say otherwise:
    nothing below may weaken a check, grant collection or execution, or make its own word count as the person's."""
    floors: dict[str, str] = field(default_factory=dict)  # class -> the weakest level a lower source may set
    project_intro: bool = False          # may buddie.toml turn the intro mode (returns only warn) on
    project_final_mark: bool = False     # may buddie.toml or BUDDIE_FINAL set the final mark
    final_mark: str | None = None        # the policy's own final mark (None: the plugin's default, the Stop answer)
    transcript: str = "project"          # "required" (read, whatever below says), "forbidden" (never), "project"
    journal_text: str = "forbidden"      # "forbidden" (receipts only), "project" (buddie.toml / env may choose)
    disclosure: bool = True              # may a `buddie:` line let a returned answer out (after the return)
    project_state: bool = False          # may BUDDIE_STATE=0 turn return tracking off
    free_command: str | None = None      # the only launch free command when ACTIVE (BUDDIE_FREE is ignored)
    network: str = "allowed"             # "allowed" (as below sources set), "forbidden" (no fetch, no GitHub)
    # [evidence] (buddie/evidence.py): where the hook's evidence may come from. Unlike the keys above, each default
    # is the behaviour without a policy, so a policy written before [evidence] existed decides exactly as it did;
    # the template sets the restrictive values
    repos: str = "environment"           # "event": only the checkout around the event, BUDDIE_REPOS set aside
    stores: str = "session"              # "observed": quotes and numbers judged only on bytes fetched in the check
    journal: str = "environment"         # "fixed": the default places, BUDDIE_LOG / BUDDIE_SHARED_LOG set aside
    collector: str = "environment"       # "isolated": the hook's fetches take no proxy or CA from the environment
    github_api: str | None = None        # the API for pr:/ci: (BUDDIE_GITHUB_API then set aside); None: as below


# INVALID: every class that judges a claim blocks, nothing is granted to the sources below (no intro, no final mark,
# no journal words, no BUDDIE_STATE=0, no free command). The workflow classes (summary, promises, context) keep what
# the sources below say: they return a Stop for a summary or a promise, they do not judge one
VERIFYING = ("anchors", "quotes", "numbers", "work", "final", "prose")
STRICTEST = Policy(floors={c: "block" for c in VERIFYING})


@dataclass(frozen=True)
class Loaded:
    status: Status
    policy: Policy | None
    path: Path
    error: str | None = None

    @property
    def effective(self) -> Policy | None:
        """The limits to apply: the policy, the strictest ones when it is INVALID, None when ABSENT."""
        return self.policy if self.status is Status.ACTIVE else STRICTEST if self.status is Status.INVALID else None


def _program_data() -> Path | None:
    """ProgramData as Windows names it (SHGetFolderPathW, CSIDL_COMMON_APPDATA), not as an environment says."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x23, None, 0, buf) == 0 and buf.value:
            return Path(buf.value)
    except Exception:  # noqa: BLE001 - no shell32: there is no system location to trust
        return None
    return None


def location() -> Path | None:
    """Where the protected policy is, fixed by the system; None where the system gives no such place."""
    if sys.platform == "win32":
        root = _program_data()
        return root / "buddie" / "policy.toml" if root else None
    return Path("/etc/buddie/policy.toml")


def protection_problem(path: Path) -> str | None:
    """Why the file at `path` is not out of this user's reach, or None when it is."""
    if sys.platform == "win32":
        # owner, DACL and this token's AccessCheck, for the file and each directory above it (buddie/winacl.py):
        # not a write-open probe, which a read-only attribute or a passing lock would fool
        from buddie import winacl
        return winacl.problem(str(path))
    real = Path(os.path.realpath(path))
    for p in [real, *real.parents]:
        try:
            st = os.stat(p)
        except OSError as error:
            return f"cannot be inspected: {p}: {error.strerror or error}"
        if st.st_uid != 0:
            return f"{p} is not owned by root"
        if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            return f"{p} is writable by its group or by others"
    if os.geteuid() != 0 and os.access(real, os.W_OK):
        return "writable by this user"
    return None


def parse(data: dict) -> Policy:
    """A policy from its TOML, or ValueError naming what is wrong. Unknown keys are errors, not ignored: a key that
    does not do what its author meant must not pass unnoticed."""
    if data.get("version") != VERSION:
        raise ValueError(f"unsupported version {data.get('version')!r} (this buddie reads version {VERSION})")
    known = {"version", "gates", "project", "final_mark", "transcript", "journal_text", "disclosure", "free_command",
             "network", "evidence"}
    if extra := sorted(set(data) - known):
        raise ValueError(f"unknown keys: {', '.join(extra)}")
    floors = data.get("gates", {})
    if not isinstance(floors, dict) or (bad := [k for k, v in floors.items() if k not in CLASSES or v not in LEVELS]):
        raise ValueError(f"[gates]: {', '.join(bad) if isinstance(floors, dict) else 'not a table'}: each key is a class "
                         f"({', '.join(CLASSES)}) and each value one of {', '.join(LEVELS)}")
    project = data.get("project", {})
    allowed = {"intro", "final_mark", "state"}
    if not isinstance(project, dict) or (bad := [k for k, v in project.items()
                                                 if k not in allowed or not isinstance(v, bool)]):
        raise ValueError(f"[project]: {', '.join(bad) if isinstance(project, dict) else 'not a table'}: "
                         f"keys {', '.join(sorted(allowed))}, each true or false")

    def one_of(key, values, default):
        v = data.get(key, default)
        if v not in values:
            raise ValueError(f"{key} = {v!r}: one of {', '.join(values)}")
        return v
    mark, free = data.get("final_mark"), data.get("free_command")
    for key, v in (("final_mark", mark), ("free_command", free)):
        if v is not None and not isinstance(v, str):
            raise ValueError(f"{key}: a string")
    if not isinstance(data.get("disclosure", True), bool):
        raise ValueError("disclosure: true or false")
    evidence = data.get("evidence", {})
    choices = {"repos": ("environment", "event"), "stores": ("session", "observed"),
               "journal": ("environment", "fixed"), "collector": ("environment", "isolated")}  # the default first
    if not isinstance(evidence, dict) or (bad := sorted(set(evidence) - set(choices) - {"github_api"})):
        raise ValueError(f"[evidence]: {', '.join(bad) if isinstance(evidence, dict) else 'not a table'}: keys "
                         f"{', '.join([*choices, 'github_api'])}")
    for key, values in choices.items():
        if evidence.get(key, values[0]) not in values:
            raise ValueError(f"[evidence] {key} = {evidence[key]!r}: one of {', '.join(values)}")
    api = evidence.get("github_api")
    if api is not None and (not isinstance(api, str) or not api.startswith("https://")
                            or any(c.isspace() or c in "?#" for c in api)):
        raise ValueError(f"[evidence] github_api = {api!r}: an https:// URL")
    if mark is not None:
        import re
        try:
            re.compile(mark)
        except re.error as error:
            raise ValueError(f"final_mark: not a regular expression ({error})") from error
    return Policy(floors=dict(floors), project_intro=project.get("intro", False),
                  project_final_mark=project.get("final_mark", False), final_mark=mark,
                  transcript=one_of("transcript", ("required", "forbidden", "project"), "project"),
                  journal_text=one_of("journal_text", ("forbidden", "project"), "forbidden"),
                  disclosure=data.get("disclosure", True), project_state=project.get("state", False),
                  free_command=free, network=one_of("network", ("allowed", "forbidden"), "allowed"),
                  **{k: evidence.get(k, v[0]) for k, v in choices.items()}, github_api=api.rstrip("/") if api else None)


def load(path: Path | None = None) -> Loaded:
    """The protected policy as it stands now. `path` is for tests; the hook and the CLI never pass one."""
    path = path if path is not None else location()
    if path is None:
        return Loaded(Status.ABSENT, None, Path("<no system location>"))
    try:
        present = path.is_file() or path.exists()
    except OSError as error:
        return Loaded(Status.INVALID, None, path, f"cannot be inspected: {error.strerror or error}")
    if not present:
        return Loaded(Status.ABSENT, None, path)
    if not path.is_file():
        return Loaded(Status.INVALID, None, path, "not a regular file")
    try:
        why = protection_problem(path)
    except Exception as error:  # noqa: BLE001 - what cannot be established is not claimed
        why = f"cannot establish protection: {type(error).__name__}: {error}"
    if why:
        return Loaded(Status.INVALID, None, path, f"not protected: {why}")
    try:
        text = path.read_bytes().decode("utf-8")
    except OSError as error:
        return Loaded(Status.INVALID, None, path, f"cannot be read: {error.strerror or error}")
    except UnicodeDecodeError as error:
        return Loaded(Status.INVALID, None, path, f"not UTF-8 (byte {error.start})")
    try:
        return Loaded(Status.ACTIVE, parse(tomllib.loads(text)), path)
    except tomllib.TOMLDecodeError as error:
        return Loaded(Status.INVALID, None, path, f"not valid TOML: {error}")
    except ValueError as error:
        return Loaded(Status.INVALID, None, path, str(error))


# One reading per hook event: the hook takes a snapshot when an event starts (hook.main) and every part of that event
# asks current(), so the gate, the journal state, the free command and the journal's words judge by the same file
# even if an administrator replaces it meanwhile. Outside an event (the CLI, tests) current() reads it anew.
_SNAPSHOT: contextvars.ContextVar[Loaded | None] = contextvars.ContextVar("buddie_policy", default=None)


def current() -> Loaded:
    return _SNAPSHOT.get() or load()


@contextmanager
def snapshot():
    """The policy read once for the code inside the block (one hook event)."""
    token = _SNAPSHOT.set(load())
    try:
        yield _SNAPSHOT.get()
    finally:
        _SNAPSHOT.reset(token)


TEMPLATE = f"""# buddie protected policy (docs/policy.md). Install it where only an administrator can write:
#   Linux, macOS:  sudo install -d -o root -m 0755 /etc/buddie
#                  sudo install -o root -m 0644 policy.toml /etc/buddie/policy.toml
#   Windows:       an elevated shell: copy policy.toml to %ProgramData%\\buddie\\ and keep its default ACL
# buddie reads it on each hook run and never writes it. Delete or replace it the same way to change it.
version = {VERSION}
transcript = "project"           # "required": always read; "forbidden": never read; "project": as below sources say
journal_text = "forbidden"       # "project" lets buddie.toml keep promise sentences and choice cards in the journal
disclosure = true                # false: a `buddie:` line never lets a returned answer out; only a fix does
network = "allowed"              # "forbidden": no page fetches, no GitHub lookups (pr:, ci: stay unchecked)
# final_mark = "Следующий шаг:"   # the policy's own mark, when final answers are marked
# free_command = "python3 tools/free.py {{n}}"   # the launch gate's free command; BUDDIE_FREE is then ignored

# The weakest level buddie.toml, BUDDIE_GATES or a plugin option may set for each class; they may set a stricter one.
[gates]
anchors = "block"
quotes = "block"
work = "block"
numbers = "warn"

# What the project (buddie.toml, the hook's environment) may still decide. false: ignored, and journaled as refused.
[project]
intro = false        # the intro mode, in which every return is only a warning
final_mark = false   # which answers are final ([mandate] final_mark, BUDDIE_FINAL)
state = false        # BUDDIE_STATE=0, which stops buddie telling a `buddie:` line written before a return from one after

# Where the hook's evidence may come from (docs/policy.md, "Evidence"). The environment and the repo are the agent's.
# A key left out keeps the behaviour without a policy ("environment", "session"); these are the restrictive values.
[evidence]
repos = "event"          # only the checkout around the event; "environment": BUDDIE_REPOS may name other repos
stores = "session"       # "observed": quotes and numbers judged only on bytes the hook fetches in this check
journal = "fixed"        # the default journal places; "environment": BUDDIE_LOG / BUDDIE_SHARED_LOG may move it
collector = "isolated"   # no proxy or CA location from the environment; "environment": as the environment says
# github_api = "https://github.example.com/api/v3"   # GitHub Enterprise; BUDDIE_GITHUB_API is ignored
"""
