"""Spread model requests over several OpenAI-compatible endpoints that serve the same model, at each one's pace.

For experiments that run many independent jobs (a unit with all its arms, a case with all its steps) on free tiers:

- one worker per endpoint (or more, `concurrency`) pulls the next job, so a fast endpoint takes more jobs;
- a job keeps one endpoint: once it has started there it never moves, so a paired comparison inside a job never
  mixes providers; a job not yet started goes to whichever endpoint is free;
- each endpoint keeps its own pace: requests and tokens a minute (sliding window), requests and tokens a day,
  the provider's rate-limit headers (`retry-after`, Groq's `x-ratelimit-*`, IETF `ratelimit-*`), and an adaptive
  rate that halves on a 429 and climbs back on success (AIMD);
- a daily limit takes an endpoint out until its reset (or 00:00 UTC); repeated transport failures pause it
  (circuit breaker); the run ends when every job is done or no endpoint can work before the deadline.

Standard library only. Clock, sleep and transport can be replaced (tests).

    pool = Pool([REGISTRY["ovh"], REGISTRY["groq"]], model="openai/gpt-oss-120b")
    pool.run(jobs, work=lambda job, client: ..., started=lambda job: ..., key=lambda job: job["id"],
             pinned={"U1": "ovh"})
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


class Spent(Exception):
    """This endpoint cannot take more work now (daily limit, request budget, repeated failures)."""

    def __init__(self, message: str, until: float | None = None):
        super().__init__(message)
        self.until = until  # monotonic time it may work again, None: not in this run


@dataclass
class Endpoint:
    name: str
    url: str
    key_env: str | None = None  # None: no key (an anonymous tier)
    model_ids: dict[str, str] = field(default_factory=dict)  # common model name -> this endpoint's id
    rpm: float | None = None
    tpm: int | None = None
    rpd: int | None = None
    tpd: int | None = None
    concurrency: int = 1
    url_env: tuple[str, ...] = ()  # environment variables the url needs, as {NAME}
    extra: dict = field(default_factory=dict)  # added to every request body (e.g. a gateway's routing options)

    def resolve(self, environ=os.environ) -> tuple[str, str]:
        """The url and key from the environment; raises Spent when something is missing."""
        url = self.url
        for name in self.url_env:
            if not environ.get(name):
                raise Spent(f"{name} is not set")
            url = url.replace("{" + name + "}", environ[name])
        key = (environ.get(self.key_env) or "") if self.key_env else ""
        if self.key_env and not key:
            raise Spent(f"{self.key_env} is not set")
        return url, key


GPT_OSS = {"openai/gpt-oss-120b": {"ovh": "gpt-oss-120b", "cloudflare": "@cf/openai/gpt-oss-120b",
                                   "sambanova": "gpt-oss-120b", "cerebras": "gpt-oss-120b", "scaleway": "gpt-oss-120b",
                                   "fastrouter": "openai/gpt-oss-120b:free"},
           "openai/gpt-oss-20b": {"ovh": "gpt-oss-20b", "cloudflare": "@cf/openai/gpt-oss-20b"}}


def _ids(name: str) -> dict[str, str]:
    return {m: ids[name] for m, ids in GPT_OSS.items() if name in ids}


# Free tiers as published on 2026-10-30 (BDX-003 PROVIDERS.md); limits a provider does not publish are left None
# and found from its headers and 429s.
REGISTRY = {
    "ovh": Endpoint("ovh", "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/chat/completions", None, _ids("ovh"),
                    rpm=2),
    "groq": Endpoint("groq", "https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY",
                     rpm=30, tpm=8000, rpd=1000, tpd=200_000),
    "cloudflare": Endpoint("cloudflare",
                           "https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/v1/chat/completions",
                           "CLOUDFLARE_API_TOKEN", _ids("cloudflare"), rpm=60, url_env=("CLOUDFLARE_ACCOUNT_ID",)),
    "gemini": Endpoint("gemini", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                       "GEMINI_API_KEY"),
    "openrouter": Endpoint("openrouter", "https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_API_KEY",
                           rpm=20, rpd=50),
    "github": Endpoint("github", "https://models.github.ai/inference/chat/completions", "GITHUB_TOKEN"),
    # checked 2026-10-31, not yet called with a key (PROVIDERS.md): free but small, and two trials
    "sambanova": Endpoint("sambanova", "https://api.sambanova.ai/v1/chat/completions", "SAMBANOVA_API_KEY",
                          _ids("sambanova"), rpm=20, rpd=20, tpd=200_000),
    "cerebras": Endpoint("cerebras", "https://api.cerebras.ai/v1/chat/completions", "CEREBRAS_API_KEY",
                         _ids("cerebras"), rpm=5, tpm=30_000, tpd=1_000_000),
    "scaleway": Endpoint("scaleway", "https://api.scaleway.ai/v1/chat/completions", "SCALEWAY_API_KEY",
                         _ids("scaleway")),
    "fastrouter": Endpoint("fastrouter", "https://go.fastrouter.ai/api/v1/chat/completions", "FASTROUTER_API_KEY",
                           _ids("fastrouter")),
}
# Vercel AI Gateway: $5 of credits every 30 days for a team that has never paid, usable on gpt-oss-120b at every
# backend it lists. One endpoint per backend, pinned with providerOptions.gateway.only, so a job never changes
# backend; they share one key and one $5 (the pool sees that as each one's 429s and 402s).
for _backend in ("baseten", "groq", "cerebras", "nebius", "parasail", "together", "bedrock"):
    REGISTRY[f"vercel-{_backend}"] = Endpoint(
        f"vercel-{_backend}", "https://ai-gateway.vercel.sh/v1/chat/completions", "AI_GATEWAY_API_KEY",
        extra={"providerOptions": {"gateway": {"only": [_backend]}}})


# ---- pace ----------------------------------------------------------------------------------------------------

_DUR = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")


def seconds(value: str | None) -> float | None:
    """'7.66s', '2m59.5s', '1h2m', '250ms' or a bare number of seconds; None when absent or unreadable."""
    if not value:
        return None
    value = value.strip()
    try:
        return float(value)
    except ValueError:
        pass
    parts = _DUR.findall(value)
    if not parts:
        return None
    unit = {"ms": 0.001, "s": 1, "m": 60, "h": 3600}
    return sum(float(n) * unit[u] for n, u in parts)


def next_utc_midnight(now: datetime | None = None) -> float:
    """Seconds until the next 00:00 UTC."""
    now = now or datetime.now(timezone.utc)
    nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (nxt - now).total_seconds()


class Pace:
    """One endpoint's limits and adaptive rate. Thread-safe."""

    def __init__(self, ep: Endpoint, clock=time.monotonic, sleep=time.sleep, max_wait: float = 300,
                 max_requests: int | None = None, breaker: int = 4, cooldown: float = 300):
        self.ep, self.clock, self.sleep, self.max_wait = ep, clock, sleep, max_wait
        self.lock = threading.Lock()
        self.ceiling = ep.rpm  # the published rate; the adaptive rate moves under it
        self.rate = ep.rpm
        self.recent: deque[float] = deque()  # request times, last 60 s
        self.tokens: deque[tuple[float, int]] = deque()  # (time, tokens), last 60 s
        self.day_requests = self.day_tokens = 0
        self.est = 2000.0  # tokens a request, moving average
        self.left = max_requests
        self.failures, self.breaker, self.cooldown = 0, breaker, cooldown
        self.not_before = 0.0  # from headers or a 429
        self.spent: Spent | None = None
        self.stats = {"requests": 0, "tokens": 0, "throttled": 0, "failures": 0, "seconds": 0.0}

    def _trim(self, now: float) -> None:
        while self.recent and now - self.recent[0] >= 60:
            self.recent.popleft()
        while self.tokens and now - self.tokens[0][0] >= 60:
            self.tokens.popleft()

    def _wait_for(self, now: float) -> float:
        """Seconds to wait before the next request may go (0: now). Called under the lock."""
        self._trim(now)
        wait = max(0.0, self.not_before - now)
        if self.rate:
            if self.recent:
                wait = max(wait, self.recent[-1] + 60.0 / self.rate - now)
            if len(self.recent) >= max(1, int(self.rate)):
                wait = max(wait, self.recent[0] + 60 - now)
        if self.ep.tpm and self.tokens:
            used = sum(t for _, t in self.tokens)
            if used + self.est > self.ep.tpm:
                wait = max(wait, self.tokens[0][0] + 60 - now)
        return wait

    def acquire(self) -> None:
        """Block until a request may go; raise Spent when the endpoint is out."""
        while True:
            with self.lock:
                now = self.clock()
                if self.spent:
                    raise self.spent
                if self.left is not None and self.left <= 0:
                    self.spent = Spent(f"{self.ep.name}: request budget spent")
                    raise self.spent
                if self.ep.rpd and self.day_requests >= self.ep.rpd or \
                        self.ep.tpd and self.day_tokens + self.est > self.ep.tpd:
                    self.spent = Spent(f"{self.ep.name}: daily limit (counted)", now + next_utc_midnight())
                    raise self.spent
                wait = self._wait_for(now)
                if wait <= 0:
                    self.recent.append(now)
                    self.day_requests += 1
                    if self.left is not None:
                        self.left -= 1
                    return
                if wait > self.max_wait:
                    self.spent = Spent(f"{self.ep.name}: next request in {wait:.0f} s", now + wait)
                    raise self.spent
            self.sleep(min(wait, 60))

    def done(self, usage: dict, headers, latency: float) -> None:
        """A request answered: count its tokens, read the rate-limit headers, let the rate climb."""
        used = int((usage or {}).get("prompt_tokens") or 0) + int((usage or {}).get("completion_tokens") or 0)
        with self.lock:
            now = self.clock()
            self.tokens.append((now, used))
            self.day_tokens += used
            if used:
                self.est = 0.8 * self.est + 0.2 * used
            self.failures = 0
            self.stats["requests"] += 1
            self.stats["tokens"] += used
            self.stats["seconds"] += latency
            cap = self.ceiling or 600.0  # no published rate: climb back up to a high cap after a 429
            if self.rate and self.rate < cap:
                self.rate = min(cap, self.rate + max(0.25, cap / 20 if self.ceiling else 1.0))
            self._headers(headers, now)

    def _headers(self, headers, now: float) -> None:
        if headers is None:
            return
        get = headers.get
        for remaining, reset in (("x-ratelimit-remaining-requests", "x-ratelimit-reset-requests"),
                                 ("x-ratelimit-remaining-tokens", "x-ratelimit-reset-tokens"),
                                 ("ratelimit-remaining", "ratelimit-reset")):
            try:
                left = float(get(remaining)) if get(remaining) is not None else None
            except ValueError:
                left = None
            if left is None:
                continue
            need = self.est if "tokens" in remaining else 1
            if left < need:
                self.not_before = max(self.not_before, now + (seconds(get(reset)) or 60))

    def throttled(self, retry_after: float | None) -> None:
        """A 429: halve the rate, wait as asked; a wait past max_wait spends the endpoint until then."""
        with self.lock:
            now = self.clock()
            self.stats["throttled"] += 1
            self.rate = max(0.5, (self.rate or 60) / 2)
            wait = retry_after if retry_after is not None else 60.0 / self.rate
            if wait > self.max_wait:
                self.spent = Spent(f"{self.ep.name}: rate limit, retry after {wait:.0f} s", now + wait)
                raise self.spent
            self.not_before = max(self.not_before, now + wait)

    def failed(self) -> None:
        """A transport error or a 5xx: after `breaker` in a row the endpoint pauses for `cooldown` seconds."""
        with self.lock:
            now = self.clock()
            self.failures += 1
            self.stats["failures"] += 1
            if self.failures >= self.breaker:
                self.failures = 0
                self.spent = Spent(f"{self.ep.name}: {self.breaker} failures in a row", now + self.cooldown)
                raise self.spent
            self.not_before = max(self.not_before, now + 5 * 2 ** (self.failures - 1))

    def revive(self) -> bool:
        """Lift a spent state whose time has come; True when the endpoint may work again."""
        with self.lock:
            if self.spent and self.spent.until is not None and self.clock() >= self.spent.until:
                if "daily" in str(self.spent):
                    self.day_requests = self.day_tokens = 0
                self.spent = None
            return self.spent is None


# ---- transport -----------------------------------------------------------------------------------------------

def urllib_send(url: str, headers: dict, body: dict, timeout: float = 180):
    """POST JSON; returns (status, headers, raw bytes). HTTP errors are returned, not raised."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


class TransportError(Exception):
    pass


class EndpointClient:
    """A chat client for one endpoint under its Pace; `chat` has the shape of BDX-003's Client.chat."""

    def __init__(self, ep: Endpoint, model: str, pace: Pace, send=urllib_send, temperature: float | None = 0.0,
                 max_tokens: int = 4000, user_agent: str = "buddie-experiments/1 (+https://github.com/tsyyan/buddie)",
                 environ=os.environ):
        self.ep, self.pace, self.send = ep, pace, send
        self.url, self.key = ep.resolve(environ)
        self.model = ep.model_ids.get(model, model)
        self.temperature, self.max_tokens, self.user_agent = temperature, max_tokens, user_agent

    def chat(self, messages: list[dict], tools: list | None) -> tuple[dict, dict]:
        body = {"model": self.model, "messages": messages, "max_tokens": self.max_tokens, **self.ep.extra}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if tools:
            body["tools"] = tools
        headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": self.user_agent}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        while True:
            self.pace.acquire()
            t0 = self.pace.clock()
            try:
                status, rheaders, raw = self.send(self.url, headers, body)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                self.pace.failed()  # raises Spent after `breaker` in a row
                continue
            if status == 429:
                if b"quota" in (raw or b"").lower():  # a used-up quota (Gemini's free tier), not a pace to slow to
                    with self.pace.lock:
                        self.pace.spent = Spent(f"{self.ep.name}: quota: {raw[:160]!r}")
                    raise self.pace.spent
                self.pace.throttled(seconds((rheaders or {}).get("retry-after")))
                continue
            if status >= 500:
                self.pace.failed()
                continue
            if status in (401, 402, 403):  # the key or the account, not this job: out for this run
                with self.pace.lock:
                    self.pace.spent = Spent(f"{self.ep.name}: HTTP {status}: {raw[:160]!r}")
                raise self.pace.spent
            if status >= 400:
                raise TransportError(f"HTTP {status}: {raw[:300]!r}")
            try:
                data = json.loads(raw)
                msg, usage = data["choices"][0]["message"], data.get("usage") or {}
            except (ValueError, KeyError, IndexError, TypeError) as e:
                raise TransportError(f"HTTP {status}: not a chat completion: {raw[:200]!r}") from e
            self.pace.done(usage, rheaders, self.pace.clock() - t0)
            return msg, usage


# ---- scheduling ----------------------------------------------------------------------------------------------

class Pool:
    """Workers per endpoint pulling jobs; a started job stays with its endpoint."""

    def __init__(self, endpoints: list[Endpoint], model: str, clock=time.monotonic, sleep=time.sleep,
                 send=urllib_send, environ=os.environ, log=print, temperature: float | None = 0.0,
                 max_tokens: int = 4000, **pace_args):
        self.clock, self.sleep, self.log = clock, sleep, log
        self.clients: dict[str, EndpointClient] = {}
        self.paces: dict[str, Pace] = {}
        for ep in endpoints:
            pace = Pace(ep, clock=clock, sleep=sleep, **pace_args)
            try:
                self.clients[ep.name] = EndpointClient(ep, model, pace, send=send, environ=environ,
                                                       temperature=temperature, max_tokens=max_tokens)
            except Spent as e:
                log(f"endpoint {ep.name} left out: {e}")
                continue
            self.paces[ep.name] = pace
        if not self.clients:
            raise Spent("no endpoint is usable")
        self.endpoints = [ep for ep in endpoints if ep.name in self.clients]
        self.lock = threading.Lock()  # for callers writing shared files from work()

    def run(self, jobs: list, work, started, key, pinned: dict | None = None, deadline: float | None = None) -> dict:
        """Run work(job, client, endpoint_name) for every job until done, no endpoint can go on, or deadline.

        `started(job)` says whether any of the job's work is recorded (then it is pinned to the endpoint that
        did it); `pinned` maps job keys to endpoints from earlier runs. work() raising Spent stops that endpoint;
        any other exception is the caller's to record inside work() — here it is logged and the job left.
        """
        pinned = dict(pinned or {})
        lock = threading.Condition()
        queue = list(jobs)
        busy: set = set()
        left = {key(j) for j in jobs}

        def take(name: str):
            for j in queue:
                k = key(j)
                if k not in busy and pinned.get(k) in (None, name):
                    queue.remove(j)
                    busy.add(k)
                    return j
            return None

        def can_still_work(name: str) -> bool:
            sp = self.paces[name].spent
            return sp is None or (sp.until is not None and (deadline is None or sp.until < deadline))

        def worker(name: str):
            client, pace = self.clients[name], self.paces[name]
            while True:
                if deadline is not None and self.clock() >= deadline:
                    return
                if not pace.revive():
                    if not can_still_work(name):
                        return
                    self.sleep(min(60.0, max(1.0, pace.spent.until - self.clock())))
                    continue
                with lock:
                    job = take(name)
                    if job is None:
                        if not busy:
                            return  # nothing queued is mine and nothing in flight can come back
                        lock.wait(timeout=5)  # a job in flight elsewhere may come back unstarted
                        continue
                k = key(job)
                try:
                    work(job, client, name)
                    with lock:
                        left.discard(k)
                except Spent as e:
                    self.log(f"endpoint {name}: {e}")
                    with lock:
                        if started(job):
                            pinned[k] = name  # it waits for this endpoint
                        queue.insert(0, job)
                except Exception as e:  # noqa: BLE001 - the caller records failures inside work()
                    self.log(f"job {k} at {name}: {e!r}")
                    with lock:
                        left.discard(k)
                finally:
                    with lock:
                        busy.discard(k)
                        if started(job):
                            pinned.setdefault(k, name)
                        lock.notify_all()

        threads = [threading.Thread(target=worker, args=(ep.name,), daemon=True, name=f"pool-{ep.name}-{i}")
                   for ep in self.endpoints for i in range(max(1, ep.concurrency))]
        for t in threads:
            t.start()
        for t in threads:
            while t.is_alive():
                t.join(timeout=1)  # short joins keep Ctrl-C (and `timeout --signal=INT`) working
        return {"left": sorted(left), "pinned": pinned,
                "endpoints": {n: dict(p.stats, spent=str(p.spent) if p.spent else None) for n, p in self.paces.items()}}
