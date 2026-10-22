"""PR #29 security review: where buddie's GitHub token may go, and when a finding's evidence counts as observed by
the collector (core.Provenance.COLLECTOR_OBSERVED). Each test is an attack or an edge that the first version of #29
got wrong, shown against a local server standing in for GitHub, a page or a proxy."""
from __future__ import annotations

import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from buddie import effects, evidence, findings, policy, verify
from buddie.core import Provenance
from buddie.verbatim.store import Store

QUOTE = "the outage began at 14:59 UTC and was resolved within two hours"
PAGE = f"<html><body><p>{'Background paragraph about the service. ' * 40}</p><p>They said {QUOTE}.</p></body></html>"


class Recorder(BaseHTTPRequestHandler):
    """Answers `routes[path]`: bytes (200), ("redirect", url) or ("private", body: 404 without a token); records
    each request's Authorization header."""
    routes: dict = {}
    seen: list = []

    def do_GET(self):  # noqa: N802 - http.server's name
        self.seen.append((self.path, self.headers.get("Authorization")))
        got = self.routes.get(self.path)
        if isinstance(got, tuple) and got[0] == "private":
            got = got[1] if self.headers.get("Authorization") else None
        if isinstance(got, tuple):
            self.send_response(302)
            self.send_header("Location", got[1])
            self.end_headers()
            return
        if got is None:
            self.send_response(404)
            self.end_headers()
            return
        body = got if isinstance(got, bytes) else got.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8" if b"<html" in body else "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _serve():
    handler = type("H", (Recorder,), {"routes": {}, "seen": []})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, handler


@pytest.fixture
def two_hosts():
    """Two servers on different origins: (base, routes, seen) each."""
    a, ha = _serve()
    b, hb = _serve()
    yield (f"http://127.0.0.1:{a.server_port}", ha.routes, ha.seen), (f"http://localhost:{b.server_port}", hb.routes,
                                                                      hb.seen)
    for s in (a, b):
        s.shutdown()
        s.server_close()


def _api(monkeypatch, base):
    monkeypatch.setattr(effects, "API", base)
    monkeypatch.setattr(effects, "ENV_API", base)


# --- 1. the token -------------------------------------------------------------------------------------------------

def test_a_redirect_to_another_origin_gets_neither_the_token_nor_belief(two_hosts, monkeypatch):
    (api, routes, _), (other, other_routes, other_seen) = two_hosts
    _api(monkeypatch, api)
    monkeypatch.setenv("BUDDIE_GITHUB_TOKEN", "t0ken")
    routes["/repos/o/r/pulls/1"] = ("redirect", f"{other}/steal")
    other_routes["/steal"] = '{"state": "open"}'
    with pytest.raises(effects.GitHubUnavailable, match="another host"):  # its answer is not taken
        effects.github_get("/repos/o/r/pulls/1")
    assert other_seen == [("/steal", None)]  # urllib followed the redirect, without the token
    routes["/repos/o/r/pulls/2"] = ("redirect", f"{other}/missing")  # a 404 there is not "no such PR" either
    with pytest.raises(effects.GitHubUnavailable, match="another host"):
        effects.github_get("/repos/o/r/pulls/2")


def test_a_redirect_on_the_same_origin_is_followed_with_the_token(two_hosts, monkeypatch):
    (api, routes, seen), _ = two_hosts
    _api(monkeypatch, api)
    monkeypatch.setenv("BUDDIE_GITHUB_TOKEN", "t0ken")
    routes["/repos/o/r/pulls/1"] = ("redirect", f"{api}/repositories/7/pulls/1")  # a renamed private repo
    routes["/repositories/7/pulls/1"] = ("private", '{"state": "open"}')
    assert effects.github_get("/repos/o/r/pulls/1") == {"state": "open"}
    assert seen == [("/repos/o/r/pulls/1", "Bearer t0ken"), ("/repositories/7/pulls/1", None),  # urllib's hop
                    ("/repositories/7/pulls/1", "Bearer t0ken")]  # asked again there, on the API's origin


def test_github_goes_through_the_installed_opener(two_hosts, monkeypatch):
    """The remote server installs a guarded opener for every fetch of its process (remote.py), the hook an isolated
    one: buddie's GitHub requests must not build one of their own around them."""
    (api, routes, _), _ = two_hosts
    _api(monkeypatch, api)
    routes["/repos/o/r/pulls/1"] = '{"state": "open"}'
    used = []
    installed = urllib.request.build_opener()
    original = installed.open
    monkeypatch.setattr(installed, "open", lambda *a, **k: used.append(1) or original(*a, **k))
    monkeypatch.setattr(urllib.request, "_opener", installed)
    assert effects.github_get("/repos/o/r/pulls/1") == {"state": "open"} and used


def test_the_plugins_token_does_not_go_to_an_api_the_environment_named(two_hosts, monkeypatch):
    """CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN is the person's setting, handed to buddie only; BUDDIE_GITHUB_API is the
    hook's environment, the agent's to set. Sending the one to the other gave the agent the token."""
    (api, routes, seen), _ = two_hosts
    _api(monkeypatch, api)
    monkeypatch.delenv("BUDDIE_GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN", "pers0nal")
    routes["/repos/o/r/pulls/1"] = '{"state": "open"}'
    effects.github_get("/repos/o/r/pulls/1")
    assert seen == [("/repos/o/r/pulls/1", None)]
    monkeypatch.setenv("BUDDIE_GITHUB_TOKEN", "fr0m-env")  # the environment's own token may go to its own API
    effects.github_get("/repos/o/r/pulls/1")
    assert seen[-1] == ("/repos/o/r/pulls/1", "Bearer fr0m-env")


@pytest.mark.parametrize("env_api", ["https://api.github.com/", "https://API.github.com", "https://api.github.com.",
                                     "https://api.github.com@agent.example", "https://api.github.com:443"])
def test_no_spelling_of_the_default_api_from_the_environment_counts_as_github(monkeypatch, env_api):
    _api(monkeypatch, env_api)
    assert effects.api()[1] == "environment"
    assert findings.github_provenance() is Provenance.CALLER_SUPPLIED


# --- 2. what counts as observed -----------------------------------------------------------------------------------

def test_a_github_function_the_caller_hands_in_is_not_github(monkeypatch):
    fake = {"/repos/o/r/pulls/1": {"state": "open", "head": {"sha": "abc"}}}
    _, found, _ = verify.assess("Merged. `⚓ pr:o/r#1=open`", repos=[], fetch=False, mandate=False,
                                github=fake.get)
    assert found[0].fact.value == "supported" and found[0].evidence[0].provenance is Provenance.CALLER_SUPPLIED


def test_bytes_the_caller_put_in_the_store_are_not_observed(tmp_path):
    store = Store(tmp_path / "s")
    store.add("https://news.example.org/a", PAGE.encode())  # written by whoever handed the store in, not fetched
    _, found, _ = verify.assess(f"They said “{QUOTE}” ([s](https://news.example.org/a)).", store=store,
                                fetch=False, mandate=False)
    assert found[0].fact.value == "supported" and found[0].evidence[0].provenance is Provenance.UNKNOWN


def test_a_page_fetched_over_plain_http_is_not_observed(two_hosts, tmp_path):
    (base, routes, _), _ = two_hosts
    routes["/a"] = PAGE
    _, found, _ = verify.assess(f"They said “{QUOTE}” ([s]({base}/a)).", store=tmp_path / "s", mandate=False)
    # anyone on the path may have answered: fetched now, but not observed from the site
    assert found[0].fact.value == "supported" and found[0].evidence[0].provenance is Provenance.UNKNOWN


def test_a_fetch_through_a_proxy_is_not_observed_when_a_collector_starts_meanwhile(two_hosts, tmp_path, monkeypatch):
    """network_clean() asked once, after the check, saw another thread's isolated collector and took a fetch that
    went through the environment's proxy for an observed one."""
    (proxy, routes, _), _ = two_hosts
    place = tmp_path / "system" / "policy.toml"
    place.parent.mkdir()
    place.write_text('version = 1\n[evidence]\ncollector = "isolated"\n', encoding="utf-8")
    monkeypatch.setattr(policy, "location", lambda: place)
    monkeypatch.setattr(policy, "protection_problem", lambda p: None)
    monkeypatch.setattr(urllib.request, "getproxies", urllib.request.getproxies_environment)
    monkeypatch.setenv("HTTP_PROXY", proxy)
    entered, leave = threading.Event(), threading.Event()

    def other_event():
        with evidence.collector():
            entered.set()
            leave.wait(30)
    routes["http://news.invalid/a"] = PAGE
    original = Store.fetch

    def fetch_then_isolate(self, url, timeout=30):
        entry = original(self, url, timeout)  # through the proxy, before the other collector starts
        self.collected.add(entry["sha256"])  # as an https fetch would be: only the network's state can tell now
        threading.Thread(target=other_event, daemon=True).start()
        entered.wait(30)
        return entry
    monkeypatch.setattr(Store, "fetch", fetch_then_isolate)
    # this thread's event has no policy (its own snapshot); the other thread reads the isolating one
    token = policy._SNAPSHOT.set(policy.Loaded(policy.Status.ABSENT, None, place))
    try:
        _, found, _ = verify.assess(f"They said “{QUOTE}” ([s](http://news.invalid/a)).", store=tmp_path / "s",
                                    mandate=False)
    finally:
        leave.set()
        policy._SNAPSHOT.reset(token)
    assert found[0].evidence[0].provenance is not Provenance.COLLECTOR_OBSERVED


# --- 3. the collector's process-wide state ------------------------------------------------------------------------

@pytest.fixture
def isolated_policy(tmp_path, monkeypatch):
    place = tmp_path / "system" / "policy.toml"
    place.parent.mkdir()
    place.write_text('version = 1\n[evidence]\ncollector = "isolated"\n', encoding="utf-8")
    monkeypatch.setattr(policy, "location", lambda: place)
    monkeypatch.setattr(policy, "protection_problem", lambda p: None)


def test_nested_collectors_keep_the_outer_one_until_it_ends(isolated_policy):
    before = urllib.request._opener
    with evidence.collector():
        outer = urllib.request._opener
        with evidence.collector():
            pass
        assert urllib.request._opener is outer and evidence.network_clean()  # still the outer event's network
    assert urllib.request._opener is before and not evidence._isolated()


def test_overlapping_collectors_in_two_threads_leave_nothing_behind(isolated_policy):
    before = urllib.request._opener
    a_in, b_in, a_out = threading.Event(), threading.Event(), threading.Event()

    def a():
        with evidence.collector():
            a_in.set()
            b_in.wait(30)
        a_out.set()

    def b():
        a_in.wait(30)
        with evidence.collector():
            b_in.set()
            a_out.wait(30)  # A ends while B is still inside
            assert evidence._isolated()
    threads = [threading.Thread(target=f) for f in (a, b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert urllib.request._opener is before and not evidence._isolated()


def test_a_collector_that_fails_inside_restores_everything(isolated_policy, monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", "agent-ca.pem")
    before = urllib.request._opener
    with pytest.raises(RuntimeError):
        with evidence.collector():
            raise RuntimeError("the check failed")
    assert urllib.request._opener is before and not evidence._isolated()
    assert evidence.os.environ["SSL_CERT_FILE"] == "agent-ca.pem"


# --- 4. provenance is a label, never a verdict --------------------------------------------------------------------

def test_provenance_never_changes_a_verdict_and_a_failure_stays_a_gap():
    text = "Merged. `⚓ pr:o/r#1=open`"

    def answer(path):
        return {"state": "open", "head": {"sha": "abc"}}

    def marked(path):  # a callback that claims to be buddie's collector: the claim counts for nothing
        return answer(path)
    marked.buddie_collector = True

    def down(path):
        raise effects.GitHubUnavailable("GitHub unreachable: no route")
    handed, _ = verify.assess(text, repos=[], fetch=False, mandate=False, github=answer, now="t")[:2]
    claimed, found = verify.assess(text, repos=[], fetch=False, mandate=False, github=marked, now="t")[:2]
    assert handed == claimed  # the same receipt-v0 (test_provenance_unforgeable.py: with github_get too)
    assert found[0].evidence[0].provenance is Provenance.CALLER_SUPPLIED
    receipt, found, _ = verify.assess(text, repos=[], fetch=False, mandate=False, github=down, now="t")
    assert receipt["predicate"]["outcome"] == "GAPS" and found[0].fact.value == "undetermined"
    assert found[0].evidence == ()  # nothing was observed, so nothing is claimed
