"""Where the hook's evidence comes from, kept apart from what the evidence shows.

Five questions, answered in five places:
  selection      which repos and snapshot stores a check reads and where the journal goes: here (repos, store_for)
                 and logbook.log_targets
  provenance     where each was named (Origin, here) and how far a finding's bytes are known (core.Provenance,
                 findings.py, with network_clean and the store's `collected` from here)
  authorization  whether the hook may collect at all (resolved.network_allowed, BUDDIE_FETCH, BUDDIE_GITHUB) and
                 through what network (collector, here)
  results        what the checks found: verify.py, unchanged by any of this
  enforcement    what the protected policy lets the lower sources choose: policy.py's [evidence], read here through
                 policy.current() (one reading per event) and journaled as refused by resolved.limited

The agent runs as the person's OS user, so every local place is within its reach: the repos, the snapshot stores,
the journal, the session transcript. Nothing here makes such a place trusted. What a policy does is keep the *choice*
of evidence from following the agent's settings (the hook's environment, paths named in the transcript), keep the
hook's own fetches off the environment's proxy and CA settings, and, with stores = "observed", judge quotes and
numbers only on bytes the hook fetched itself during the check. Without a policy every choice is as before.
"""
from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# what the environment can set to route or vouch for the hook's own fetches (urllib reads the proxies, OpenSSL the
# CA locations); a policy's collector = "isolated" sets them aside
PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
CA_VARS = ("SSL_CERT_FILE", "SSL_CERT_DIR")
STORE_VARS = ("BUDDIE_STORES", "VERBATIM_STORE")
JOURNAL_VARS = ("BUDDIE_LOG", "BUDDIE_SHARED_LOG")


class Origin(str, Enum):
    """Who named a place the hook takes evidence from. None of these is a person's decision but POLICY."""
    ENVIRONMENT = "environment"   # a variable of the hook's environment (a project's settings can set it)
    TRANSCRIPT = "transcript"     # a path the session named in its own tool calls
    EVENT = "event"               # found around the event: its git checkout, ./.verbatim of its cwd
    REPO = "repo"                 # inside a selected repo: its .verbatim, the sources/ it changed
    POLICY = "policy"             # named by the protected policy
    OBSERVED = "observed"         # a store made for this check, holding only what the hook fetched in it


@dataclass(frozen=True)
class Selected:
    kind: str                     # "repo" or "store"
    path: Path
    origin: Origin


def limits():
    """The protected policy's limits for this event (None: no policy, everything as before)."""
    from buddie import policy
    return policy.current().effective


def env_paths(name: str) -> list[Path]:
    return [Path(p) for p in os.environ.get(name, "").split(os.pathsep) if p]


def repos(event: dict) -> list[Selected]:
    """BUDDIE_REPOS when it names any and no policy keeps the choice to the event (repos = "event"), else the git
    checkout around the event's cwd."""
    from buddie.anchors import find_repos
    named, lim = env_paths("BUDDIE_REPOS"), limits()
    if named and (lim is None or lim.repos == "environment"):
        return [Selected("repo", p, Origin.ENVIRONMENT) for p in named]
    return [Selected("repo", p, Origin.EVENT) for p in find_repos(Path(event.get("cwd") or os.getcwd()))]


@contextmanager
def store_for(cwd: Path, repo_paths: list[Path], transcript: str | None):
    """(store, the stores it reads) for the hook's quotes and numbers. stores = "observed": a new, empty store in a
    temporary directory, gone after the check, so only bytes fetched in this check are judged. Otherwise the stores
    the session used (stores.session_sources), with fetches going where they went before."""
    from buddie.stores import UnionStore, session_sources
    lim = limits()
    if lim is not None and lim.stores == "observed":
        with tempfile.TemporaryDirectory(prefix="buddie-observed-") as tmp:
            yield UnionStore(tmp, []), [Selected("store", Path(tmp), Origin.OBSERVED)]
        return
    chosen = session_sources(cwd, repo_paths, transcript)
    yield UnionStore(None, [s.path for s in chosen]), chosen


def network_clean() -> bool:
    """Whether the hook's fetches reach their hosts with nothing the environment set in between: the collector is
    isolated, or no proxy (environment, or the system settings urllib reads) and no CA location is set."""
    import urllib.request
    if _isolated:
        return True
    return not any(os.environ.get(k) for k in PROXY_VARS + CA_VARS) and not urllib.request.getproxies()


_isolated = False


@contextmanager
def collector():
    """The hook's network for one event. collector = "isolated" (the policy's default): urllib goes direct (no
    proxy from the environment or the system settings) and verifies TLS against the default CA store, without the
    SSL_CERT_FILE / SSL_CERT_DIR the environment may point elsewhere. Without a policy, or with "environment",
    nothing changes. Yields whether the collector is isolated."""
    global _isolated
    lim = limits()
    if lim is None or lim.collector == "environment":
        yield False
        return
    import ssl
    import urllib.request
    saved = {k: os.environ.pop(k) for k in CA_VARS if k in os.environ}
    try:
        context = ssl.create_default_context()
    finally:
        os.environ.update(saved)
    before = urllib.request._opener  # urlopen's installed opener (None: it builds the default one)
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                              urllib.request.HTTPSHandler(context=context)))
    _isolated = True
    try:
        yield True
    finally:
        _isolated = False
        urllib.request._opener = before


def refused(lim) -> list[str]:
    """The evidence settings of lower sources that the policy `lim` sets aside, by name only (resolved.limited)."""
    from buddie import effects
    out = []
    if lim.repos == "event" and env_paths("BUDDIE_REPOS"):
        out.append("evidence.repos")
    if lim.stores == "observed" and any(os.environ.get(k) for k in STORE_VARS):
        out.append("evidence.stores")
    if lim.journal == "fixed" and any(k in os.environ for k in JOURNAL_VARS):
        out.append("evidence.journal")
    if lim.collector == "isolated" and any(os.environ.get(k) for k in PROXY_VARS + CA_VARS):
        out.append("evidence.collector")
    if lim.github_api and effects.ENV_API and effects.ENV_API.rstrip("/") != lim.github_api:
        out.append("evidence.github_api")
    return out
