"""Where the local MCP server keeps verification feedback chains (docs/feedback.md#mcp): one directory per chain in
buddie's state dir, made whole or not at all, and changed only by replacing its trace with a longer one under a lock.

  <state dir>/feedback/<chain hex>/trace.jsonl   trace.dumps lines
                                   options.json  the check options the chain was started with, and their digest
                                   lock          the chain's lock (held while its trace is read or replaced)

  - Start: both files are written and synced in a hidden temporary directory, which is then renamed to the chain's
    name. An interruption before the rename leaves only the temporary directory (ignored, removed after STALE
    seconds), never half a chain; a second start of the same chain finds the name taken (`chain_exists`).
  - Resolve: the trace is read under the lock, the submission checked without it (a re-verification can fetch), and
    the longer trace committed under the lock only if the file is still the one read: else the other writer's
    record decides (`duplicate_submission`) or nothing is written (`chain_changed`). The trace is written to a
    temporary file, synced and renamed over the old one, so a failed write (`write_failed`) or a crash leaves the old
    trace whole and a retry possible. The lock is the operating system's (fcntl, msvcrt) and goes with the process
    that held it: a crash leaves no stale lock.
  - Integrity: options.json carries the sha256 of its chain and options; a trace that does not replay, options that
    are not the contract's or whose digest is not theirs, are `state_corrupt`. This detects a damaged file, not who
    wrote it: the files are on the agent's machine and agent-writable (core.Provenance AGENT_WRITABLE), and anyone
    who can write them can write a consistent chain with a matching digest. What the agent cannot write is this
    process's memory: a chain this server started or committed is checked against the options digest and newest
    record it remembers (`state_tampered`), and every result says on which basis the chain was read (`server`, or
    `agent_writable` after a restart of the server).
  - Retention: a chain whose files have not changed for RETENTION seconds is removed when a chain is started, open or
    not (a removed chain can no longer be resolved; it never turns into a result), and at most MAX_CHAINS are kept
    (`state_full` until older ones age out or are removed by hand). A trace is at most MAX_TRACE_BYTES (the repair
    budget keeps a chain to a few dozen records), the options at most MAX_OPTIONS_BYTES.
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from buddie import feedback as fb, receipts, trace as tr

OPTIONS_V1 = "https://github.com/tsyyan/buddie#feedback-options-v1"
OPTION_KEYS = frozenset({"repos", "store", "fetch", "access", "numbers", "github", "transcript", "profile", "modules",
                         "checks"})
MAX_CHAINS = 256
RETENTION = 30 * 86400
STALE = 3600
MAX_TRACE_BYTES = 2**20
MAX_OPTIONS_BYTES = 64 * 2**10
LOCK_TIMEOUT = 30.0

# chain -> (options digest, newest record_id) of the chains this process started or committed
_KNOWN: dict[str, tuple[str, str]] = {}


class ChainError(ValueError):
    """A chain that cannot be started, read or committed; `code` says why. Nothing was written."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class Chain:
    chain: str
    records: tuple
    state: tr.State
    options: dict
    digest: str          # of the chain and its options
    trace: bytes         # the trace file as it was read
    basis: str           # "server": checked against this process's memory; "agent_writable": the files alone


def root() -> Path:
    """The state dir, as the hook's: BUDDIE_STATE, default ~/.cache/buddie/pending. BUDDIE_STATE=0 stops the gate's
    return tracking; a chain still needs its files, so they are kept in the default place then."""
    state = os.environ.get("BUDDIE_STATE", "")
    return (Path(state) if state not in ("", "0") else Path.home() / ".cache" / "buddie" / "pending") / "feedback"


def directory(chain) -> Path:
    if not isinstance(chain, str) or not fb.ID.match(chain):
        raise ChainError("malformed_chain", "a chain is sha256:<64 hex>, as feedback_start returned it")
    return root() / chain.split(":", 1)[1]


def digest(chain: str, options: dict) -> str:
    return fb.digest(receipts.dumps({"chain": chain, "options": options}).encode("utf-8"))


def _strings(value) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def valid_options(o) -> bool:
    """Whether `o` is check options as mcp.check_options makes them (keys, types and vocabularies)."""
    return (isinstance(o, dict) and set(o) == OPTION_KEYS and _strings(o["repos"]) and isinstance(o["store"], str)
            and isinstance(o["fetch"], bool) and isinstance(o["github"], bool) and o["numbers"] in ("gap", "fail", "off")
            and all(o[k] is None or isinstance(o[k], str) for k in ("access", "transcript"))
            and o["profile"] in (None, "developer", "research", "complete", "custom")
            and all(o[k] is None or _strings(o[k]) for k in ("modules", "checks")))


def _write(path: Path, data: bytes) -> None:
    with path.open("xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def _read(path: Path, limit: int) -> bytes:
    """Bound allocation before parsing agent-writable state, including the commit-time reread."""
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ChainError("state_corrupt", "a chain file is over its size limit")
    return data


@contextlib.contextmanager
def _locked(where: Path, timeout: float | None = None):
    """The chain's lock, across processes."""
    timeout = LOCK_TIMEOUT if timeout is None else timeout
    with (where / "lock").open("a+b") as f:
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ChainError("chain_busy", "another call holds the chain; try again") from None
                time.sleep(0.02)
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


def _age(path: Path, now: float) -> float:
    try:
        times = [path.stat().st_mtime] + [p.stat().st_mtime for p in path.iterdir()]
    except OSError:
        return 0.0
    return now - max(times)


def prune(now: float | None = None) -> int:
    """Remove chains unchanged for RETENTION seconds and temporary directories older than STALE; how many."""
    now, removed = time.time() if now is None else now, 0
    base = root()
    if not base.is_dir():
        return 0
    for entry in base.iterdir():
        if not entry.is_dir():
            continue
        temporary = entry.name.startswith(".")
        if _age(entry, now) > (STALE if temporary else RETENTION):
            shutil.rmtree(entry, ignore_errors=True)
            removed += not entry.exists()
    return removed


def count() -> int:
    base = root()
    return sum(1 for e in base.iterdir() if e.is_dir() and not e.name.startswith(".")) if base.is_dir() else 0


def create(chain: str, records: tuple, options: dict) -> None:
    """A new chain's directory, whole or not at all."""
    final = directory(chain)
    if not valid_options(options):
        raise ChainError("malformed_options", "check options outside the contract")
    sealed = digest(chain, options)
    body = (json.dumps({"schema": OPTIONS_V1, "chain": chain, "options": options, "sha256": sealed},
                       ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    if len(body) > MAX_OPTIONS_BYTES:
        raise ChainError("options_too_large", f"check options over {MAX_OPTIONS_BYTES} bytes (too many repos?)")
    trace = tr.dumps(records).encode("utf-8")
    if len(trace) > MAX_TRACE_BYTES:
        raise ChainError("trace_too_large", f"initial trace over {MAX_TRACE_BYTES} bytes; no chain was started")
    prune()
    if final.exists():
        raise ChainError("chain_exists", f"{chain} exists already (the same check of the same text); not started again")
    if count() >= MAX_CHAINS:
        raise ChainError("state_full", f"{MAX_CHAINS} chains are kept already; older ones are removed after "
                                       f"{RETENTION // 86400} days, or remove some from {root()}")
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = final.parent / f".{final.name}.{uuid.uuid4().hex}"
    try:
        temporary.mkdir()
        _write(temporary / "options.json", body)
        _write(temporary / "trace.jsonl", trace)
        try:
            os.rename(temporary, final)
        except OSError:
            if final.exists():
                raise ChainError("chain_exists", f"{chain} was started by another call") from None
            raise
    except OSError as error:
        raise ChainError("write_failed", f"the chain was not started: {error}") from None
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
    _KNOWN[chain] = (sealed, records[-1]["record_id"])


def _parse(chain: str, trace: bytes, options: bytes) -> tuple[tuple, tr.State, dict, str]:
    if len(trace) > MAX_TRACE_BYTES or len(options) > MAX_OPTIONS_BYTES:
        raise ChainError("state_corrupt", "a chain file is over its size limit")
    try:
        records = tr.loads(trace.decode("utf-8"))
        state = tr.replay(records)
        doc = json.loads(options.decode("utf-8"))
        ok = (isinstance(doc, dict) and set(doc) == {"schema", "chain", "options", "sha256"}
              and doc["schema"] == OPTIONS_V1 and doc["chain"] == chain == state.chain
              and valid_options(doc["options"]) and doc["sha256"] == digest(chain, doc["options"]))
    except (tr.TraceError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise ChainError("state_corrupt", f"the chain's files do not replay: {error}") from None
    if not ok:
        raise ChainError("state_corrupt", "the chain's options are not its own (contract, chain or digest)")
    return records, state, doc["options"], doc["sha256"]


def load(chain: str) -> Chain:
    """The chain as its files say, checked against this process's memory when it is known here."""
    where = directory(chain)
    if not (where / "trace.jsonl").is_file():
        raise ChainError("unknown_chain", f"no chain {chain} here: start one with feedback_start")
    with _locked(where):
        try:
            trace = _read(where / "trace.jsonl", MAX_TRACE_BYTES)
            options = _read(where / "options.json", MAX_OPTIONS_BYTES)
        except FileNotFoundError:
            raise ChainError("state_corrupt", "the chain's directory is missing a file") from None
    records, state, opts, sealed = _parse(chain, trace, options)
    known = _KNOWN.get(chain)
    if known is not None and known != (sealed, records[-1]["record_id"]):
        raise ChainError("state_tampered", "the chain's files changed outside this server since it last wrote them")
    return Chain(chain, records, state, opts, sealed, trace, "server" if known else "agent_writable")


def commit(read: Chain, records: tuple, recheck) -> None:
    """Replace the trace `read` came from with `records` (which extend it), if the file is still the one read.
    recheck(state): called with the newer state when it is not, to refuse in its terms (repair.admit)."""
    where = directory(read.chain)
    data = tr.dumps(records).encode("utf-8")
    if not data.startswith(read.trace) or len(data) > MAX_TRACE_BYTES:
        raise ChainError("write_failed", "a commit only extends the trace, within its size limit")
    with _locked(where):
        try:
            now = _read(where / "trace.jsonl", MAX_TRACE_BYTES)
        except FileNotFoundError:
            raise ChainError("unknown_chain", "the chain was removed while the submission was checked") from None
        if now != read.trace:
            try:
                newer = tr.replay(tr.loads(now.decode("utf-8")))
            except (tr.TraceError, ValueError, KeyError, TypeError, AttributeError) as error:
                raise ChainError("state_corrupt", f"the chain's file does not replay: {error}") from None
            recheck(newer)
            raise ChainError("chain_changed", "the chain changed while this submission was checked: nothing written")
        temporary = where / f".trace.{uuid.uuid4().hex}"
        try:
            _write(temporary, data)
            os.replace(temporary, where / "trace.jsonl")
        except OSError as error:
            raise ChainError("write_failed", f"nothing was written: {error}") from None
        finally:
            with contextlib.suppress(OSError):
                temporary.unlink()
    _KNOWN[read.chain] = (read.digest, records[-1]["record_id"])
