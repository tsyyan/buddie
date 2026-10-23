"""Release hardening (docs/release-hardening.md). RH-1: a process's standard input handle can become unusable under
it (on Windows, the Python install manager's command shim was seen to close the handle it gave its child, after
pytest had put its own in that slot). buddie's own child processes never inherit it, so they do not depend on it."""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STARTS = {"run", "Popen", "call", "check_call", "check_output"}


def test_buddie_never_lets_a_child_inherit_its_standard_input():
    """Every program buddie starts is given its standard input (DEVNULL, a pipe, input=), never the process's own:
    that one may be unusable (RH-1), and a child inheriting it fails to start (WinError 6) or reads the agent's
    session."""
    bare = []
    for path in sorted((ROOT / "buddie").rglob("*.py")) + sorted((ROOT / "scripts").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in STARTS \
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess":
                if not any(k.arg in ("stdin", "input") for k in node.keywords):
                    bare.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert bare == [], bare


CHILD = r"""
import ctypes, json, os, subprocess, sys
from ctypes import wintypes
sys.path.insert(0, sys.argv[1])
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.GetStdHandle.restype = wintypes.HANDLE
k32.GetStdHandle.argtypes = [wintypes.DWORD]
k32.CloseHandle.argtypes = [wintypes.HANDLE]
STD = wintypes.DWORD(-10 & 0xFFFFFFFF)
h = k32.GetStdHandle(STD)
k32.CloseHandle(h)  # the RH-1 condition: the slot still names a handle, and the handle is gone
out = {}
try:
    subprocess.run([sys.executable, "-c", "pass"], capture_output=True, timeout=30)
    out["inherited"] = "started"
except OSError as error:
    out["inherited"] = f"OSError {getattr(error, 'winerror', None)}"
from buddie import patterns, runner
got = runner.run([sys.executable, "-c", "print(41 + 1)"], env=dict(os.environ))
out["runner"] = [got.state, got.code, got.out.decode().strip()]
out["git"] = runner.git_text(sys.argv[1], "rev-parse", "--is-inside-work-tree")
m = patterns.search(r"x(?P<n>\d+)", "x12")
out["pattern"] = m.groupdict() if m else None
patterns._worker.stop()
print(json.dumps(out))
"""


@pytest.mark.skipif(os.name != "nt", reason="the Windows standard handle slot")
def test_an_unusable_standard_input_breaks_inheriting_children_and_not_buddies():
    """The hazard and the guarantee, in a process of its own: with its standard input handle closed under it, a child
    started without stdin= fails (the RH-1 signature, WinError 6), while buddie's runner, its git and its pattern
    worker start and answer."""
    p = subprocess.run([sys.executable, "-I", "-c", CHILD, str(ROOT)], capture_output=True, text=True, timeout=120,
                       stdin=subprocess.DEVNULL)
    assert p.returncode == 0, p.stderr[-2000:]
    got = json.loads(p.stdout.strip().splitlines()[-1])
    assert got["inherited"] == "OSError 6", got  # the hazard is real
    assert got["runner"] == ["ok", 0, "42"] and got["pattern"] == {"n": "12"}, got
    assert got["git"] is None or got["git"].strip() == "true", got


@pytest.mark.skipif(os.name != "nt", reason="the Windows standard handle slot")
def test_the_suites_diagnostic_names_an_unusable_standard_input():
    """tests/conftest.py checks the test process's standard input handle after collection and after each test, and
    says so at the end of the run (BUDDIE_RH1_STRICT=1 makes it fail the session): a recurrence of RH-1 is named,
    not a scatter of unrelated-looking failures."""
    import conftest
    assert conftest.stdin_problem() is None  # this run's handle is usable
    code = (f"import sys; sys.path.insert(0, {str(ROOT / 'tests')!r}); import ctypes, conftest; "
            "from ctypes import wintypes; k=ctypes.WinDLL('kernel32'); k.GetStdHandle.restype=wintypes.HANDLE; "
            "k.CloseHandle.argtypes=[wintypes.HANDLE]; "
            "k.CloseHandle(k.GetStdHandle(wintypes.DWORD(-10 & 0xFFFFFFFF))); print(conftest.stdin_problem())")
    p = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60,
                       stdin=subprocess.DEVNULL)
    assert "not a usable handle" in p.stdout, (p.stdout, p.stderr[-500:])
