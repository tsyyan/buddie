"""Task-aware environment diagnostics: what an agent may ask buddie to observe about this machine before it gives
system-specific instructions (docs/environment.md, "Diagnostics"; docs/design/environment-diagnostics.md).

A request names categories (system.os, hardware.gpu, software.python, ...), an optional task description and, for
some categories, tool names or a directory. What is collected is the intersection of

  requested     the categories the caller names
  supported     the static REGISTRY below, on this platform
  granted       the person's grants file (environment.toml in buddie's user configuration directory): "baseline"
                grants the low-sensitivity tier, each sensitive category is named, and a path-scoped category also
                needs its directory inside a granted root
  allowed       an ACTIVE protected policy's [environment] allow (a ceiling; no table: none; INVALID: none)

The request itself grants nothing: its task text is kept as the caller's word, and a field it is not meant to have
(a `consent: true`) makes it invalid. A denied, unsupported or unknown category is answered as such and its collector
is never called.

Collection is deterministic. Categories run in REGISTRY order; each collector (buddie/probes.py) may use only the
methods its entry declares here, choosing among them by what it found (a vendor's tool after its adapter is seen),
and every attempt is recorded with why and how it ended. One deadline covers the request; programs are bounded one
by one (buddie/runner.py). Observations are "observed" (a value, what it rests on, the method, the time) or
"unavailable" (a reason, no value): nothing unknown is filled in, and "not found on PATH" never reads as "absent".

The document (environment-diagnostics-v1) is separate from environment-v0, which is unchanged; when the caller also
asks for artifacts or a report, the v0 snapshot is embedded as is. It is sequential observation, not an atomic
picture of the machine, and nothing in it is signed.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import tomllib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from buddie import probes, runner

FORMAT = "https://github.com/tsyyan/buddie#environment-diagnostics-v1"
CATALOG_FORMAT = "https://github.com/tsyyan/buddie#environment-catalog-v1"
OBSERVED, UNAVAILABLE = "observed", "unavailable"
BASELINE, SENSITIVE = "baseline", "sensitive"
ALL = ("linux", "darwin", "windows")

MAX_CATEGORIES = 32
MAX_TOOLS = 32
MAX_TASK = 200
MAX_PROGRAMS = 96              # programs one request may start, every category together
DEADLINE = 90.0                # seconds for the whole request's programs
MAX_DOCUMENT = 256 * 1024      # bytes of the JSON document
ID = re.compile(r"^[a-z]+\.[a-z_]+$")
TOOL = re.compile(r"^[a-z0-9][a-z0-9.+-]{0,31}$")


@dataclass(frozen=True)
class Method:
    kind: str                            # "interface" (Python, the OS), "file" (fixed paths), "program"
    paths: tuple[str, ...] = ()          # file: the fixed paths, tried in order


@dataclass(frozen=True)
class Module:
    id: str
    tier: str
    summary: str
    observations: tuple[str, ...]
    methods: dict[str, Method]
    platforms: tuple[str, ...] = ALL
    scope: str = "none"                  # "path": needs a granted directory; "tools": needs tool names
    collector: str = ""
    limits: str = ""


P, F, API = Method("program"), (lambda *paths: Method("file", paths)), Method("interface")

REGISTRY: dict[str, Module] = {m.id: m for m in (
    Module("system.os", BASELINE, "operating system family, name, version, kernel, architecture; WSL or container",
           ("family", "name", "version", "edition", "kernel", "architecture", "distribution_id", "runtime_context",
            "container_engine"),
           {"platform": API, "os_release": F("/etc/os-release", "/usr/lib/os-release"),
            "runtime_markers": F("/proc/sys/kernel/osrelease", "/proc/1/cgroup"), "mac_ver": API, "win32_ver": API},
           ALL + ("other",), collector="system_os",
           limits="inside WSL or a container this describes the guest, not the host"),
    Module("system.shell", BASELINE, "shells present and their versions (bash, zsh, fish, PowerShell)",
           ("bash", "zsh", "fish", "pwsh", "powershell", "cmd", "default"),
           {"shell_bash": P, "shell_zsh": P, "shell_fish": P, "shell_pwsh": P, "shell_powershell": P,
            "cmd_present": API, "login_shell": API}, collector="system_shell",
           limits="PowerShell is started without its profile; shells not on PATH or in standard places are not seen"),
    Module("system.permissions", BASELINE, "whether this process runs elevated (root, administrator)",
           ("elevated", "scope"), {"privilege": API}, collector="system_permissions",
           limits="describes buddie's process; no attempt is made to elevate"),
    Module("hardware.cpu", BASELINE, "CPU model, architecture and logical cores", ("model", "architecture",
           "logical_cores"), {"platform": API, "cpuinfo": F("/proc/cpuinfo"), "sysctl_cpu": P, "registry_cpu": API},
           collector="hardware_cpu"),
    Module("hardware.memory", BASELINE, "total and available memory; a container's memory limit",
           ("total_bytes", "available_bytes", "cgroup_limit_bytes"),
           {"platform": API, "meminfo": F("/proc/meminfo"),
            "cgroup_memory": F("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"),
            "sysctl_memory": P, "vm_stat": P, "memory_status": API}, collector="hardware_memory",
           limits="available memory on macOS is free + inactive + speculative pages, an estimate"),
    Module("hardware.gpu", BASELINE, "GPU adapters: vendor, model, video memory",
           ("adapters", "wsl_gpu_bridge"),
           {"sysfs_drm": F("/sys/class/drm"), "lspci": P, "registry_display": API, "system_profiler_displays": P,
            "nvidia_smi_gpus": P}, collector="hardware_gpu",
           limits="NVIDIA models and memory need nvidia-smi; other Linux models need lspci; a WSL guest sees a "
                  "bridged GPU, not the host's adapters"),
    Module("hardware.storage", SENSITIVE, "total and free space of the volume holding a granted directory",
           ("total_bytes", "free_bytes"), {"disk_usage": API}, scope="path", collector="hardware_storage"),
    Module("software.python", BASELINE, "Python interpreters on PATH: version, pip, venv, ensurepip; Windows launcher",
           ("buddie_runtime", "interpreters", "py_launcher_versions"),
           {"own_interpreter": API, "python_on_path": P, "py_launcher": P}, collector="software_python",
           limits="interpreters not on PATH (conda envs, pyenv shims not on PATH) are not seen; no path is returned"),
    Module("software.runtimes", BASELINE, "Node.js, Java, .NET runtimes and SDKs, Go, Rust",
           tuple(probes.RUNTIMES), {f"runtime_{n}": P for n in probes.RUNTIMES}, collector="software_runtimes",
           limits="Java 8 prints its version only on stderr, which buddie does not read: inconclusive"),
    Module("software.package_managers", BASELINE, "package managers present and their versions",
           tuple(probes.PACKAGE_MANAGERS), {f"pm_{n}": P for n in probes.PACKAGE_MANAGERS},
           collector="software_package_managers",
           limits="npm, yarn, pnpm on Windows are batch scripts, found but not run"),
    Module("software.gpu_stack", BASELINE, "NVIDIA driver and CUDA versions, CUDA toolkit, ROCm; Metal on macOS",
           ("nvidia_driver", "cuda_driver", "cuda_toolkit", "rocm", "metal"),
           {"platform": API, "proc_nvidia": F("/proc/driver/nvidia/version"), "nvidia_smi_query": P, "nvcc": P,
            "rocm_version": F("/opt/rocm/.info/version"), "system_profiler_metal": P},
           collector="software_gpu_stack",
           limits="nvidia-smi is asked only for its header and compute mode, never for processes"),
    Module("software.tools", BASELINE, "versions of named tools from a fixed catalog",
           tuple(probes.TOOLS), {f"tool:{n}": P for n in probes.TOOLS}, scope="tools", collector="software_tools",
           limits="only catalog names are run, each with its fixed version argument"),
    Module("development.containers", SENSITIVE, "Docker and Podman clients; whether the local Docker daemon answers",
           ("docker_client", "docker_daemon", "podman_client"),
           {"docker_client": P, "docker_daemon": P, "podman_client": P}, collector="development_containers",
           limits="the daemon is asked only for its version, on the local default context; podman's machine is not "
                  "probed; a daemon that does not answer may be stopped or not permitted"),
    Module("development.project", SENSITIVE, "project manifests at the top of a granted directory; declared versions",
           ("manifests", "requires_python", "python_version_file", "engines_node", "nvmrc", "go_version"),
           {"manifest_names": API, "pyproject": API, "python_version_file": API, "package_json": API, "nvmrc": API,
            "go_mod": API}, scope="path", collector="development_project",
           limits="the directory itself only, no search below it; files the agent can write"),
    Module("development.repository", SENSITIVE, "the git repository at a granted directory: HEAD, clean or dirty, "
           "origin", ("head", "worktree", "changes", "origin"), {"git": API}, scope="path",
           collector="development_repository", limits="as environment-v0's repository facts (agent_writable)"),
)}

UNSUPPORTED = {  # asked for, answered, never probed (docs/design/environment-diagnostics.md)
    "network.connectivity": "makes outbound connections to hosts of the request's choosing; not a description of "
                            "this machine",
    "network.proxy": "proxy settings carry credentials and are another program's configuration",
    "network.ports": "probing ports reaches other services and processes",
    "system.applications": "installed applications and their settings are other programs' data, often personal",
}


# --- authorization ----------------------------------------------------------------------------------------------------

GRANTS_VERSION = 1


@dataclass(frozen=True)
class Grants:
    status: str                                  # "absent", "active", "invalid"
    allow: frozenset = frozenset()
    roots: tuple = ()
    path: Path | None = None
    error: str | None = None


def grants_location() -> Path:
    """The person's grants file: %APPDATA%\\buddie\\environment.toml on Windows, else
    $XDG_CONFIG_HOME/buddie/environment.toml (~/.config). The person's own file, and so the agent's too when it runs
    as the same user (docs/environment.md, "Who decides")."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "buddie" / "environment.toml"


def expand(names) -> set:
    """Grant names to category ids: "baseline" is every baseline category; an id is itself."""
    out = set()
    for name in names:
        out |= {m.id for m in REGISTRY.values() if m.tier == BASELINE} if name == BASELINE else {name}
    return out


def _allow_list(value, where: str) -> set:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{where}: a list of category ids or \"baseline\"")
    bad = [v for v in value if v != BASELINE and v not in REGISTRY]
    if bad:
        raise ValueError(f"{where}: unknown {', '.join(sorted(bad)[:8])} (buddie snapshot --list)")
    return expand(value)


def load_grants(path: Path | None = None) -> Grants:
    """The person's grants as they stand now. Absent: nothing granted. Anything wrong with the file: nothing granted,
    and the reason given (a file that does not say what its author meant must not grant anything)."""
    path = path or grants_location()
    try:
        if not path.exists():
            return Grants("absent", path=path)
        data = tomllib.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        return Grants("invalid", path=path, error=f"cannot be read: {type(error).__name__}")
    try:
        if data.get("version") != GRANTS_VERSION:
            raise ValueError(f"version: {GRANTS_VERSION}")
        if extra := sorted(set(data) - {"version", "allow", "roots"}):
            raise ValueError(f"unknown keys {', '.join(extra)}")
        allow = _allow_list(data.get("allow", []), "allow")
        roots = data.get("roots", [])
        if not isinstance(roots, list) or not all(isinstance(r, str) and r for r in roots):
            raise ValueError("roots: a list of directories")
        resolved = []
        for r in roots:
            p = Path(os.path.expanduser(r))
            if not p.is_absolute():
                raise ValueError(f"roots: {r!r} is not an absolute path")
            resolved.append(Path(os.path.realpath(p)))
    except ValueError as error:
        return Grants("invalid", path=path, error=str(error))
    return Grants("active", frozenset(allow), tuple(resolved), path)


GRANT_TEMPLATE = """# buddie environment diagnostics: what a local agent may ask buddie to observe (docs/environment.md).
# Save as {path}
# This file is yours; an agent running as your user can edit it too. An administrator's protected policy
# ([environment] allow) is the limit an agent cannot change.
version = 1

# "baseline": OS, shells, privilege level, CPU, memory, GPU, Python, runtimes, package managers, GPU stack, catalog tools.
# Sensitive categories are named one by one: hardware.storage, development.containers, development.project,
# development.repository.
allow = ["baseline"]

# Directories the path-scoped categories (hardware.storage, development.project, development.repository) may look at,
# with everything below them. Absolute paths; ~ is your home directory.
roots = []
"""


def decide(requested: list[str], grants: Grants, loaded) -> dict[str, tuple[str, str | None]]:
    """For each requested id: ("allowed", None) or ("denied", reason). `loaded`: policy.Loaded."""
    from buddie.policy import Status
    out = {}
    ceiling = None if loaded.status is Status.ABSENT else set(loaded.effective.environment)
    for cid in requested:
        if ceiling is not None and cid not in ceiling:
            out[cid] = ("denied", "policy_invalid" if loaded.status is Status.INVALID else "policy_ceiling")
        elif grants.status == "invalid":
            out[cid] = ("denied", "grants_invalid")
        elif cid not in grants.allow:
            out[cid] = ("denied", "not_granted")
        else:
            out[cid] = ("allowed", None)
    return out


def _inside(path: Path, roots) -> bool:
    try:
        real = Path(os.path.realpath(path))
    except (OSError, ValueError):
        return False
    return any(real == r or r in real.parents for r in roots)


# --- one category's collection ----------------------------------------------------------------------------------------

REASONS = {  # why an observation is unavailable
    "not_found_on_path", "not_found", "timeout", "output_limit", "unavailable", "exit_nonzero", "script_not_run",
    "inconclusive_output", "not_reported", "unsupported_platform", "none_found", "unreadable",
    "not_applicable_on_platform", "not_probed_on_platform", "not_in_catalog", "program_budget", "redacted",
} | {"git_unavailable", "not_a_repository", "no_commit", "git_error", "unneutralized_filter", "no_remote",
     "local_path", "unrecognized_url", "index_hides_entries"}
CATEGORY_REASONS = {
    "denied": {"not_granted", "grants_invalid", "policy_ceiling", "policy_invalid", "path_not_granted"},
    "unavailable": {"no_path_given", "path_not_found", "no_tools_given", "collector_error", "nothing_observed",
                    "document_size_limit"},
    "unsupported": {"unsupported_platform", "not_supported"},
}
OUTCOMES = {"used", "found", "not_found", "ok", "exit_nonzero", "timeout", "output_limit", "unavailable",
            "script_not_run", "program_budget"}


class Ctx:
    """What one category's collector may do: its own declared methods, nothing else."""

    def __init__(self, module: Module, clock, budget: list[int], path=None, tools=()):
        self.module, self.clock, self.budget, self.path, self.tools = module, clock, budget, path, tuple(tools)
        self.methods: list[dict] = []
        self.observations: dict[str, dict] = {}
        self.limits: list[str] = []

    def _declared(self, method: str) -> Method:
        got = self.module.methods.get(method)
        if got is None:
            raise PermissionError(f"{self.module.id} has no method {method}")
        return got

    def _record(self, method: str, why: str, outcome: str):
        entry = {"method": method, "why": why, "outcome": outcome}
        if entry not in self.methods:
            self.methods.append(entry)

    def attempt(self, method: str, why: str) -> None:
        self._declared(method)
        self._record(method, why, "used")

    def file(self, method: str, why: str) -> str | None:
        declared = self._declared(method)
        if declared.kind != "file":
            raise PermissionError(f"{method} is not a file method")
        for p in declared.paths:
            data = probes.read(p)
            if data is not None:
                self._record(method, why, "found")
                return data
        self._record(method, why, "not_found")
        return None

    def program(self, method: str, why: str, name: str, fixed: tuple, args: tuple, timeout: float | None = None,
                exe: str | None = None):
        """(exe, basis, outcome, output): `name` at a fixed location or on PATH (or `exe`, already found on PATH),
        run with `args`, both fixed in buddie/probes.py."""
        if self._declared(method).kind != "program":
            raise PermissionError(f"{method} is not a program method")
        basis = probes.PATH_PROGRAM
        if exe is None:
            exe, basis = probes.locate(name, fixed)
        if exe is None:
            self._record(method, why, "not_found")
            return None, None, "not_found_on_path" if not fixed else "not_found", None
        if self.budget[0] <= 0:
            self._record(method, why, "program_budget")
            return exe, basis, "program_budget", None
        self.budget[0] -= 1
        outcome, out = probes.run(exe, args, timeout or probes.PROGRAM_TIMEOUT)
        self._record(method, why, outcome)
        return exe, basis, outcome, out

    def observe(self, name: str, value, basis: str, method: str, reason: str | None = None,
                concerns_: str = "runtime") -> None:
        self._declared(method)
        if value is None:
            self.unavailable(name, reason or "not_reported", method)
            return
        value = _value(value)
        if value is None:
            self.unavailable(name, "redacted", method)
            return
        self.observations[name] = {"status": OBSERVED, "value": value, "basis": basis, "method": method,
                                   "observed_at": self.clock(), "reason": None, "concerns": concerns_}

    def unavailable(self, name: str, reason: str, method: str) -> None:
        self._declared(method)
        self.observations[name] = {"status": UNAVAILABLE, "value": None, "basis": None, "method": method,
                                   "observed_at": self.clock(), "reason": reason if reason in REASONS else
                                   "inconclusive_output", "concerns": "runtime"}

    def result(self, name: str, exe, basis, outcome: str, value, method: str) -> None:
        """A program's version: observed, or why not (not found, did not answer, answered something else)."""
        if exe is None:
            self.unavailable(name, outcome if outcome in REASONS else "not_found_on_path", method)
        elif outcome != "ok":
            self.unavailable(name, outcome, method)
        elif value is None:
            self.unavailable(name, "inconclusive_output", method)
        else:
            self.observe(name, value, basis, method, concerns_=probes.concerns(exe))

    def limit(self, code: str) -> None:
        if code not in self.limits:
            self.limits.append(code)


def _private() -> list[str]:
    """Strings that must not leave in a document: the home directory, the user's name as a path part."""
    out = []
    home = os.path.expanduser("~")
    if home and home not in ("~", "/") and len(home) > 3:
        out += [home, home.replace("\\", "/")]
    for key in ("USERNAME", "USER", "LOGNAME"):
        name = os.environ.get(key, "")
        if len(name) >= 3:
            out += [f"/{name}/", f"\\{name}\\", f"/{name}", f"\\{name}"]
    return out


def _value(value, depth: int = 0):
    """A value fit for the document: None, bool, int, a short string, a short list of those or of flat objects of
    those. Anything else, or a string holding the home directory or user name as a path part: None (redacted)."""
    if depth > 2:
        return None
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value if -2**63 <= value < 2**63 else None
    if isinstance(value, str):
        if len(value) > 256 or any(p.lower() in value.lower() for p in _private()):
            return None
        return value
    if isinstance(value, list):
        out = [_value(v, depth + 1) for v in value[:32]]
        return None if any(v is None for v in out) else out
    if isinstance(value, dict):
        if len(value) > 16 or not all(isinstance(k, str) and TOOL.match(k.lower().replace("_", "-")) for k in value):
            return None
        out = {k: _value(v, depth + 1) for k, v in value.items() if v is not None}
        return None if any(v is None for v in out.values()) else dict(sorted(out.items()))
    return None


# --- the request ------------------------------------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_RUNNING = threading.BoundedSemaphore(2)


def validate(categories, tools=None, task=None) -> tuple[list[str], list[dict], list[str], list[dict], str | None]:
    """(known ids in request order, rejected categories, catalog tools, rejected tools, task), or ValueError for a
    request that is not one: not a list of strings, too many entries, a task that is not short text."""
    if type(categories) is not list or not categories or len(categories) > MAX_CATEGORIES:
        raise ValueError(f"categories: a list of 1 to {MAX_CATEGORIES} category ids (buddie snapshot --list)")
    known, rejected = [], []
    for i, c in enumerate(categories):
        if type(c) is not str or len(c) > 64:
            raise ValueError(f"categories[{i}]: a category id")
        if c in REGISTRY or c in UNSUPPORTED:
            if c not in known:
                known.append(c)
        else:
            rejected.append({"index": i, "id": c if ID.match(c) else None,
                             "reason": "unknown_category" if ID.match(c) else "invalid_category"})
    tools = [] if tools is None else tools
    if type(tools) is not list or len(tools) > MAX_TOOLS or any(type(t) is not str or len(t) > 64 for t in tools):
        raise ValueError(f"tools: a list of at most {MAX_TOOLS} tool names from the catalog")
    named, bad_tools = [], []
    for i, t in enumerate(tools):
        if t in probes.TOOLS:
            if t not in named:
                named.append(t)
        else:
            bad_tools.append({"index": i, "name": t if TOOL.match(t) else None, "reason": "not_in_catalog"})
    if task is not None:
        if type(task) is not str or len(task) > MAX_TASK or re.search(r"[\x00-\x1f\x7f]", task):
            raise ValueError(f"task: one line of text, at most {MAX_TASK} characters")
    return known, rejected, named, bad_tools, task


def collect(categories, *, task=None, tools=None, path=None, supplied=None, legacy: dict | None = None,
            grants: Grants | None = None, clock=None) -> dict:
    """An environment-diagnostics-v1 document. `path`: the directory for path-scoped categories (it must lie in a
    granted root). `legacy`: arguments for environment.collect (root, artifacts_named, report), whose v0 snapshot is
    embedded as is. `grants`: the person's grants (default: their file). Raises ValueError for a request that is not
    one, RuntimeError when two collections are already running."""
    from buddie import __version__, environment, policy
    clock = clock or _now
    known, rejected, named_tools, bad_tools, task = validate(categories, tools, task)
    given = environment.supplied_facts(supplied)
    if path is not None and (type(path) is not str or not path or len(path) > 4096 or "\0" in path):
        raise ValueError("path: a directory")
    grants = grants if grants is not None else load_grants()
    if not _RUNNING.acquire(timeout=5):
        raise RuntimeError("two environment collections are already running; try again")
    try:
        with policy.held() as loaded:
            started = clock()
            supported_here = [c for c in known if c in REGISTRY]
            decisions = decide(supported_here, grants, loaded)
            out, limits, budget = {}, [], [MAX_PROGRAMS]
            platform_key = probes.platform_key()
            with runner.deadline(DEADLINE):
                for cid in [c for c in REGISTRY if c in known] + [c for c in UNSUPPORTED if c in known]:
                    out[cid] = _category(cid, platform_key, decisions.get(cid), grants, path, named_tools, bad_tools,
                                         clock, budget, limits)
            snapshot = environment.collect(**legacy, supplied=supplied, clock=clock) if legacy is not None else None
            doc = {
                "format": FORMAT,
                "collector": {"buddie": __version__, "policy": loaded.status.value, "platform": platform_key},
                "request": {"id": uuid.uuid4().hex, "categories": [c for c in categories if isinstance(c, str)
                                                                   and ID.match(c)][:MAX_CATEGORIES],
                            "rejected": rejected, "tools": named_tools, "rejected_tools": bad_tools,
                            "path_given": path is not None},
                "authorization": {"grants": grants.status, "policy": loaded.status.value,
                                  "effective": sorted(c for c, d in decisions.items() if d[0] == "allowed")},
                "started_at": started,
                "finished_at": clock(),
                "observations_concern": "runtime",
                "categories": out,
                "supplied": {**({"task": task} if task is not None else {}), **given},
                "limitations": sorted(set(limits)),
                "snapshot": snapshot,
            }
    finally:
        _RUNNING.release()
    return _bounded(doc)


def _category(cid, platform_key, decision, grants, path, tools, bad_tools, clock, budget, limits) -> dict:
    base = {"status": None, "reason": None, "tier": None, "methods": [], "observations": {}}
    if cid in UNSUPPORTED:
        return dict(base, status="unsupported", reason="not_supported", explanation=UNSUPPORTED[cid])
    module = REGISTRY[cid]
    base["tier"] = module.tier
    if platform_key not in module.platforms:
        return dict(base, status="unsupported", reason="unsupported_platform")
    if decision[0] != "allowed":
        return dict(base, status="denied", reason=decision[1])
    target = None
    if module.scope == "path":
        if path is None:
            return dict(base, status="unavailable", reason="no_path_given")
        if not _inside(Path(path), grants.roots):
            return dict(base, status="denied", reason="path_not_granted")
        target = Path(os.path.realpath(path))
        if not (target.is_dir() or (cid == "hardware.storage" and target.exists())):
            return dict(base, status="unavailable", reason="path_not_found")
    if module.scope == "tools" and not tools and not bad_tools:
        return dict(base, status="unavailable", reason="no_tools_given")
    ctx = Ctx(module, clock, budget, path=str(target) if target else None, tools=tools)
    try:
        getattr(probes, module.collector)(ctx)
    except PermissionError:
        raise  # a collector using another category's method is a bug in buddie, not a result
    except Exception:  # noqa: BLE001 - one category failing does not take the others down
        limits.append(f"{cid}:collector_error")
        return dict(base, status="unavailable", reason="collector_error", methods=ctx.methods)
    if module.scope == "tools":
        for bad in bad_tools:
            if bad["name"]:
                ctx.observations[bad["name"]] = {"status": UNAVAILABLE, "value": None, "basis": None,
                                                 "method": None, "observed_at": clock(), "reason": "not_in_catalog",
                                                 "concerns": "runtime"}
    limits.extend(f"{cid}:{code}" for code in ctx.limits)
    seen = sum(o["status"] == OBSERVED for o in ctx.observations.values())
    status = "collected" if seen and seen == len(ctx.observations) else "partial" if seen else "unavailable"
    return dict(base, status=status, reason="nothing_observed" if status == "unavailable" else None,
                methods=ctx.methods, observations=dict(sorted(ctx.observations.items())))


def _bounded(doc: dict) -> dict:
    """At most MAX_DOCUMENT bytes: the last categories lose their observations first, and say so."""
    for cid in reversed(list(doc["categories"])):
        if len(dumps(doc).encode("utf-8")) <= MAX_DOCUMENT:
            break
        entry = doc["categories"][cid]
        if entry["observations"]:
            entry["observations"], entry["status"], entry["reason"] = {}, "unavailable", "document_size_limit"
            doc["limitations"] = sorted(set(doc["limitations"]) | {f"{cid}:document_size_limit"})
    return doc


def dumps(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# --- discovery --------------------------------------------------------------------------------------------------------

def catalog() -> dict:
    """What can be asked for, with what each category reads and how it is authorized: for an agent to choose."""
    here = probes.platform_key()
    grants = load_grants()
    return {
        "format": CATALOG_FORMAT,
        "platform": here,
        "grants": {"status": grants.status, "allowed": sorted(grants.allow), "roots_count": len(grants.roots)},
        "categories": [{"id": m.id, "tier": m.tier, "summary": m.summary, "observations": list(m.observations),
                        "methods": sorted(m.methods), "platforms": list(m.platforms), "scope": m.scope,
                        "supported_here": here in m.platforms, "limits": m.limits} for m in REGISTRY.values()],
        "unsupported": [{"id": k, "why": v} for k, v in UNSUPPORTED.items()],
        "tools_catalog": sorted(probes.TOOLS),
    }


# --- for a person -----------------------------------------------------------------------------------------------------

def _short(value) -> str:
    if isinstance(value, list):
        return "[" + "; ".join(_short(v) for v in value[:6]) + (" …" if len(value) > 6 else "") + "]"
    if isinstance(value, dict):
        return ", ".join(f"{k} {_short(v)}" for k, v in value.items())
    return str(value)


def lines(doc: dict) -> list[str]:
    """The document for a person: a line per category, its status, then what was observed or why not."""
    out = [f"buddie snapshot: diagnostics of {len(doc['categories'])} categories "
           f"(grants {doc['authorization']['grants']}, policy {doc['authorization']['policy']})"]
    for cid, entry in doc["categories"].items():
        head = f"  {cid}: {entry['status']}" + (f" ({entry['reason']})" if entry.get("reason") else "")
        out.append(head)
        for name, o in entry["observations"].items():
            out.append(f"    {name}: " + (_short(o["value"]) + f"  [{o['basis']}]" if o["status"] == OBSERVED
                                         else f"unavailable ({o['reason']})"))
    for r in doc["request"]["rejected"]:
        where = r["id"] or "categories[%d]" % r["index"]
        out.append(f"  {where}: {r['reason']}")
    if any(e["status"] == "denied" for e in doc["categories"].values()):
        out.append("  denied categories need a grant: buddie snapshot --grants")
    if doc["limitations"]:
        out.append(f"  limitations: {', '.join(doc['limitations'])}")
    return out


def describe_grants() -> list[str]:
    from buddie import policy
    g = load_grants()
    loaded = policy.load()
    out = [f"grants file: {g.path} ({g.status}{': ' + g.error if g.error else ''})",
           f"  granted: {', '.join(sorted(g.allow)) or 'nothing'}",
           f"  roots: {len(g.roots)} granted director{'y' if len(g.roots) == 1 else 'ies'}",
           f"protected policy: {loaded.status.value}"]
    if loaded.status.value != "absent":
        out.append(f"  policy allows: {', '.join(sorted(loaded.effective.environment)) or 'nothing'}")
    if g.status != "active":
        out.append("  to grant: buddie snapshot --grant-template, then save it there and edit it")
    return out


# --- consistency ------------------------------------------------------------------------------------------------------

TOP = {"format", "collector", "request", "authorization", "started_at", "finished_at", "observations_concern",
       "categories", "supplied", "limitations", "snapshot"}
STATUSES = {"collected", "partial", "unavailable", "denied", "unsupported"}
_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def problems(doc) -> list[str]:
    """What makes `doc` not a consistent environment-diagnostics-v1 document. Consistency, not authenticity: a
    consistent document may be written by hand. Only plain JSON data is read (environment._plain)."""
    from buddie import environment
    if type(doc) is not dict:
        return ["not an object"]
    if not environment._plain(doc):
        return ["not plain JSON data"]
    if set(doc) != TOP:
        return [f"keys: missing {sorted(TOP - set(doc))}, unknown {sorted(set(doc) - TOP)}"]
    out = []
    if doc["format"] != FORMAT:
        out.append(f"format is not {FORMAT}")
    for k in ("started_at", "finished_at"):
        if type(doc[k]) is not str or not _TIME.match(doc[k]):
            out.append(f"{k}: not a UTC time")
    cats = doc["categories"]
    if type(cats) is not dict:
        return out + ["categories: an object"]
    for cid, e in cats.items():
        where = f"categories.{cid}"
        if cid not in REGISTRY and cid not in UNSUPPORTED:
            out.append(f"{where}: unknown category")
            continue
        if type(e) is not dict or e.get("status") not in STATUSES:
            out.append(f"{where}: status one of {', '.join(sorted(STATUSES))}")
            continue
        if e["status"] in CATEGORY_REASONS and e.get("reason") not in CATEGORY_REASONS[e["status"]]:
            out.append(f"{where}: {e['status']} needs a known reason")
        obs = e.get("observations")
        if type(obs) is not dict:
            out.append(f"{where}.observations: an object")
            continue
        if e["status"] in ("denied", "unsupported") and obs:
            out.append(f"{where}: {e['status']} but has observations")
        declared = REGISTRY[cid].methods if cid in REGISTRY else {}
        for m in e.get("methods") or []:
            if type(m) is not dict or m.get("method") not in declared or m.get("outcome") not in OUTCOMES:
                out.append(f"{where}.methods: a method this category does not declare, or an unknown outcome")
        for name, o in obs.items():
            w = f"{where}.observations.{name}"
            if type(o) is not dict or set(o) != {"status", "value", "basis", "method", "observed_at", "reason",
                                                 "concerns"}:
                out.append(f"{w}: status, value, basis, method, observed_at, reason, concerns")
                continue
            if o["status"] == OBSERVED:
                if o["value"] is None or o["reason"] is not None or o["basis"] not in probes.BASES:
                    out.append(f"{w}: observed needs a value and a basis, and no reason")
            elif o["status"] == UNAVAILABLE:
                if o["value"] is not None or o["reason"] not in REASONS:
                    out.append(f"{w}: unavailable has a known reason and no value")
            else:
                out.append(f"{w}: status {o['status']!r}")
    if doc["snapshot"] is not None:
        out += [f"snapshot: {p}" for p in environment.problems(doc["snapshot"])]
    try:
        environment.supplied_facts({k: v for k, v in doc["supplied"].items() if k != "task"}
                                   if type(doc["supplied"]) is dict else doc["supplied"])
    except ValueError as error:
        out.append(str(error))
    return out
