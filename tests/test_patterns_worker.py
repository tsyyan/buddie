"""PR #36: the pattern worker (buddie/patterns.py) is bounded in every step, not only while it matches: its start,
writing a request, reading the answer, stopping it, starting another. Each case swaps in a worker that misbehaves in
one way and runs in a process of its own under a hard timeout, so a regression is a failed test, never a hung one.
The child reports how long the call took, what it raised, and whether any worker it started is still running."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARD = 60  # seconds: the outer limit of each child, far over every bound under test

CHILD = r"""
import json, subprocess, sys, time
sys.path.insert(0, sys.argv[1])
from buddie import patterns
spec = json.loads(sys.stdin.read())  # on stdin: a 64 K text is over a command line's limit
started_procs = []
real = subprocess.Popen
def spy(*a, **k):
    p = real(*a, **k)
    started_procs.append(p)
    return p
subprocess.Popen = spy
if spec.get("worker"):
    patterns.WORKER = spec["worker"]
patterns.STARTUP = spec.get("startup", 3.0)
patterns.CALL = spec.get("call", 1.0)
out = []
t0 = time.monotonic()
for _ in range(spec.get("calls", 1)):
    t = time.monotonic()
    try:
        with patterns.budget(spec.get("budget", 10.0)):
            m = patterns.search(spec.get("pattern", r"x(?P<n>\d+)"), spec["text"])
        out.append({"ok": m.groupdict() if m else None, "s": time.monotonic() - t})
    except Exception as error:
        out.append({"error": type(error).__name__, "why": str(error)[:120], "s": time.monotonic() - t})
total = time.monotonic() - t0
if patterns._worker is not None:  # the live, healthy worker: stop it as buddie's exit would
    patterns._worker.stop()
time.sleep(0.2)
alive = [p.pid for p in started_procs if p.poll() is None]
print(json.dumps({"calls": out, "total": total, "workers": len(started_procs), "alive": alive}))
"""

READY = 'import sys, time\nsys.stdout.write("{}\\n"); sys.stdout.flush()\n'


def run(spec: dict) -> dict:
    p = subprocess.run([sys.executable, "-I", "-c", CHILD, str(ROOT)], input=json.dumps(spec), capture_output=True,
                       text=True, timeout=HARD)
    assert p.returncode == 0, p.stderr[-2000:]
    return json.loads(p.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("name, worker, text", [
    ("starts but never reads stdin", READY + "time.sleep(600)\n", "é" * ((1 << 16) - 1)),  # ~390 KB as JSON
    ("never sends its ready line", "import time\ntime.sleep(600)\n", "x1"),
    ("an incomplete answer, then waits", READY + 'sys.stdin.readline()\nsys.stdout.write(\'{"ok": [[0\')\n'
                                                 "sys.stdout.flush()\ntime.sleep(600)\n", "x1"),
    ("an incomplete answer, then exits", READY + 'sys.stdin.readline()\nsys.stdout.write(\'{"ok": [[0\')\n', "x1"),
    ("a whole line that is not an answer", READY + 'sys.stdin.readline()\nprint(\'{"verified": true}\')\n'
                                                   'sys.stdout.flush()\ntime.sleep(600)\n', "x1"),
    ("exits during the request", READY + "sys.stdin.read(10)\n", "é" * ((1 << 16) - 1)),
    ("a wrong ready line", 'print("ready")\nimport time\ntime.sleep(600)\n', "x1"),
], ids=lambda v: v if isinstance(v, str) and len(v) < 60 and "\n" not in v and not v.startswith(("x1", "é")) else "")
# short ids: pytest puts the id in an environment variable, and Windows refuses one over 32767 characters
def test_a_misbehaving_worker_is_stopped_within_its_bound(name, worker, text):
    got = run({"worker": worker, "text": text, "startup": 3.0, "call": 1.0})
    [call] = got["calls"]
    assert call.get("error") == "PatternTimeout", (name, call)
    assert call["s"] < 3.0 + 1.0 + 6.0, (name, call)  # startup + call + cleanup
    assert got["alive"] == [], (name, got)


def test_a_worker_that_stops_reading_after_startup():
    worker = READY + 'sys.stdin.readline()\nprint(\'{"ok": null, "names": {}}\')\nsys.stdout.flush()\ntime.sleep(600)\n'
    got = run({"worker": worker, "text": "é" * ((1 << 16) - 1), "calls": 2})
    first, second = got["calls"]
    assert "ok" in first and second.get("error") == "PatternTimeout" and second["s"] < 7
    assert got["alive"] == []


def test_repeated_failures_restart_one_worker_at_a_time_and_leave_none():
    got = run({"worker": READY + "sys.stdin.read(10)\n", "text": "x1", "calls": 6})
    assert [c.get("error") for c in got["calls"]] == ["PatternTimeout"] * 6
    assert got["workers"] == 6 and got["alive"] == [] and got["total"] < 6 * 7


def test_failures_cannot_spend_more_than_the_events_budget():
    got = run({"worker": "import time\ntime.sleep(600)\n", "text": "x1", "calls": 5, "budget": 2.0,
               "startup": 1.5})
    assert got["total"] < 2.0 + 5 * 0.5 + 6  # each later call sees the budget spent and starts nothing
    assert all(c.get("error") == "PatternTimeout" for c in got["calls"]) and got["alive"] == []


def test_the_real_worker_answers_near_the_size_limit_and_refuses_past_it():
    got = run({"text": "a" * ((1 << 16) - 3) + "x12", "calls": 1})
    [call] = got["calls"]
    assert call.get("ok") == {"n": "12"} and call["s"] < 1.0
    got = run({"text": "a" * ((1 << 16) + 1)})
    assert got["calls"][0].get("error") == "PatternTimeout" and got["workers"] == 0  # refused before asking


def test_a_slow_pattern_on_the_real_worker_is_stopped_and_reaped():
    got = run({"pattern": r"a*a*a*a*b", "text": "a" * 2000, "calls": 2})
    assert [c.get("error") for c in got["calls"]] == ["PatternTimeout"] * 2
    assert all(c["s"] < 1.0 + 6 for c in got["calls"]) and got["alive"] == []


def test_a_buddie_toml_pattern_equal_to_a_built_in_one_runs_in_process(monkeypatch):
    """An agent's buddie.toml may give buddie's own default patterns: they are buddie's code, run as such, with
    the same answers and no worker."""
    from buddie import mandate, patterns
    started = []
    real = subprocess.Popen

    def spy(*a, **k):
        started.append(a)
        return real(*a, **k)
    monkeypatch.setattr(subprocess, "Popen", spy)
    monkeypatch.setattr(patterns, "_worker", None)
    cfg = {**mandate.DEFAULTS, "parent": mandate.DEFAULTS["parent"]}
    got = mandate.parse(cfg, "fix ← №12")
    assert got["kind"] == "fix" and got["parent"] == 12 and started == []
    # the same text with one more character is not buddie's: it goes to the worker
    assert patterns.search("(?:" + mandate.DEFAULTS["parent"] + ")", "fix ← №12") is not None and len(started) == 1
    patterns._worker.stop()
    monkeypatch.setattr(patterns, "_worker", None)


def test_the_hook_returns_the_answer_when_the_worker_does_not_read(tmp_path):
    """End to end, in a process of its own: a Stop whose verdict claim meets a worker that never reads goes back
    (exit 2) within the bound, with no worker left."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "buddie.toml").write_text('[mandate]\nparent = "x(?P<parent>\\\\d+)$"\n', encoding="utf-8")
    (repo / "NEXT.md").write_text("| № | Шаг | — | Основание | Статус |\n|---|---|---|---|---|\n"
                                  "| 1 | step | — | basis | предложено |\n", encoding="utf-8")
    code = r"""
import io, json, subprocess, sys, time
sys.path.insert(0, sys.argv[1])
from buddie import hook, patterns
procs = []
real = subprocess.Popen
def spy(*a, **k):
    p = real(*a, **k)
    procs.append(p)
    return p
subprocess.Popen = spy
patterns.WORKER = 'import sys, time\nsys.stdout.write("{}\\n"); sys.stdout.flush()\ntime.sleep(600)\n'
patterns.CALL = 1.0
event = {"hook_event_name": "Stop", "session_id": "s", "cwd": sys.argv[2],
         "last_assistant_message": "Шаг №1: вердикт auto."}
sys.stdin = io.TextIOWrapper(io.BytesIO(json.dumps(event).encode()))
err = io.StringIO()
sys.stderr = err
t = time.monotonic()
rc = hook.main()
s = time.monotonic() - t
time.sleep(0.2)
alive = [p.pid for p in procs if p.poll() is None and "time.sleep(600)" in str(p.args)]
sys.__stdout__.write(json.dumps({"rc": rc, "s": s, "err": err.getvalue()[:300], "alive": alive}) + "\n")
"""
    env = {"BUDDIE_FETCH": "0", "BUDDIE_GITHUB": "0", "BUDDIE_LOG": str(tmp_path / "h.jsonl"), "BUDDIE_LESSONS": "0",
           "BUDDIE_STATE": str(tmp_path / "p"), "BUDDIE_PROMISES": "0", "BUDDIE_REPOS": str(repo),
           "BUDDIE_INTRO": "0", "BUDDIE_SHARED_LOG": "0", "BUDDIE_GATES": "work=block"}
    import os
    p = subprocess.run([sys.executable, "-I", "-c", code, str(ROOT), str(repo)], capture_output=True, text=True,
                       timeout=HARD, env={**{k: v for k, v in os.environ.items() if not k.startswith("BUDDIE_")},
                                          **env}, stdin=subprocess.DEVNULL, encoding="utf-8")
    got = json.loads(p.stdout.strip().splitlines()[-1])
    assert got["rc"] == 2 and "PatternTimeout" in got["err"] and got["s"] < 15 and got["alive"] == [], got


def _alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = wintypes.DWORD()
        k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:  # a zombie is gone for this purpose
        return Path(f"/proc/{pid}/status").read_text().find("State:\tZ") < 0
    except (FileNotFoundError, ProcessLookupError):  # reaped between the signal and the read (#73)
        return False
    except OSError:
        return True


def test_the_worker_ends_with_buddies_process_mid_match():
    """buddie killed while its worker runs a slow match: on Windows (job object) and Linux (PR_SET_PDEATHSIG) the
    worker ends with it. On macOS it runs until its match ends (docs/release-hardening.md, RH-2): recorded here,
    not asserted away."""
    import time
    code = r"""
import sys, threading
sys.path.insert(0, sys.argv[1])
from buddie import patterns
patterns.CALL = 600
patterns.search(r"x", "x")
print(patterns._worker.proc.pid, flush=True)
patterns.search(r"a*a*a*a*b", "a" * 3000)  # minutes: buddie is killed meanwhile
"""
    p = subprocess.Popen([sys.executable, "-I", "-c", code, str(ROOT)], stdout=subprocess.PIPE,
                         stdin=subprocess.DEVNULL, text=True)
    worker = None
    detail = ""
    try:
        worker = int(p.stdout.readline())
        time.sleep(1.0)
        assert _alive(worker)  # matching
        p.kill()
        p.wait(30)
        ended = False
        for _ in range(50):
            if not _alive(worker):  # once gone it stays gone: no second read that a reap can race (#73)
                ended = True
                break
            time.sleep(0.1)
        if not ended:
            detail = f"worker {worker} outlived buddie process {p.pid}"
            if sys.platform.startswith("linux"):
                try:
                    detail += "\n" + Path(f"/proc/{worker}/status").read_text()
                except OSError as error:
                    detail += f"; status unavailable: {error}"
    finally:
        p.kill()
        p.wait(30)
        p.stdout.close()
        if worker is not None and _alive(worker):
            try:
                os.kill(worker, 9)
            except ProcessLookupError:  # it ended between the observation and cleanup
                pass
    if sys.platform == "darwin":
        pytest.skip(f"macOS: the worker {'ended' if ended else 'outlived buddie (known limitation, RH-2)'}")
    assert ended, detail
