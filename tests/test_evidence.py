"""PR #29: evidence trust boundaries. What the hook's environment, the repo or the transcript names as evidence is
not taken as the person's choice once the protected policy's [evidence] says so; without that key (or without a
policy) everything is as before. Each attack below is shown working in the legacy setting and stopped by the key."""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tempfile
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from buddie import effects, evidence, findings, hook, logbook, policy, resolved
from buddie.core import Provenance
from buddie.evidence import Origin
from buddie.verbatim.store import Store

QUOTE = "the outage began at 14:59 UTC and was resolved within two hours"
FILLER = "Background paragraph about the service. " * 40
REAL = f"<html><body><p>{FILLER}</p><p>The company said the outage began at 15:30 UTC.</p></body></html>".encode()
FORGED = f"<html><body><p>{FILLER}</p><p>The company said {QUOTE}.</p></body></html>".encode()
HELLO = hashlib.sha256(b"hello\n").hexdigest()[:12]


class Pages(BaseHTTPRequestHandler):
    pages: dict = {}

    def do_GET(self):  # noqa: N802 - http.server's name
        body = self.pages.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    """A web server, and (asked for an absolute URL) a proxy: `pages` maps a path or a full URL to its bytes."""
    handler = type("Handler", (Pages,), {"pages": {}})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", handler.pages
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def admin(tmp_path, monkeypatch):
    """install(text): the administrator's policy file (protection stands in for root or admin ownership, which a
    test cannot create; tests/test_policy.py and test_trust_boundary.py test that on real files)."""
    place = tmp_path / "system" / "policy.toml"
    monkeypatch.setattr(policy, "location", lambda: place)
    monkeypatch.setattr(policy, "protection_problem", lambda p: None)
    for k in ("BUDDIE_GATES", "BUDDIE_FINAL", "BUDDIE_NUMBERS"):
        monkeypatch.delenv(k, raising=False)
    for k, v in (("BUDDIE_GITHUB", "0"), ("BUDDIE_LOG", str(tmp_path / "hook.jsonl")), ("BUDDIE_LESSONS", "0"),
                 ("BUDDIE_STATE", str(tmp_path / "pending")), ("BUDDIE_PROMISES", "0")):
        monkeypatch.setenv(k, v)

    def install(text: str | None):
        if text is None:
            place.unlink(missing_ok=True)
            return
        place.parent.mkdir(parents=True, exist_ok=True)
        place.write_text(text, encoding="utf-8")
    return install


def git_repo(path: Path, data: bytes) -> Path:
    path.mkdir(parents=True)
    (path / "data.txt").write_bytes(data)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def stop(cwd: Path, text: str, monkeypatch, capsys) -> tuple[int, str]:
    event = {"hook_event_name": "Stop", "session_id": "s", "cwd": str(cwd), "last_assistant_message": text}
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(event).encode("utf-8"))))
    code = hook.main()
    return code, capsys.readouterr().err


def judged(text: str, cwd: Path):
    """The hook's own assessment of `text`, inside one event's policy snapshot and collector."""
    with policy.snapshot(), evidence.collector():
        ctx = resolved.resolve({"cwd": str(cwd)})
        receipt, stores, found = hook.assess_for(text, {"cwd": str(cwd)}, ctx=ctx)
    return receipt["predicate"], stores, found, ctx


GATES = 'version = 1\n[gates]\nquotes = "block"\nanchors = "block"\n'


# --- the contract: [evidence] in policy v1 ------------------------------------------------------------------------

def test_a_policy_without_evidence_keeps_every_legacy_choice():
    got = policy.parse({"version": 1, "gates": {"quotes": "block"}})
    assert (got.repos, got.stores, got.journal, got.collector, got.github_api) == \
        ("environment", "session", "environment", "environment", None)
    strict = policy.STRICTEST
    assert (strict.repos, strict.stores, strict.journal, strict.collector) == \
        ("environment", "session", "environment", "environment")


def test_the_template_sets_the_restrictive_values():
    import tomllib
    got = policy.parse(tomllib.loads(policy.TEMPLATE))
    assert (got.repos, got.stores, got.journal, got.collector) == ("event", "session", "fixed", "isolated")


@pytest.mark.parametrize("table, why", [
    ('repos = "anywhere"', "repos"), ('stores = "trusted"', "stores"), ('journal = false', "journal"),
    ('collector = "off"', "collector"), ('github_api = "http://ghe.example/api"', "github_api"),
    ('github_api = "https://ghe.example/api?x=1"', "github_api"), ('registry = "x"', "registry"),
])
def test_a_bad_evidence_table_makes_the_policy_invalid(admin, table, why):
    admin(GATES + "[evidence]\n" + table + "\n")
    got = policy.load()
    assert got.status is policy.Status.INVALID and why in got.error
    assert got.effective is policy.STRICTEST


# --- BUDDIE_REPOS: which checkout anchors are judged against ------------------------------------------------------

def test_repos_from_the_environment_are_set_aside_by_repos_event(admin, tmp_path, monkeypatch, capsys):
    real = git_repo(tmp_path / "real", b"edited by the agent\n")
    decoy = git_repo(tmp_path / "decoy", b"hello\n")  # a checkout made to make the anchor hold
    monkeypatch.setenv("BUDDIE_REPOS", str(decoy))
    text = f"Done. `⚓ data.txt#{HELLO}`"
    admin(GATES)  # a #28 policy: no [evidence], so BUDDIE_REPOS is still taken
    assert [(s.path, s.origin) for s in evidence.repos({"cwd": str(real)})] == [(decoy, Origin.ENVIRONMENT)]
    assert stop(real, text, monkeypatch, capsys)[0] == 0
    admin(GATES + '[evidence]\nrepos = "event"\n')
    with policy.snapshot():
        assert [(s.path.resolve(), s.origin) for s in evidence.repos({"cwd": str(real)})] == \
            [(real.resolve(), Origin.EVENT)]
        assert "evidence.repos" in resolved.resolve({"cwd": str(real)}).refused
    code, err = stop(real, text, monkeypatch, capsys)
    assert code == 2 and "sha256 is now" in err


# --- VERBATIM_STORE / BUDDIE_STORES: which snapshots quotes are judged against ------------------------------------

def test_a_forged_snapshot_passes_from_the_session_store_and_not_with_stores_observed(admin, server, tmp_path,
                                                                                     monkeypatch, capsys):
    base, pages = server
    url = f"{base}/outage"
    pages["/outage"] = REAL                      # what the page says
    Store(tmp_path / "forged").add(url, FORGED)  # what a snapshot the agent wrote says
    monkeypatch.setenv("VERBATIM_STORE", str(tmp_path / "forged"))
    cwd = git_repo(tmp_path / "repo", b"x\n")
    text = f"The vendor wrote that “{QUOTE}” ([status]({url}))."
    admin(GATES)
    pred, stores, found, _ = judged(text, cwd)
    assert pred["quotes"][0]["verdict"] == "FOUND" and stores == [tmp_path / "forged"]
    assert found[0].evidence[0].provenance is Provenance.UNKNOWN  # not fetched now: origin unknown, never observed
    assert stop(cwd, text, monkeypatch, capsys)[0] == 0
    admin(GATES + '[evidence]\nstores = "observed"\n')
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "t"))
    (tmp_path / "t").mkdir()
    pred, stores, found, ctx = judged(text, cwd)
    assert pred["quotes"][0]["verdict"] == "NOT_FOUND" and stores == []
    # fetched now, but over plain http (the test's server): anyone on the path may have answered, so not observed
    assert found[0].evidence[0].provenance is Provenance.UNKNOWN
    assert "evidence.stores" in ctx.refused and list((tmp_path / "t").iterdir()) == []  # the check's store is gone
    code, err = stop(cwd, text, monkeypatch, capsys)
    assert code == 2 and "only against pages fetched in this check" in err
    pages["/outage"] = FORGED  # the page itself says it: fetched in this check, it holds
    pred, _, found, _ = judged(text, cwd)
    assert pred["quotes"][0]["verdict"] == "FOUND" and found[0].evidence[0].provenance is Provenance.UNKNOWN


def test_observed_with_no_fetch_is_a_gap_not_a_pass(admin, tmp_path, monkeypatch):
    Store(tmp_path / "forged").add("https://news.example.org/a", FORGED)
    monkeypatch.setenv("VERBATIM_STORE", str(tmp_path / "forged"))
    monkeypatch.setenv("BUDDIE_FETCH", "0")
    admin(GATES + '[evidence]\nstores = "observed"\n')
    pred, _, _, _ = judged(f"It said “{QUOTE}” ([s](https://news.example.org/a)).", tmp_path)
    assert pred["quotes"][0]["verdict"] == "SOURCE_UNAVAILABLE" and pred["outcome"] == "GAPS"


def test_a_snapshot_edited_after_it_was_taken_is_not_taken(admin, tmp_path, monkeypatch, capsys):
    store = Store(tmp_path / "s")
    entry = store.add("https://news.example.org/a", REAL)
    (store.snapshots / entry["sha256"]).write_bytes(FORGED)  # the bytes no longer match their hash
    monkeypatch.setenv("VERBATIM_STORE", str(tmp_path / "s"))
    monkeypatch.setenv("BUDDIE_FETCH", "0")
    text = f"It said “{QUOTE}” ([s](https://news.example.org/a))."
    with pytest.raises(ValueError, match="does not match its hash"):
        judged(text, tmp_path)
    code, err = stop(tmp_path, text, monkeypatch, capsys)  # the hook fails closed: the answer goes back
    assert code == 2 and "does not match its hash" in err


def test_each_store_says_who_named_it(tmp_path, monkeypatch):
    from buddie.stores import session_sources
    repo = tmp_path / "repo"
    for d in (tmp_path / "env", tmp_path / "cwd" / ".verbatim", repo / ".verbatim"):
        Store(d).add("https://e.example/", b"x")
    monkeypatch.setenv("BUDDIE_STORES", str(tmp_path / "env"))
    monkeypatch.delenv("VERBATIM_STORE", raising=False)
    got = [(s.path, s.origin) for s in session_sources(tmp_path / "cwd", [repo])]
    assert got == [(tmp_path / "env", Origin.ENVIRONMENT), (tmp_path / "cwd" / ".verbatim", Origin.EVENT),
                   (repo / ".verbatim", Origin.REPO)]


# --- BUDDIE_LOG / BUDDIE_SHARED_LOG: where the journal goes -------------------------------------------------------

def test_the_journal_cannot_be_moved_or_turned_off_with_journal_fixed(admin, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(logbook, "SHARED_ROOT", tmp_path / "no-shared-folder")
    monkeypatch.setenv("BUDDIE_LOG", "0")
    admin(GATES)
    with policy.snapshot():
        assert logbook.default_log() not in logbook.log_targets("s")  # legacy: BUDDIE_LOG=0 turns it off
    admin(GATES + '[evidence]\njournal = "fixed"\n')
    with policy.snapshot():
        assert logbook.log_targets("s") == [logbook.default_log()]  # BUDDIE_SHARED_LOG (conftest) set aside too
        assert "evidence.journal" in resolved.resolve({"cwd": str(tmp_path)}).refused
    stop(tmp_path, "Done.", monkeypatch, capsys)
    line = json.loads(logbook.default_log().read_text(encoding="utf-8").splitlines()[-1])
    assert line["policy"]["status"] == "active" and "evidence.journal" in line["policy"]["refused"]


# --- the hook's own fetches: proxy and CA settings from the environment -------------------------------------------

def test_a_proxy_from_the_environment_cannot_answer_for_a_page_with_collector_isolated(admin, server, tmp_path,
                                                                                      monkeypatch):
    base, pages = server
    pages["http://news.invalid/a"] = FORGED  # what the agent's proxy answers for a host that does not exist
    monkeypatch.setattr(urllib.request, "getproxies", urllib.request.getproxies_environment)  # conftest's undone
    monkeypatch.setenv("HTTP_PROXY", base)
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "agent-ca.pem"))
    admin(GATES)
    with policy.snapshot(), evidence.collector() as isolated:
        assert not isolated and not evidence.network_clean()
        assert Store(tmp_path / "a").fetch("http://news.invalid/a")["sha256"]  # legacy: the proxy's bytes
    admin(GATES + '[evidence]\ncollector = "isolated"\n')
    before = urllib.request._opener
    with policy.snapshot(), evidence.collector() as isolated:
        assert isolated and evidence.network_clean()
        assert Store(tmp_path / "b").fetch("http://news.invalid/a")["sha256"] is None  # direct: no such host
        # no proxy handler at all: not the default one, which reads the environment's and the system's proxies
        assert not any(isinstance(h, urllib.request.ProxyHandler) for h in urllib.request._opener.handlers)
        assert "evidence.collector" in resolved.resolve({"cwd": str(tmp_path)}).refused
    assert urllib.request._opener is before and evidence.network_clean() is False  # restored after the event
    assert not evidence._isolated()


def test_a_snapshot_fetched_through_a_proxy_is_not_observed(server, tmp_path, monkeypatch):
    base, pages = server
    pages["/a"] = FORGED
    text = f"It said “{QUOTE}” ([s]({base}/a))."
    monkeypatch.setenv("VERBATIM_STORE", str(tmp_path / "s"))
    original = Store.fetch

    def as_if_https(self, url, timeout=30):  # the test's server speaks http; count its bytes as an https fetch's
        entry = original(self, url, timeout)
        self.collected.add(entry["sha256"])
        return entry
    monkeypatch.setattr(Store, "fetch", as_if_https)
    _, _, found, _ = judged(text, tmp_path)
    assert found[0].evidence[0].provenance is Provenance.COLLECTOR_OBSERVED  # fetched now, nothing in between
    monkeypatch.setenv("VERBATIM_STORE", str(tmp_path / "s2"))
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "ca.pem"))  # the environment vouches for TLS now
    _, _, found, _ = judged(text, tmp_path)
    assert found[0].evidence[0].provenance is Provenance.UNKNOWN


# --- BUDDIE_GITHUB_API: who answers pr: and ci: -------------------------------------------------------------------

def test_an_api_from_the_environment_is_not_github_and_the_policy_can_fix_it(admin, monkeypatch):
    holds = {"anchor": "pr:o/r#1=open", "status": "HOLDS"}
    assert effects.api() == (effects.DEFAULT_API, "default")
    assert findings.anchor(holds).evidence[0].provenance is Provenance.COLLECTOR_OBSERVED
    monkeypatch.setattr(effects, "API", "https://agent.example")
    monkeypatch.setattr(effects, "ENV_API", "https://agent.example")
    assert effects.api() == ("https://agent.example", "environment")
    assert findings.anchor(holds).evidence[0].provenance is Provenance.CALLER_SUPPLIED
    admin(GATES + '[evidence]\ngithub_api = "https://ghe.example/api/v3/"\n')
    asked = []

    class Answer(io.BytesIO):
        def __init__(self, req):
            super().__init__(b"{}")
            self.url = req.full_url

        def geturl(self):
            return self.url

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: asked.append(req) or Answer(req))
    monkeypatch.setenv("BUDDIE_GITHUB_TOKEN", "t0ken")
    with policy.snapshot():
        assert effects.api() == ("https://ghe.example/api/v3", "policy")
        effects.github_get("/repos/o/r/pulls/1")
        assert findings.anchor(holds).evidence[0].provenance is Provenance.COLLECTOR_OBSERVED
        assert "evidence.github_api" in resolved.resolve({"cwd": "."}).refused
    assert asked[0].full_url == "https://ghe.example/api/v3/repos/o/r/pulls/1"  # the token goes there, not to
    assert asked[0].get_header("Authorization") == "Bearer t0ken"              # the environment's API


# --- one reading of the policy covers the evidence choices too ----------------------------------------------------

def test_the_evidence_choices_read_the_events_policy_once(admin, tmp_path, monkeypatch, capsys):
    admin(GATES + '[evidence]\nrepos = "event"\njournal = "fixed"\ncollector = "isolated"\n')
    reads, real = [], policy.load
    monkeypatch.setattr(policy, "load", lambda path=None: reads.append(1) or real(path))
    stop(tmp_path, f"Done. `⚓ data.txt#{HELLO}`", monkeypatch, capsys)
    assert len(reads) == 1 and policy._SNAPSHOT.get() is None
