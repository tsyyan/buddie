"""How environment diagnostics observe a machine (docs/environment.md, "Diagnostics"; docs/design/environment-diagnostics.md).

Each category's collector lives here and may use only the methods buddie/diagnostics.py declares for it: a program at
a fixed system location or found on PATH, run with a fixed argument list; a fixed file; an interface of the OS or of
Python. Nothing here takes a command, an argument or a file name from the request: a request chooses categories, the
tool names of software.tools (from a fixed catalog) and, for the path-scoped categories, a directory the person
granted.

Programs. Started through buddie/runner.py: no shell, nothing on stdin, stderr discarded, a timeout and an output
limit, the process tree stopped when either is reached, inside the request's deadline. The environment is built from
an allowlist (where programs are, the user's directories some need to start, a C locale), so no token, no *_OPTIONS
(NODE_OPTIONS, JAVA_TOOL_OPTIONS), no LD_PRELOAD or DYLD_*, no DOCKER_HOST or DOCKER_CONTEXT reaches them. The working
directory is the system's temporary directory, never the project. Batch and PowerShell scripts found on PATH
(npm.cmd) are not run: Windows would start them through cmd.exe, whose AutoRun setting the user, and so the agent,
can write. PATH is searched by buddie, absolute entries only (no current directory). Only version- or model-shaped
tokens of an answer are kept: no raw output, no paths.

What a value rests on (basis): "buddie" (buddie's own interpreter), "os_interface" (the OS through Python: platform,
/proc, /sys, the registry, a system call), "fixed_program" (a program at a fixed system location), "path_program" (a
program found on PATH, which the agent can change), "agent_writable" (project files, a repository). None is
attestation.

Standard library only.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import sys
import tempfile
from pathlib import Path

from buddie import runner

BUDDIE, OS_INTERFACE, FIXED_PROGRAM, PATH_PROGRAM, AGENT_WRITABLE = (
    "buddie", "os_interface", "fixed_program", "path_program", "agent_writable")
BASES = (BUDDIE, OS_INTERFACE, FIXED_PROGRAM, PATH_PROGRAM, AGENT_WRITABLE)

PROGRAM_TIMEOUT = 10.0
PROGRAM_OUTPUT = 64 * 1024
FILE_LIMIT = 1024 * 1024
TEXT = 128                      # characters of a model or name kept
SCRIPTS = (".cmd", ".bat", ".ps1", ".vbs", ".js", ".wsf")

# the environment a diagnostic program gets: where programs are and the user's directories some need to start
_INHERITED = ("PATH", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA",
              "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "PATHEXT", "COMSPEC")
_FIXED_ENV = {"LC_ALL": "C", "LANG": "C", "NO_COLOR": "1", "TERM": "dumb", "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
              "DOTNET_NOLOGO": "1", "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1", "HOMEBREW_NO_AUTO_UPDATE": "1",
              "HOMEBREW_NO_ANALYTICS": "1", "CONDA_NO_PLUGINS": "true", "PYTHONIOENCODING": "utf-8"}


def program_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k.upper() in _INHERITED}
    env.update(_FIXED_ENV)
    return env


def platform_key() -> str:
    return "windows" if sys.platform == "win32" else "darwin" if sys.platform == "darwin" else \
        "linux" if sys.platform.startswith("linux") else "other"


# --- what is returned -----------------------------------------------------------------------------------------------

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
VERSION = re.compile(r"(?<![\w.])v?(\d+(?:\.\d+){1,3}(?:[-+][0-9A-Za-z][0-9A-Za-z.]{0,30})?)(?![\w])")


def text(value, limit: int = TEXT) -> str | None:
    """A model or product name as shown to a person: printable, single-spaced, at most `limit` characters, and
    nothing path- or assignment-shaped (no '/', '\\', '='); None when nothing like that is left."""
    if not isinstance(value, str):
        return None
    value = " ".join(_CONTROL.sub(" ", value).split())
    if not value or len(value) > limit or any(c in value for c in "/\\="):
        return None
    return value


def version(output: str | None) -> str | None:
    """The first version-shaped token of a program's answer (1.2, v20.11.1, 3.12.1+, 8.0.100-rc.1), or None."""
    if not output:
        return None
    m = VERSION.search(output)
    return m[1] if m else None


# --- finding and running programs -----------------------------------------------------------------------------------

def which(name: str) -> str | None:
    """`name` on PATH, absolute entries only: an empty or relative entry (the current directory) is skipped, so a
    file the agent drops into a project is never picked by a relative PATH entry. Windows tries PATHEXT."""
    exts = [""]
    if os.name == "nt" and not os.path.splitext(name)[1]:
        exts = [e.lower() for e in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if e.startswith(".")]
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        entry = entry.strip().strip('"')
        if not entry or not os.path.isabs(entry):
            continue
        for ext in exts:
            candidate = os.path.join(entry, name + ext)
            if os.path.isfile(candidate) and (os.name == "nt" or os.access(candidate, os.X_OK)):
                return candidate
    return None


def locate(name: str, fixed: tuple = ()) -> tuple[str | None, str | None]:
    """(the program, its basis): the first of `fixed` (absolute system locations) that is a file, else PATH."""
    for candidate in fixed:
        if candidate and os.path.isabs(candidate) and os.path.isfile(candidate):
            return candidate, FIXED_PROGRAM
    found = which(name)
    return (found, PATH_PROGRAM) if found else (None, None)


def concerns(path: str | None) -> str:
    """Whom an observation is about: a Windows program reached from WSL (/mnt/c/...) answers for the Windows host."""
    return "windows_host" if path and re.match(r"^/mnt/[a-z]/", path) and _wsl() else "runtime"


def run(exe: str, args: tuple, timeout: float = PROGRAM_TIMEOUT) -> tuple[str, str | None]:
    """(outcome, output) of `exe ARGS`: "ok" (exit 0), "exit_nonzero", "timeout", "output_limit", "unavailable" (it
    did not start), "script_not_run" (a batch or PowerShell script: not run, see the module's docstring)."""
    if os.path.splitext(exe)[1].lower() in SCRIPTS:
        return "script_not_run", None
    got = runner.run([exe, *args], env=program_env(), cwd=tempfile.gettempdir(), timeout=timeout,
                     limit=PROGRAM_OUTPUT)
    if got.state != "ok":
        return got.state, None
    out = got.out.decode("utf-8", "replace")
    return ("ok" if got.code == 0 else "exit_nonzero"), out


def read(path: str, limit: int = FILE_LIMIT) -> str | None:
    """A fixed system file's text, at most `limit` bytes; None when it is not there or cannot be read."""
    try:
        with open(path, "rb") as f:
            data = f.read(limit + 1)
    except OSError:
        return None
    if len(data) > limit:
        return None
    return data.decode("utf-8", "replace")


# --- the runtime's context ------------------------------------------------------------------------------------------

def _wsl() -> bool:
    if platform_key() != "linux":
        return False
    release = (read("/proc/sys/kernel/osrelease", 4096) or "").lower()
    return "microsoft" in release or "wsl" in release


def _container() -> str | None:
    """The container engine the runtime is in, when a marker says so: docker, podman, kubernetes, lxc, a cgroup."""
    if platform_key() != "linux":
        return None
    if os.path.exists("/.dockerenv"):
        return "docker"
    if os.path.exists("/run/.containerenv"):
        return "podman"
    cgroup = read("/proc/1/cgroup", 65536) or ""
    for marker, name in (("kubepods", "kubernetes"), ("docker", "docker"), ("containerd", "containerd"),
                         ("libpod", "podman"), ("lxc", "lxc")):
        if marker in cgroup:
            return name
    return None


# --- collectors -----------------------------------------------------------------------------------------------------
# Each is collector(ctx). ctx.observe(name, value, basis, method) records a value, ctx.unavailable(name, reason,
# method) a reason, ctx.attempt(method, why) declares the method being used (only the category's own methods are
# accepted), ctx.program(method, why) locates and runs a declared program, ctx.file(method, why) reads a declared file.

def system_os(ctx) -> None:
    key = platform_key()
    ctx.attempt("platform", "always")
    ctx.observe("family", {"windows": "Windows", "darwin": "macOS", "linux": "Linux"}.get(key, platform.system())
                or None, OS_INTERFACE, "platform")
    ctx.observe("architecture", platform.machine() or None, OS_INTERFACE, "platform")
    ctx.observe("kernel", text(platform.release()), OS_INTERFACE, "platform")
    if key == "linux":
        data = ctx.file("os_release", "linux_distribution")
        fields = dict(re.findall(r'^([A-Z_]+)="?([^"\n]*)"?$', data or "", re.M))
        ctx.observe("name", text(fields.get("NAME")), OS_INTERFACE, "os_release")
        ctx.observe("version", text(fields.get("VERSION_ID"), 32), OS_INTERFACE, "os_release")
        ctx.observe("distribution_id", text(fields.get("ID"), 32), OS_INTERFACE, "os_release")
        ctx.attempt("runtime_markers", "wsl_or_container")
        wsl, engine = _wsl(), _container()
        ctx.observe("runtime_context", "wsl" if wsl else "container" if engine else "native", OS_INTERFACE,
                    "runtime_markers")
        if engine:
            ctx.observe("container_engine", engine, OS_INTERFACE, "runtime_markers")
    elif key == "darwin":
        ctx.attempt("mac_ver", "macos_release")
        ctx.observe("name", "macOS", OS_INTERFACE, "mac_ver")
        ctx.observe("version", text(platform.mac_ver()[0], 32), OS_INTERFACE, "mac_ver")
        ctx.observe("runtime_context", "native", OS_INTERFACE, "mac_ver")
    elif key == "windows":
        ctx.attempt("win32_ver", "windows_release")
        release, ver, _, _ = platform.win32_ver()
        ctx.observe("name", text(f"Windows {release}".strip()), OS_INTERFACE, "win32_ver")
        ctx.observe("version", text(ver, 32), OS_INTERFACE, "win32_ver")
        ctx.observe("edition", text(platform.win32_edition() or None, 64), OS_INTERFACE, "win32_ver")
        ctx.observe("runtime_context", "native", OS_INTERFACE, "win32_ver")
    else:
        ctx.unavailable("name", "unsupported_platform", "platform")


SHELLS = {  # name -> (fixed locations, arguments): --version for each; PowerShell without its profile
    "bash": (("/bin/bash", "/usr/bin/bash"), ("--version",)),
    "zsh": (("/bin/zsh", "/usr/bin/zsh"), ("--version",)),
    "fish": (("/usr/bin/fish", "/opt/homebrew/bin/fish", "/usr/local/bin/fish"), ("--version",)),
    "pwsh": ((), ("-NoLogo", "-NoProfile", "-NonInteractive", "-Command", "$PSVersionTable.PSVersion.ToString()")),
}


def system_shell(ctx) -> None:
    key = platform_key()
    for name, (fixed, args) in SHELLS.items():
        exe, basis, outcome, out = ctx.program(f"shell_{name}", "listed_shell", name, fixed, args)
        ctx.result(name, exe, basis, outcome, version(out), f"shell_{name}")
    if key == "windows":
        system = _system_directory()
        ps = os.path.join(system, "WindowsPowerShell", "v1.0", "powershell.exe") if system else None
        exe, basis, outcome, out = ctx.program("shell_powershell", "windows_powershell", "powershell",
                                               (ps,) if ps else (), SHELLS["pwsh"][1])
        ctx.result("powershell", exe, basis, outcome, version(out), "shell_powershell")
        ctx.attempt("cmd_present", "windows_command_prompt")
        present = bool(system) and os.path.isfile(os.path.join(system, "cmd.exe"))
        ctx.observe("cmd", "present" if present else None, OS_INTERFACE, "cmd_present",
                    reason=None if present else "not_found")
    else:
        ctx.attempt("login_shell", "account_shell")
        try:
            import pwd
            shell = os.path.basename(pwd.getpwuid(os.getuid()).pw_shell or "")
        except (ImportError, KeyError, OSError):
            shell = ""
        ctx.observe("default", text(shell, 32), OS_INTERFACE, "login_shell")


def _system_directory() -> str | None:
    """The Windows system directory as the system names it (GetSystemDirectoryW), not as %SystemRoot% says."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.kernel32.GetSystemDirectoryW(buf, 260):
            return buf.value
    except Exception:  # noqa: BLE001 - no kernel32: no system directory to name
        return None
    return None


def system_permissions(ctx) -> None:
    ctx.attempt("privilege", "current_process")
    if platform_key() == "windows":
        try:
            import ctypes
            elevated = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:  # noqa: BLE001
            ctx.unavailable("elevated", "not_reported", "privilege")
            return
        ctx.observe("elevated", elevated, OS_INTERFACE, "privilege")
    elif hasattr(os, "geteuid"):
        ctx.observe("elevated", os.geteuid() == 0, OS_INTERFACE, "privilege")
    else:
        ctx.unavailable("elevated", "not_reported", "privilege")
    ctx.observe("scope", "this process: a container's or WSL guest's root is not the host's", BUDDIE, "privilege")


def hardware_cpu(ctx) -> None:
    key = platform_key()
    ctx.attempt("platform", "always")
    ctx.observe("architecture", platform.machine() or None, OS_INTERFACE, "platform")
    count = os.cpu_count()
    ctx.observe("logical_cores", count if count else None, OS_INTERFACE, "platform")
    model = None
    if key == "linux":
        info = ctx.file("cpuinfo", "cpu_model") or ""
        m = re.search(r"^(?:model name|Hardware|Model|cpu model)\s*:\s*(.+)$", info, re.M)
        model, method = (text(m[1]) if m else None), "cpuinfo"
    elif key == "darwin":
        _, _, outcome, out = ctx.program("sysctl_cpu", "cpu_model", "sysctl", ("/usr/sbin/sysctl",),
                                         ("-n", "machdep.cpu.brand_string"))
        model, method = (text(out.strip()) if outcome == "ok" and out else None), "sysctl_cpu"
    elif key == "windows":
        ctx.attempt("registry_cpu", "cpu_model")
        model, method = text(_registry(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString")), \
            "registry_cpu"
    else:
        method = "platform"
    ctx.observe("model", model, OS_INTERFACE if method != "sysctl_cpu" else FIXED_PROGRAM, method,
                reason=None if model else "not_reported")


def _registry(path: str, name: str):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
            return winreg.QueryValueEx(key, name)[0]
    except (ImportError, OSError):
        return None


def hardware_memory(ctx) -> None:
    key = platform_key()
    total = available = None
    if key == "linux":
        info = ctx.file("meminfo", "memory_totals") or ""
        kb = {k: int(v) for k, v in re.findall(r"^(MemTotal|MemAvailable):\s+(\d+) kB$", info, re.M)}
        total = kb.get("MemTotal", 0) * 1024 or None
        available = kb.get("MemAvailable", 0) * 1024 or None
        method = "meminfo"
        limit = ctx.file("cgroup_memory", "container_limit")
        if limit and limit.strip().isdigit():
            ctx.observe("cgroup_limit_bytes", int(limit.strip()), OS_INTERFACE, "cgroup_memory")
    elif key == "darwin":
        _, _, outcome, out = ctx.program("sysctl_memory", "memory_total", "sysctl", ("/usr/sbin/sysctl",),
                                         ("-n", "hw.memsize"))
        total = int(out.strip()) if outcome == "ok" and out and out.strip().isdigit() else None
        _, _, outcome, out = ctx.program("vm_stat", "memory_available", "vm_stat", ("/usr/bin/vm_stat",), ())
        if outcome == "ok" and out:
            page = re.search(r"page size of (\d+) bytes", out)
            pages = {k: int(v) for k, v in re.findall(r"^Pages (free|inactive|speculative):\s+(\d+)\.", out, re.M)}
            if page and pages:
                available = sum(pages.values()) * int(page[1])
        method = "sysctl_memory"
    elif key == "windows":
        ctx.attempt("memory_status", "memory_totals")
        total, available = _windows_memory()
        method = "memory_status"
    else:
        method = "platform"
    basis = FIXED_PROGRAM if key == "darwin" else OS_INTERFACE
    ctx.observe("total_bytes", total, basis, method, reason=None if total else "not_reported")
    ctx.observe("available_bytes", available, basis, "vm_stat" if key == "darwin" else method,
                reason=None if available else "not_reported")


def _windows_memory() -> tuple[int | None, int | None]:
    try:
        import ctypes

        class Status(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        status = Status()
        status.dwLength = ctypes.sizeof(Status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys), int(status.ullAvailPhys)
    except Exception:  # noqa: BLE001
        pass
    return None, None


VENDORS = {"0x10de": "NVIDIA", "0x1002": "AMD", "0x8086": "Intel", "0x106b": "Apple", "0x1af4": "virtio",
           "0x15ad": "VMware", "0x1414": "Microsoft"}
NVIDIA_SMI_LINUX = ("/usr/bin/nvidia-smi", "/usr/lib/wsl/lib/nvidia-smi")


def _nvidia_smi_fixed() -> tuple:
    if platform_key() == "windows":
        system = _system_directory()
        return (os.path.join(system, "nvidia-smi.exe"),) if system else ()
    return NVIDIA_SMI_LINUX


def hardware_gpu(ctx) -> None:
    key = platform_key()
    adapters: list[dict] = []
    if key == "linux":
        ctx.attempt("sysfs_drm", "pci_display_devices")
        seen = set()
        for card in sorted(Path("/sys/class/drm").glob("card[0-9]*")) if Path("/sys/class/drm").is_dir() else []:
            if "-" in card.name:
                continue
            vendor = (read(str(card / "device" / "vendor"), 64) or "").strip().lower()
            device = (read(str(card / "device" / "device"), 64) or "").strip().lower()
            if not vendor or (vendor, device, card.resolve().parent) in seen:
                continue
            seen.add((vendor, device, card.resolve().parent))
            item = {"vendor": VENDORS.get(vendor, "other"), "pci_id": f"{vendor}:{device}"[:16]}
            vram = (read(str(card / "device" / "mem_info_vram_total"), 64) or "").strip()
            if vram.isdigit():
                item["vram_bytes"] = int(vram)
            adapters.append(item)
        if os.path.exists("/dev/dxg"):
            ctx.observe("wsl_gpu_bridge", True, OS_INTERFACE, "sysfs_drm")
        if any(a["vendor"] not in ("NVIDIA",) and "model" not in a for a in adapters):
            exe, _, outcome, out = ctx.program("lspci", "follow_up:names_for_pci_ids", "lspci",
                                               ("/usr/bin/lspci", "/usr/sbin/lspci", "/sbin/lspci"), ("-mm", "-nn"))
            if outcome == "ok" and out:
                names = {}
                for line in out.splitlines():
                    f = re.findall(r'"([^"]*)"', line)
                    ids = re.findall(r"\[([0-9a-f]{4})\]", line)
                    if len(f) >= 3 and re.search(r"VGA|3D|Display", f[0]) and len(ids) >= 3:
                        names[f"0x{ids[1]}:0x{ids[2]}"] = text(f[2])
                for a in adapters:
                    if a["pci_id"] in names and names[a["pci_id"]]:
                        a["model"] = names[a["pci_id"]]
    elif key == "windows":
        ctx.attempt("registry_display", "display_adapters")
        adapters = _windows_adapters()
    elif key == "darwin":
        _, _, outcome, out = ctx.program("system_profiler_displays", "display_adapters", "system_profiler",
                                         ("/usr/sbin/system_profiler",), ("SPDisplaysDataType", "-json"), timeout=30)
        items = []
        if outcome == "ok" and out:
            try:
                items = json.loads(out).get("SPDisplaysDataType", [])
            except (ValueError, AttributeError):
                items = None
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                vendor = str(item.get("spdisplays_vendor", ""))
                name = text(item.get("sppci_model") or item.get("_name"))
                entry = {"vendor": "Apple" if "apple" in vendor.lower() or "apple" in (name or "").lower()
                         else text(vendor.replace("sppci_vendor_", "")) or "other"}
                if name:
                    entry["model"] = name
                vram = str(item.get("spdisplays_vram") or item.get("spdisplays_vram_shared") or "")
                if m := re.match(r"^(\d+)\s*(GB|MB)$", vram.strip()):
                    entry["vram_bytes"] = int(m[1]) * (2**30 if m[2] == "GB" else 2**20)
                elif entry["vendor"] == "Apple":
                    entry["memory"] = "unified"
                adapters.append(entry)
            if items is None:
                ctx.unavailable("adapters", "inconclusive_output", "system_profiler_displays")
                return
    method = "registry_display" if key == "windows" else "system_profiler_displays" if key == "darwin" else "sysfs_drm"
    basis = FIXED_PROGRAM if key == "darwin" else OS_INTERFACE
    for a in adapters:
        a.setdefault("source", method)
    exe = None
    if any(a.get("vendor") == "NVIDIA" for a in adapters) or (key == "linux" and os.path.exists("/dev/nvidiactl")):
        exe, smi_basis, outcome, out = ctx.program("nvidia_smi_gpus", "follow_up:nvidia_adapter", "nvidia-smi",
                                                   _nvidia_smi_fixed(),
                                                   ("--query-gpu=name,memory.total", "--format=csv,noheader,nounits"))
        if outcome == "ok" and out:
            rows = [r.rsplit(",", 1) for r in out.strip().splitlines()[:16] if "," in r]
            nvidia = [{"vendor": "NVIDIA", "source": "nvidia_smi_gpus", **({"model": text(n)} if text(n) else {}),
                       **({"vram_bytes": int(m.strip()) * 2**20} if m.strip().isdigit() else {})} for n, m in rows]
            if nvidia:  # nvidia-smi's model and memory replace the listing's; the observation rests on the weaker
                adapters = [a for a in adapters if a.get("vendor") != "NVIDIA"] + nvidia
                method, basis = "nvidia_smi_gpus", smi_basis
    if adapters:
        ctx.observe("adapters", adapters[:16], basis, method, concerns_=concerns(exe) if method == "nvidia_smi_gpus"
                    else "runtime")
    else:
        ctx.unavailable("adapters", "none_found", method)


def _windows_adapters() -> list[dict]:
    out = []
    try:
        import winreg
        base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
            for i in range(64):
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                if not sub.isdigit():
                    continue
                try:
                    with winreg.OpenKey(root, sub) as key:
                        values = {}
                        for name in ("DriverDesc", "ProviderName", "HardwareInformation.qwMemorySize",
                                     "HardwareInformation.MemorySize"):
                            try:
                                values[name] = winreg.QueryValueEx(key, name)[0]
                            except OSError:
                                pass
                except OSError:
                    continue
                model = text(values.get("DriverDesc"))
                if not model:
                    continue
                provider = str(values.get("ProviderName", ""))
                low = (model + " " + provider).lower()
                vendor = next((v for k, v in (("nvidia", "NVIDIA"), ("amd", "AMD"), ("radeon", "AMD"),
                                              ("advanced micro", "AMD"), ("intel", "Intel"),
                                              ("microsoft", "Microsoft")) if k in low), "other")
                entry = {"vendor": vendor, "model": model}
                mem = values.get("HardwareInformation.qwMemorySize", values.get("HardwareInformation.MemorySize"))
                if isinstance(mem, bytes) and len(mem) in (4, 8):
                    mem = int.from_bytes(mem, "little")
                if isinstance(mem, int) and mem > 0:
                    entry["vram_bytes"] = mem
                out.append(entry)
    except ImportError:
        pass
    return out


def hardware_storage(ctx) -> None:
    ctx.attempt("disk_usage", "granted_path")
    try:
        usage = shutil.disk_usage(ctx.path)
    except OSError:
        ctx.unavailable("total_bytes", "unreadable", "disk_usage")
        ctx.unavailable("free_bytes", "unreadable", "disk_usage")
        return
    ctx.observe("total_bytes", int(usage.total), OS_INTERFACE, "disk_usage")
    ctx.observe("free_bytes", int(usage.free), OS_INTERFACE, "disk_usage")


PYTHON_PROBE = ("import importlib.util as u, json, platform, struct, sys; print(json.dumps({'version': "
                "platform.python_version(), 'implementation': sys.implementation.name, 'bits': "
                "struct.calcsize('P') * 8, 'pip': u.find_spec('pip') is not None, 'venv': u.find_spec('venv') is "
                "not None, 'ensurepip': u.find_spec('ensurepip') is not None}))")


def _python_facts(out: str | None) -> dict | None:
    try:
        got = json.loads((out or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None
    if not isinstance(got, dict) or not isinstance(got.get("version"), str) or not version(got["version"]) \
            or not isinstance(got.get("implementation"), str):
        return None
    return {"version": version(got["version"]), "implementation": text(got["implementation"], 32),
            "bits": got.get("bits") if got.get("bits") in (32, 64) else None,
            **{k: got.get(k) is True for k in ("pip", "venv", "ensurepip")}}


def software_python(ctx) -> None:
    ctx.attempt("own_interpreter", "always")
    import importlib.util as u
    ctx.observe("buddie_runtime", {"version": platform.python_version(), "implementation": sys.implementation.name,
                                   "pip": u.find_spec("pip") is not None, "venv": u.find_spec("venv") is not None},
                BUDDIE, "own_interpreter")
    names = ["python3", "python"] if platform_key() != "windows" else ["python", "python3"]
    names += [f"python3.{n}" for n in range(9, 15)] if platform_key() != "windows" else []
    found, seen = [], set()
    for name in names:
        exe = which(name)
        if exe is None:
            continue
        real = os.path.realpath(exe)
        if real in seen:
            continue
        seen.add(real)
        if len(found) >= 8:
            ctx.limit("interpreter_count_limit")
            break
        _, basis, outcome, out = ctx.program("python_on_path", "interpreter_on_path", name, (), ("-I", "-c", PYTHON_PROBE),
                                             exe=exe)
        facts = _python_facts(out) if outcome == "ok" else None
        found.append({"found_via": f"{name} on PATH", **(facts or {"status": outcome if outcome != "ok"
                                                                    else "inconclusive_output"}),
                      **({"concerns": "windows_host"} if concerns(exe) == "windows_host" else {})})
    if platform_key() == "windows":
        exe, basis, outcome, out = ctx.program("py_launcher", "windows_launcher", "py",
                                               _launcher_fixed(), ("--list",))
        if outcome == "ok" and out:
            versions = sorted({m for m in re.findall(r"-V:(\d+\.\d+[\w.-]*)", out)} |
                              {m for m in re.findall(r"^\s*-?(\d+\.\d+)(?:-\d+)?\s", out, re.M)})[:16]
            ctx.observe("py_launcher_versions", versions or [], basis, "py_launcher")
        elif exe is None:
            ctx.unavailable("py_launcher_versions", "not_found", "py_launcher")
        else:
            ctx.unavailable("py_launcher_versions", outcome if outcome != "ok" else "inconclusive_output",
                            "py_launcher")
    if found:
        ctx.observe("interpreters", found, PATH_PROGRAM, "python_on_path")
    else:
        ctx.unavailable("interpreters", "not_found_on_path", "python_on_path")


def _launcher_fixed() -> tuple:
    system = _system_directory()
    return (os.path.join(os.path.dirname(system), "py.exe"),) if system else ()


RUNTIMES = {  # name -> (program, arguments, how its answer is read)
    "node": ("node", ("--version",), "version"),
    "java": ("java", ("--version",), "version"),
    "dotnet_runtimes": ("dotnet", ("--list-runtimes",), "dotnet"),
    "dotnet_sdks": ("dotnet", ("--list-sdks",), "dotnet"),
    "go": ("go", ("version",), "go"),
    "rustc": ("rustc", ("--version",), "version"),
}


def software_runtimes(ctx) -> None:
    for name, (program, args, reader) in RUNTIMES.items():
        exe, basis, outcome, out = ctx.program(f"runtime_{name}", "listed_runtime", program, (), args)
        if reader == "dotnet" and outcome == "ok" and out is not None:
            items = []
            for line in out.splitlines()[:32]:
                m = re.match(r"^\s*(?:([A-Za-z.]+)\s+)?(\d+\.\d+\.\d+[\w.-]*)\s+\[", line)
                if m:
                    items.append(f"{m[1]} {m[2]}" if m[1] else m[2])
            ctx.observe(name, items, basis, f"runtime_{name}", concerns_=concerns(exe))
            continue
        value = version(out.replace("go version go", "go version ") if reader == "go" and out else out)
        ctx.result(name, exe, basis, outcome, value, f"runtime_{name}")


PACKAGE_MANAGERS = {  # name -> (platforms, fixed locations, arguments)
    "uv": (("linux", "darwin", "windows"), (), ("--version",)),
    "pipx": (("linux", "darwin", "windows"), (), ("--version",)),
    "conda": (("linux", "darwin", "windows"), (), ("--version",)),
    "npm": (("linux", "darwin", "windows"), (), ("--version",)),
    "yarn": (("linux", "darwin", "windows"), (), ("--version",)),
    "pnpm": (("linux", "darwin", "windows"), (), ("--version",)),
    "cargo": (("linux", "darwin", "windows"), (), ("--version",)),
    "brew": (("darwin", "linux"), ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"), ("--version",)),
    "apt": (("linux",), ("/usr/bin/apt",), ("--version",)),
    "dnf": (("linux",), ("/usr/bin/dnf",), ("--version",)),
    "pacman": (("linux",), ("/usr/bin/pacman",), ("--version",)),
    "zypper": (("linux",), ("/usr/bin/zypper",), ("--version",)),
    "apk": (("linux",), ("/sbin/apk",), ("--version",)),
    "winget": (("windows",), (), ("--version",)),
    "choco": (("windows",), (), ("--version",)),
}


def software_package_managers(ctx) -> None:
    key = platform_key()
    for name, (platforms, fixed, args) in PACKAGE_MANAGERS.items():
        if key not in platforms:
            continue
        exe, basis, outcome, out = ctx.program(f"pm_{name}", "listed_package_manager", name, fixed, args)
        ctx.result(name, exe, basis, outcome, version(out), f"pm_{name}")


def software_gpu_stack(ctx) -> None:
    key = platform_key()
    if key == "darwin":
        for name in ("nvidia_driver", "cuda_driver", "cuda_toolkit", "rocm"):
            ctx.attempt("platform", "not_applicable")
            ctx.unavailable(name, "not_applicable_on_platform", "platform")
        _, _, outcome, out = ctx.program("system_profiler_metal", "metal_support", "system_profiler",
                                         ("/usr/sbin/system_profiler",), ("SPDisplaysDataType", "-json"), timeout=30)
        family = None
        if outcome == "ok" and out:
            try:
                for item in json.loads(out).get("SPDisplaysDataType", []):
                    family = family or text(str(item.get("spdisplays_mtlgpufamilysupport", "")).replace(
                        "spdisplays_", ""), 48)
            except (ValueError, AttributeError, TypeError):
                family = None
        ctx.observe("metal", family, FIXED_PROGRAM, "system_profiler_metal",
                    reason=None if family else "not_reported")
        return
    driver = None
    if key == "linux":
        data = ctx.file("proc_nvidia", "nvidia_kernel_module")
        m = re.search(r"Kernel Module\s+(?:for\s+\S+\s+)?(\d+\.\d+(?:\.\d+)?)", data or "")
        driver = m[1] if m else None
        if driver:
            ctx.observe("nvidia_driver", driver, OS_INTERFACE, "proc_nvidia")
    exe, basis, outcome, out = ctx.program("nvidia_smi_query", "nvidia_driver", "nvidia-smi", _nvidia_smi_fixed(),
                                           ("-q", "-d", "COMPUTE"))
    if outcome == "ok" and out:
        d = re.search(r"Driver Version\s*:\s*(\d+\.\d+(?:\.\d+)?)", out)
        c = re.search(r"CUDA Version\s*:\s*(\d+\.\d+)", out)
        if not driver:
            ctx.observe("nvidia_driver", d[1] if d else None, basis, "nvidia_smi_query",
                        reason=None if d else "inconclusive_output", concerns_=concerns(exe))
        ctx.observe("cuda_driver", c[1] if c else None, basis, "nvidia_smi_query",
                    reason=None if c else "inconclusive_output", concerns_=concerns(exe))
    else:
        reason = "not_found" if exe is None else outcome
        if not driver:
            ctx.unavailable("nvidia_driver", reason, "nvidia_smi_query")
        ctx.unavailable("cuda_driver", reason, "nvidia_smi_query")
    fixed = ("/usr/local/cuda/bin/nvcc",) if key == "linux" else ()
    exe, basis, outcome, out = ctx.program("nvcc", "cuda_toolkit", "nvcc", fixed, ("--version",))
    m = re.search(r"release (\d+\.\d+)", out or "")
    ctx.result("cuda_toolkit", exe, basis, outcome, m[1] if m else None, "nvcc")
    if key == "linux":
        data = ctx.file("rocm_version", "rocm_install")
        ver = version(data)
        ctx.observe("rocm", ver, OS_INTERFACE, "rocm_version", reason=None if ver else "not_found")
    else:
        ctx.attempt("platform", "rocm_not_probed")
        ctx.unavailable("rocm", "not_probed_on_platform", "platform")


TOOLS = {  # the catalog software.tools may run: name -> arguments that print its version
    "git": ("--version",), "curl": ("--version",), "wget": ("--version",), "make": ("--version",),
    "cmake": ("--version",), "ninja": ("--version",), "gcc": ("--version",), "clang": ("--version",),
    "gh": ("--version",), "jq": ("--version",), "ffmpeg": ("-version",), "ollama": ("--version",),
    "kubectl": ("version", "--client"), "helm": ("version", "--short"), "terraform": ("version",),
    "openssl": ("version",), "sqlite3": ("--version",), "nvcc": ("--version",), "rustup": ("--version",),
    "git-lfs": ("--version",), "pkg-config": ("--version",), "gpg": ("--version",), "tar": ("--version",),
}


def software_tools(ctx) -> None:
    for name in ctx.tools:
        exe, basis, outcome, out = ctx.program(f"tool:{name}", "requested_tool", name, (), TOOLS[name])
        ctx.result(name, exe, basis, outcome, version(out), f"tool:{name}")


def development_containers(ctx) -> None:
    exe, basis, outcome, out = ctx.program("docker_client", "container_client", "docker", (), ("--version",))
    ctx.result("docker_client", exe, basis, outcome, version(out), "docker_client")
    if exe is not None and outcome == "ok":
        # the local default context, whatever the user's config or DOCKER_HOST says: no remote daemon is contacted
        _, _, outcome, out = ctx.program("docker_daemon", "follow_up:client_present", "docker", (),
                                         ("--context", "default", "version", "--format", "{{.Server.Version}}"),
                                         exe=exe)
        if outcome == "ok" and version(out):
            ctx.observe("docker_daemon", {"reachable": True, "version": version(out)}, basis, "docker_daemon",
                        concerns_=concerns(exe))
        else:
            ctx.observe("docker_daemon", {"reachable": False}, basis, "docker_daemon", concerns_=concerns(exe))
            ctx.limit("docker_daemon_unreachable_or_not_permitted")
    exe, basis, outcome, out = ctx.program("podman_client", "container_client", "podman", (), ("--version",))
    ctx.result("podman_client", exe, basis, outcome, version(out), "podman_client")


MANIFESTS = ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile", "poetry.lock", "uv.lock",
             "environment.yml", ".python-version", "package.json", "package-lock.json", "yarn.lock",
             "pnpm-lock.yaml", ".nvmrc", "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts",
             "Gemfile", "composer.json", "CMakeLists.txt", "Makefile", "Dockerfile", "compose.yaml",
             "docker-compose.yml", ".tool-versions")
CONSTRAINT = re.compile(r"^[0-9a-zA-Z.,<>=!~*^| -]{1,64}$")


def development_project(ctx) -> None:
    from buddie import anchors as anc
    root = Path(ctx.path)
    ctx.attempt("manifest_names", "granted_directory_top_level")
    present = []
    for name in MANIFESTS:
        target = root / name
        try:
            if target.is_file() and not target.is_symlink():
                present.append(name)
        except OSError:
            continue
    ctx.observe("manifests", present, AGENT_WRITABLE, "manifest_names")

    def small(name):
        target = anc._inside(root, name)
        if target in (None, anc.OUTSIDE):
            return None
        fd = anc._open(target, root.resolve())
        if fd is None:
            return None
        try:
            data = os.read(fd, 256 * 1024 + 1)
        finally:
            os.close(fd)
        return None if len(data) > 256 * 1024 else data.decode("utf-8", "replace")

    if "pyproject.toml" in present:
        ctx.attempt("pyproject", "follow_up:manifest_present")
        try:
            import tomllib
            req = (tomllib.loads(small("pyproject.toml") or "").get("project") or {}).get("requires-python")
        except (ValueError, AttributeError):
            req = None
        if isinstance(req, str) and CONSTRAINT.match(req.strip()):
            ctx.observe("requires_python", req.strip(), AGENT_WRITABLE, "pyproject")
    if ".python-version" in present:
        ctx.attempt("python_version_file", "follow_up:manifest_present")
        ver = version((small(".python-version") or "").splitlines()[0] if small(".python-version") else None)
        if ver:
            ctx.observe("python_version_file", ver, AGENT_WRITABLE, "python_version_file")
    if "package.json" in present:
        ctx.attempt("package_json", "follow_up:manifest_present")
        try:
            node = ((json.loads(small("package.json") or "{}") or {}).get("engines") or {}).get("node")
        except (ValueError, AttributeError):
            node = None
        if isinstance(node, str) and CONSTRAINT.match(node.strip()):
            ctx.observe("engines_node", node.strip(), AGENT_WRITABLE, "package_json")
    if ".nvmrc" in present:
        ctx.attempt("nvmrc", "follow_up:manifest_present")
        line = (small(".nvmrc") or "").strip().splitlines()[:1]
        if line and CONSTRAINT.match(line[0]):
            ctx.observe("nvmrc", line[0], AGENT_WRITABLE, "nvmrc")
    if "go.mod" in present:
        ctx.attempt("go_mod", "follow_up:manifest_present")
        m = re.search(r"^go (\d+\.\d+(?:\.\d+)?)\s*$", small("go.mod") or "", re.M)
        if m:
            ctx.observe("go_version", m[1], AGENT_WRITABLE, "go_mod")


def development_repository(ctx) -> None:
    from buddie import environment
    ctx.attempt("git", "granted_directory")
    facts, limits = environment.repository(Path(ctx.path))
    for name in ("head", "worktree", "changes", "origin"):
        f = facts[name]
        if f["status"] == "observed":
            ctx.observe(name, f["value"], AGENT_WRITABLE, "git")
        else:
            ctx.unavailable(name, f["reason"], "git")
    for item in limits:
        ctx.limit(item)
