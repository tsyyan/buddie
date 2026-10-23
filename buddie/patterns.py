"""Matching with the regular expressions buddie.toml gives, bounded in time (docs/adversarial.md, ADV-5).

buddie.toml is the repo's, so the agent's to write, and its [mandate] patterns run on the queue's text, the agent's
too. Python's re has no time limit and backtracks: exponentially on some patterns (refused when the file is read,
mandate.pattern_problem), polynomially on many more (`a*a*a*a*b` on 200 characters takes seconds, on 2000 hours).
No list of constructs finds them all. So these patterns are not run in buddie's process: a worker process of its
own (`python -I`, no buddie credentials, nothing but re and json) matches them, each call within CALL seconds and a
hook event's calls together within the budget the hook sets (budget()). A pattern that takes longer has its worker
stopped and raises PatternTimeout: the check cannot be completed, and the gate returns the answer (hook.failed) as
for any check that fails, instead of being held until the host lets the answer out unchecked.

buddie's own default patterns (mandate.DEFAULTS) are run in-process: they are buddie's code, not the agent's.
"""
from __future__ import annotations

import contextvars
import json
import queue
import subprocess
import sys
import threading
import time
from contextlib import contextmanager

CALL = 1.0            # seconds for one match
MAX_TEXT = 1 << 16    # characters of text a pattern is matched on (a queue cell; more is refused)
MAX_MATCHES = 10_000  # matches finditer gives back
_BUDGET: contextvars.ContextVar = contextvars.ContextVar("buddie_pattern_budget", default=None)

STARTUP = 15.0        # seconds for the worker to start (not a pattern's time), and never past the event's budget
CLEANUP = 5.0         # seconds to wait for a stopped worker and the threads on its pipes
WORKER = r"""
import json, re, sys
try:  # Linux: the kernel ends the worker when buddie's process ends, even mid-match (re holds the GIL)
    import ctypes
    ctypes.CDLL(None).prctl(1, 9)  # PR_SET_PDEATHSIG, SIGKILL
except Exception:
    pass
cache = {}
sys.stdout.write("{}\n")
sys.stdout.flush()
for line in sys.stdin:
    q = json.loads(line)
    try:
        key = (q["p"], q["f"])
        rx = cache.get(key)
        if rx is None:
            rx = cache[key] = re.compile(q["p"], q["f"])
        dump = lambda m: None if m is None else [m.span(i) for i in range(rx.groups + 1)]
        t, op = q["t"], q["op"]
        if op == "finditer":
            got = []
            for m in rx.finditer(t):
                got.append(dump(m))
                if len(got) >= q["max"]:
                    break
        elif op == "fullmatch":
            got = dump(rx.fullmatch(t))
        else:
            got = dump(getattr(rx, op)(t, q["pos"]))
        out = {"ok": got, "names": dict(rx.groupindex)}
    except Exception as error:  # a bad pattern or request is an answer, never the worker's end
        out = {"error": f"{type(error).__name__}: {error}"}
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()
"""


class PatternTimeout(RuntimeError):
    """A buddie.toml pattern took longer than its bound, or the event's patterns together did."""


class PatternError(ValueError):
    pass


@contextmanager
def budget(seconds: float):
    """A time budget for every pattern matched inside the block together (one hook event); an outer, shorter one
    stays in force."""
    end = time.monotonic() + seconds
    outer = _BUDGET.get()
    token = _BUDGET.set(end if outer is None else min(outer, end))
    try:
        yield
    finally:
        _BUDGET.reset(token)


class Match:
    """What the worker found, as the parts of re.Match that buddie reads."""

    def __init__(self, text: str, spans: list, names: dict):
        self._text, self._spans, self._names = text, [tuple(s) for s in spans], names

    def _index(self, key) -> int:
        return self._names[key] if isinstance(key, str) else key

    def group(self, key=0):
        start, end = self._spans[self._index(key)]
        return None if start < 0 else self._text[start:end]

    __getitem__ = group

    def start(self, key=0) -> int:
        return self._spans[self._index(key)][0]

    def end(self, key=0) -> int:
        return self._spans[self._index(key)][1]

    def span(self, key=0) -> tuple:
        return self._spans[self._index(key)]

    def groupdict(self) -> dict:
        return {name: self.group(i) for name, i in self._names.items()}


def _until(seconds: float) -> float:
    """The moment `seconds` from now, or the event's budget's end when that comes first."""
    end = _BUDGET.get()
    now = time.monotonic()
    return now + seconds if end is None else min(now + seconds, end)


def _left(by: float) -> float:
    return max(0.0, by - time.monotonic())


class _Worker:
    """One worker process and the two threads on its pipes. Every step has a deadline: its start (ready() within
    STARTUP and the event's budget), writing a request (a thread of its own, joined until the call's deadline: a
    worker that does not read cannot block buddie on a full pipe), and its answer (a line, within the same deadline,
    that is a whole JSON object of the expected shape). Past any of them, or on an incomplete answer, the worker is
    stopped: killed (with its job on Windows), reaped within CLEANUP, its pipes closed; the threads on them end with
    the pipes. At most one worker lives at a time."""

    def __init__(self, by: float):
        from buddie.runner import _windows_job, without_credentials
        import os
        self.proc = subprocess.Popen([sys.executable, "-I", "-c", WORKER], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=without_credentials(),
                                     text=True, encoding="ascii", bufsize=1)
        self.job = _windows_job(self.proc) if os.name == "nt" else None  # ends with buddie's process, too
        self.lines: queue.Queue = queue.Queue()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.writer = None
        try:  # the worker says it is ready: its start is not counted against a pattern's time
            ready = self.lines.get(timeout=_left(by))
        except queue.Empty:
            ready = None
        if ready != "{}\n":
            self.stop()
            raise PatternTimeout("the worker for buddie.toml patterns did not start in time")

    def _read(self):
        try:
            for line in self.proc.stdout:
                self.lines.put(line)
        except (OSError, ValueError):
            pass
        self.lines.put(None)

    def ask(self, request: dict, by: float) -> dict | None:
        """The worker's answer to `request` by the deadline `by`, or None: not written in time, the worker gone, no
        whole answer in time. None leaves the worker to be stopped."""
        data = json.dumps(request) + "\n"  # ASCII: json escapes everything else
        failed = []

        def write():
            try:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
            except (OSError, ValueError) as error:  # the worker ended, or its pipe was closed by stop()
                failed.append(error)
        self.writer = threading.Thread(target=write, daemon=True)
        self.writer.start()
        self.writer.join(_left(by))
        if self.writer.is_alive() or failed:
            return None
        try:
            line = self.lines.get(timeout=_left(by))
        except queue.Empty:
            return None
        if line is None or not line.endswith("\n"):
            return None
        try:
            answer = json.loads(line)
        except ValueError:
            return None
        if not isinstance(answer, dict) or not (("ok" in answer and isinstance(answer.get("names"), dict))
                                                or isinstance(answer.get("error"), str)):
            return None
        return answer

    def stop(self):
        from buddie.runner import _close_job
        try:
            self.proc.kill()
        except OSError:
            pass
        _close_job(self.job, terminate=True)
        self.job = None
        try:
            self.proc.wait(CLEANUP)
        except subprocess.TimeoutExpired:
            pass
        for thread in (self.writer, self.reader):  # a dead worker's pipes are broken: these return
            if thread is not None:
                thread.join(CLEANUP)
        for stream in (self.proc.stdin, self.proc.stdout):
            try:
                stream.close()
            except (OSError, ValueError):
                pass


_worker: _Worker | None = None
_lock = threading.Lock()
TRUSTED: set[str] = set()  # buddie's own patterns (mandate.DEFAULTS), run in-process


def _ask(op: str, pattern: str, text: str, flags: int, pos: int = 0):
    global _worker
    if type(pattern) is not str or type(text) is not str:
        raise PatternError("a pattern and a text")
    if len(text) > MAX_TEXT:
        raise PatternTimeout(f"text over {MAX_TEXT} characters for a buddie.toml pattern")
    if _left(_until(CALL)) <= 0:
        raise PatternTimeout("the time for buddie.toml patterns in this event is spent")
    request = {"op": op, "p": pattern, "f": int(flags), "t": text, "pos": pos, "max": MAX_MATCHES}
    with _lock:
        if _worker is not None and _worker.proc.poll() is not None:  # it ended since: reap it before another
            _worker.stop()
            _worker = None
        if _worker is None:
            _worker = _Worker(_until(STARTUP))
        by = _until(CALL)  # the call's own time starts once the worker is ready
        answer = _worker.ask(request, by)
        if answer is None:
            _worker.stop()
            _worker = None
            raise PatternTimeout(f"buddie.toml pattern {pattern[:60]!r}: no whole answer within "
                                 f"{CALL:.1f} s (the worker was stopped)")
    if "error" in answer:
        raise PatternError(f"buddie.toml pattern {pattern[:60]!r}: {answer['error']}")
    return answer["ok"], answer["names"]


def _local(op, pattern, text, flags, pos):
    import re
    rx = re.compile(pattern, flags)
    if op == "finditer":
        return list(rx.finditer(text))
    return rx.fullmatch(text) if op == "fullmatch" else getattr(rx, op)(text, pos)


def _one(op: str, pattern: str, text: str, flags: int = 0, pos: int = 0):
    if pattern in TRUSTED:
        return _local(op, pattern, text, flags, pos)
    got, names = _ask(op, pattern, text, flags, pos)
    return None if got is None else Match(text, got, names)


def search(pattern: str, text: str, flags: int = 0, pos: int = 0):
    return _one("search", pattern, text, flags, pos)


def match(pattern: str, text: str, flags: int = 0, pos: int = 0):
    return _one("match", pattern, text, flags, pos)


def fullmatch(pattern: str, text: str, flags: int = 0):
    return _one("fullmatch", pattern, text, flags)


def finditer(pattern: str, text: str, flags: int = 0) -> list:
    if pattern in TRUSTED:
        return _local("finditer", pattern, text, flags, 0)
    got, names = _ask("finditer", pattern, text, flags)
    return [Match(text, spans, names) for spans in got]
