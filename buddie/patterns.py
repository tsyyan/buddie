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
MAX_TEXT = 1 << 20    # characters of text a pattern is matched on
MAX_MATCHES = 10_000  # matches finditer gives back
_BUDGET: contextvars.ContextVar = contextvars.ContextVar("buddie_pattern_budget", default=None)

STARTUP = 30.0        # seconds for the worker to start (not the pattern's time: Python's own start on a busy host)
WORKER = r"""
import json, re, sys
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


class _Worker:
    def __init__(self):
        from buddie.runner import without_credentials
        self.proc = subprocess.Popen([sys.executable, "-I", "-c", WORKER], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=without_credentials(),
                                     text=True, encoding="ascii", bufsize=1)
        self.lines: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        try:  # the worker says it is ready: its start is not counted against a pattern's time
            ready = self.lines.get(timeout=STARTUP)
        except queue.Empty:
            ready = None
        if ready is None:
            self.stop()
            raise PatternTimeout("the worker for buddie.toml patterns did not start")

    def _read(self):
        try:
            for line in self.proc.stdout:
                self.lines.put(line)
        except (OSError, ValueError):
            pass
        self.lines.put(None)

    def ask(self, request: dict, timeout: float):
        self.proc.stdin.write(json.dumps(request) + "\n")  # ASCII: json escapes everything else
        self.proc.stdin.flush()
        return self.lines.get(timeout=timeout)

    def stop(self):
        try:
            self.proc.kill()
            self.proc.wait(5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        for stream in (self.proc.stdin, self.proc.stdout):
            try:
                stream.close()
            except OSError:
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
    end = _BUDGET.get()
    allowed = CALL if end is None else min(CALL, end - time.monotonic())
    if allowed <= 0:
        raise PatternTimeout("the time for buddie.toml patterns in this event is spent")
    request = {"op": op, "p": pattern, "f": int(flags), "t": text, "pos": pos, "max": MAX_MATCHES}
    with _lock:
        if _worker is None or _worker.proc.poll() is not None:
            _worker = _Worker()
        try:
            line = _worker.ask(request, allowed)
        except (queue.Empty, OSError, ValueError):
            line = None
        if line is None:
            _worker.stop()
            _worker = None
            raise PatternTimeout(f"buddie.toml pattern {pattern[:60]!r} took over {allowed:.1f} s on the queue's "
                                 "text (stopped)")
    answer = json.loads(line)
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
