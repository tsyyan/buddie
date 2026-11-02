"""What every model request cost, written down when it happens.

A run's rows used to carry only what a finished arm counted, so a request inside a run that later failed, or a
request cut off by a spent balance, left no trace, and cache writes and reads were summed into the input. Here each
request that came back is one ledger line, at once: input, cache write, cache read and output counted apart, the
provider's request id, and US dollars only when a price was given (an unknown price is None, never 0).

    ledger = spend.Ledger("main.jsonl.spend.jsonl", budget_tokens=2_000_000, price=spend.price("15,18.75,1.5,75"))
    spend.use(ledger)          # the clients record into the ledger in use
    ...
    print(ledger.totals())

A budget is checked before a request is sent: a run stops between requests, not in the middle of an answer.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

FIELDS = ("input", "cache_write", "cache_read", "output")


class BudgetSpent(Exception):
    """The ledger's token budget is used up: the run stops before the next request."""


def split(usage: dict | None) -> dict:
    """A provider's usage as input / cache_write / cache_read / output, with `reported` False when it said nothing.

    Anthropic's Messages API counts cache writes and reads apart from input_tokens; an OpenAI-style usage counts
    cached tokens inside prompt_tokens (prompt_tokens_details.cached_tokens), so they are taken out of the input.
    """
    u = usage or {}
    if any(k in u for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")):
        out = {"input": int(u.get("input_tokens") or 0), "cache_write": int(u.get("cache_creation_input_tokens") or 0),
               "cache_read": int(u.get("cache_read_input_tokens") or 0), "output": int(u.get("output_tokens") or 0)}
    else:
        prompt = int(u.get("prompt_tokens") or 0)
        cached = int(((u.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0)
        out = {"input": prompt - cached, "cache_write": 0, "cache_read": cached,
               "output": int(u.get("completion_tokens") or 0)}
    out["reported"] = any(out[k] for k in FIELDS)
    return out


def price(text: str | None) -> tuple[float, float, float, float] | None:
    """'input,cache_write,cache_read,output' in US dollars per million tokens, or None."""
    if not text:
        return None
    parts = [float(x) for x in text.split(",")]
    if len(parts) != 4:
        raise ValueError("a price is four numbers: input,cache_write,cache_read,output per million tokens")
    return tuple(parts)  # type: ignore[return-value]


def usd(counts: dict, rates: tuple[float, float, float, float] | None) -> float | None:
    if rates is None or not counts.get("reported", True):
        return None
    return round(sum(counts.get(k, 0) * r for k, r in zip(FIELDS, rates)) / 1e6, 6)


class Ledger:
    def __init__(self, path: str | Path | None = None, budget_tokens: int | None = None,
                 price: tuple[float, float, float, float] | None = None):
        self.path = Path(path) if path else None
        self.budget, self.rates, self.lock = budget_tokens, price, threading.Lock()
        self.sums = {k: 0 for k in FIELDS} | {"requests": 0, "unreported": 0}
        if self.path and self.path.exists():  # a resumed run: what was spent before counts against the budget
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._add(json.loads(line))

    def _add(self, entry: dict) -> None:
        for k in FIELDS:
            self.sums[k] += int(entry.get(k) or 0)
        self.sums["requests"] += 1
        self.sums["unreported"] += not entry.get("reported", True)

    def tokens(self) -> int:
        return sum(self.sums[k] for k in FIELDS)

    def check(self) -> None:
        if self.budget is not None and self.tokens() >= self.budget:
            raise BudgetSpent(f"token budget spent: {self.tokens()} of {self.budget}")

    def record(self, *, provider: str, model: str, usage: dict | None, seconds: float | None = None,
               request_id: str | None = None, status: str = "ok") -> dict:
        entry = {"t": round(time.time(), 3), "provider": provider, "model": model, "status": status,
                 **split(usage), "request_id": request_id,
                 "seconds": None if seconds is None else round(seconds, 2)}
        entry["usd"] = usd(entry, self.rates)
        with self.lock:
            self._add(entry)
            if self.path:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def totals(self) -> dict:
        with self.lock:
            out = dict(self.sums)
        out["usd"] = usd(out | {"reported": True}, self.rates)
        if out["unreported"]:  # dollars over requests that reported nothing are a lower bound, not the cost
            out["usd_is_lower_bound"] = True
        return out


_current: Ledger | None = None


def use(ledger: Ledger | None) -> None:
    global _current
    _current = ledger


def current() -> Ledger | None:
    return _current


def add(rec: dict, usage: dict | None) -> None:
    """Count one request's usage into a run's record: the split fields and the old prompt/completion sums."""
    s = split(usage)
    for k in FIELDS:
        rec[k] = rec.get(k, 0) + s[k]
    rec["prompt_tokens"] = rec.get("prompt_tokens", 0) + s["input"] + s["cache_write"] + s["cache_read"]
    rec["completion_tokens"] = rec.get("completion_tokens", 0) + s["output"]
    rec["usage_unreported"] = rec.get("usage_unreported", 0) + (not s["reported"])
