"""Snapshot store: source bytes by sha256, plus an index of which URL gave which bytes when.

Layout (same snapshot naming as components/evidence_corpus CAS):
    <store>/snapshots/<sha256>   raw response body, never modified
    <store>/index.json           {"<url>": [{"sha256", "fetched_at", "http_status", "content_type", "final_url",
                                             "content_encoding"?}, ...]}

The newest entry for a URL is the one a check uses. Failed fetches are recorded too (sha256 null),
so "the source was unavailable" is evidence, not a silent gap.
"""
from __future__ import annotations

import contextvars
import hashlib
import http.client
import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urldefrag, urlsplit, urlunsplit

USER_AGENT = "Mozilla/5.0 (compatible; verbatim/0.2; quote checker)"
DEFAULT_STORE = ".verbatim"
MAX_PAGE_BYTES = 32 * 2**20  # a body larger than this is a failed fetch, not a snapshot: read no further than this


class TooLarge(OSError):
    pass


class BudgetSpent(OSError):
    """A network call past the budget of the check it serves: a failed fetch, so the source is unavailable."""


class OverBudget(Exception):
    """The check ran past its time budget in work that is not a fetch: it stops, and gives no receipt."""


class Budget:
    """What one check may spend on the network: TCP connections (every request, retry and redirect opens one), body
    bytes read, and wall time. The caller that serves strangers (remote.py) sets BUDGET; local checks run without.
    The connection side is enforced where sockets are opened (remote._connect), the bytes in read_body, the time
    there and at check_time() in the loops whose cost grows with page size."""

    def __init__(self, requests: int, total_bytes: int, seconds: float):
        self.requests, self.bytes, self.until = requests, total_bytes, time.monotonic() + seconds
        self.seconds = seconds

    def left(self) -> float:
        return self.until - time.monotonic()

    def connect(self) -> float:
        """Spend one connection; the seconds left, for its socket timeout."""
        if self.left() <= 0:
            raise BudgetSpent(f"time budget of {self.seconds:g} s spent")
        if self.requests <= 0:
            raise BudgetSpent("request budget spent")
        self.requests -= 1
        return self.left()


BUDGET: contextvars.ContextVar[Budget | None] = contextvars.ContextVar("verbatim_budget", default=None)


def check_time() -> None:
    """For loops whose cost grows with the page (closest passage, numbers): stop when the check's time is spent."""
    budget = BUDGET.get()
    if budget is not None and budget.left() <= 0:
        raise OverBudget(f"the check ran past its time budget of {budget.seconds:g} s")


def read_body(response, limit: int | None = None) -> bytes:
    """The body of an HTTP response, never more than `limit` (MAX_PAGE_BYTES) + 1 bytes in memory; TooLarge past it.
    Under a Budget the body also counts against its bytes and is read in pieces with the time checked between them,
    so a server that sends a byte now and then cannot hold the check past its time."""
    limit = MAX_PAGE_BYTES if limit is None else limit
    budget = BUDGET.get()
    if budget is None:
        data = response.read(limit + 1)
    else:
        read, data = getattr(response, "read1", None) or response.read, bytearray()
        while len(data) <= limit:
            if budget.left() <= 0:
                raise BudgetSpent(f"time budget of {budget.seconds:g} s spent while reading")
            chunk = read(min(1 << 16, limit + 1 - len(data)))
            if not chunk:
                break
            data += chunk
            budget.bytes -= len(chunk)
            if budget.bytes < 0:
                raise BudgetSpent("byte budget spent")
        data = bytes(data)
    if len(data) > limit:
        raise TooLarge(f"body over {limit // 2**20} MiB, not stored")
    return data


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_url(url: str) -> str:
    return urldefrag(url.strip())[0]


def request_url(url: str) -> str:
    """An IRI as a URL urllib can send: IDNA host, percent-encoded non-ASCII path and query (E005: es-us.noticias...)."""
    parts = urlsplit(url.strip())
    host = parts.hostname.encode("idna").decode("ascii") if parts.hostname else ""
    netloc = host + (f":{parts.port}" if parts.port else "")
    if parts.username:
        netloc = parts.username + (f":{parts.password}" if parts.password else "") + "@" + netloc
    safe = "/%:@!$&'()*+,;=~-._?"
    return urlunsplit((parts.scheme, netloc, quote(parts.path, safe=safe), quote(parts.query, safe=safe), ""))


class Store:
    _lock = threading.Lock()  # record() rewrites index.json; `buddie-verbatim access --jobs` calls it from threads

    def __init__(self, root: str | os.PathLike | None = None) -> None:
        self.root = Path(root or os.environ.get("VERBATIM_STORE") or DEFAULT_STORE)
        self.snapshots = self.root / "snapshots"
        self.index_path = self.root / "index.json"

    def index(self) -> dict[str, list[dict]]:
        if self.index_path.exists():
            return json.loads(self.index_path.read_text())
        return {}

    def _write_index(self, index: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(index, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
        tmp.replace(self.index_path)

    def put(self, data: bytes) -> str:
        sha = hashlib.sha256(data).hexdigest()
        path = self.snapshots / sha
        if not path.exists():
            self.snapshots.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")  # same bytes from two threads
            tmp.write_bytes(data)
            try:
                tmp.replace(path)
            except PermissionError:  # Windows: another thread is replacing the same snapshot right now
                if not path.exists():
                    raise
                tmp.unlink(missing_ok=True)
        return sha

    def record(self, url: str, entry: dict) -> dict:
        with self._lock:
            index = self.index()
            index.setdefault(canonical_url(url), []).append(entry)
            self._write_index(index)
        return entry

    def add(self, url: str, data: bytes, *, content_type: str | None = None, fetched_at: str | None = None,
            http_status: int | None = 200, final_url: str | None = None, content_encoding: str | None = None,
            **meta) -> dict:
        """meta: where the bytes came from when not from the cited URL itself (access.py: via, provenance, ...)."""
        sha = self.put(data)
        entry = {"sha256": sha, "bytes": len(data), "fetched_at": fetched_at or now(), "http_status": http_status,
                 "content_type": content_type, "final_url": final_url or url, **meta}
        if content_encoding and content_encoding.lower() != "identity":
            entry["content_encoding"] = content_encoding  # bytes are kept exactly as sent; decoded when read
        return self.record(url, entry)

    def fetch(self, url: str, timeout: float = 30) -> dict:
        request = urllib.request.Request(request_url(url), headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return self.add(url, read_body(response), content_type=response.headers.get("Content-Type"),
                                http_status=response.status, final_url=response.geturl(),
                                content_encoding=response.headers.get("Content-Encoding"))
        except urllib.error.HTTPError as error:
            return self.record(url, {"sha256": None, "fetched_at": now(), "http_status": error.code,
                                     "content_type": error.headers.get("Content-Type"), "final_url": url,
                                     "error": f"HTTP {error.code}"})
        except http.client.IncompleteRead as error:
            # a body cut off mid-transfer (E014): the part that came is not the page, so it is a failed fetch,
            # not a snapshot a quote could be missing from; str() of it is only the byte counts
            return self.record(url, {"sha256": None, "fetched_at": now(), "http_status": None,
                                     "content_type": None, "final_url": url, "error": f"incomplete read: {error!r}"[:200]})
        except (urllib.error.URLError, TimeoutError, OSError, UnicodeError, ValueError, http.client.HTTPException) as error:
            return self.record(url, {"sha256": None, "fetched_at": now(), "http_status": None,
                                     "content_type": None, "final_url": url, "error": str(error)[:200] or repr(error)[:200]})

    def latest(self, url: str) -> dict | None:
        entries = self.index().get(canonical_url(url))
        return entries[-1] if entries else None

    def read(self, sha: str) -> bytes:
        data = (self.snapshots / sha).read_bytes()
        if hashlib.sha256(data).hexdigest() != sha:
            raise ValueError(f"snapshot {sha} does not match its hash")
        return data

    def resolve(self, ref: str) -> tuple[dict, bytes]:
        """A URL (newest snapshot) or a sha256 / unique sha256 prefix."""
        entry = self.latest(ref)
        if entry is None and len(ref) >= 8 and all(c in "0123456789abcdef" for c in ref):
            matches = [e for es in self.index().values() for e in es if (e.get("sha256") or "").startswith(ref)]
            entry = matches[-1] if matches else None
        if entry is None or not entry.get("sha256"):
            raise KeyError(ref)
        return entry, self.read(entry["sha256"])
