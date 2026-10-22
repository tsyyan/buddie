"""PR #29 final review: COLLECTOR_OBSERVED cannot be claimed by what a caller hands in. A GitHub callback or a
snapshot store comes from the caller; whether buddie collected with it is decided by identity (buddie's own
github_get and the remote server's wrapper of it; buddie's own Store classes), never by an attribute or a set the
caller can fill."""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

import pytest

from buddie import effects, remote, verify
from buddie.core import Provenance
from buddie.stores import UnionStore
from buddie.verbatim.store import Store

PR_TEXT = "Merged. `⚓ pr:o/r#1=open`"
PR = {"state": "open", "head": {"sha": "abc"}, "base": {"repo": {"private": False, "full_name": "o/r"}}}
REPO = {"private": False, "full_name": "o/r"}
QUOTE = "the outage began at 14:59 UTC and was resolved within two hours"
PAGE = f"<html><body><p>{'Background paragraph about the service. ' * 40}</p><p>They said {QUOTE}.</p></body></html>"


def provenance(github, **kw):
    receipt, found, _ = verify.assess(PR_TEXT, repos=[], fetch=False, mandate=False, github=github, now="t", **kw)
    return receipt, found[0]


class Answer(io.BytesIO):
    def __init__(self, url, data):
        super().__init__(json.dumps(data).encode())
        self.url = url

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def github_api(monkeypatch):
    """GitHub's real API URL, answered here: the default API, so only the callback decides the provenance."""
    answers = {"/repos/o/r/pulls/1": PR, "/repos/o/r": REPO}

    def urlopen(req, timeout):
        path = req.full_url.removeprefix(effects.DEFAULT_API)
        if path not in answers:
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        return Answer(req.full_url, answers[path])
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert effects.api() == (effects.DEFAULT_API, "default")
    return answers


# --- GitHub callbacks ---------------------------------------------------------------------------------------------

def test_a_fabricated_callback_with_the_old_marker_is_not_collected(github_api):
    def forged(path):
        return PR  # made up by the caller, never asked of GitHub
    forged.buddie_collector = True
    assert provenance(forged)[1].evidence[0].provenance is Provenance.CALLER_SUPPLIED


def test_an_ordinary_callback_is_caller_supplied(github_api):
    assert provenance({"/repos/o/r/pulls/1": PR}.get)[1].evidence[0].provenance is Provenance.CALLER_SUPPLIED


def test_buddies_own_github_get_is_collected(github_api):
    assert provenance(effects.github_get)[1].evidence[0].provenance is Provenance.COLLECTOR_OBSERVED


def test_the_remote_servers_wrapper_of_github_get_is_collected_and_of_anything_else_is_not(github_api):
    assert provenance(remote.public_github(effects.github_get))[1].evidence[0].provenance \
        is Provenance.COLLECTOR_OBSERVED

    def forged(path):
        return PR if path.endswith("/pulls/1") else REPO
    forged.buddie_collector = True
    assert provenance(remote.public_github(forged))[1].evidence[0].provenance is Provenance.CALLER_SUPPLIED
    # wrapping the wrapper, or calling it from a function of one's own, does not pass the identity on
    wrapped = remote.public_github(effects.github_get)
    assert provenance(lambda path: wrapped(path))[1].evidence[0].provenance is Provenance.CALLER_SUPPLIED


def test_the_same_answer_gives_the_same_receipt_whatever_the_provenance(github_api):
    collected, own = provenance(effects.github_get)
    handed, other = provenance({"/repos/o/r/pulls/1": PR}.get)
    assert collected == handed and own.fact == other.fact  # receipt-v0 and the verdict do not depend on it
    assert own.evidence[0].provenance is not other.evidence[0].provenance


def test_a_network_failure_on_the_collected_path_is_a_gap_with_no_evidence(monkeypatch):
    def down(req, timeout):
        raise urllib.error.URLError("no route")
    monkeypatch.setattr(urllib.request, "urlopen", down)
    receipt, finding = provenance(effects.github_get)
    assert receipt["predicate"]["outcome"] == "GAPS" and finding.fact.value == "undetermined"
    assert finding.evidence == ()


def test_a_cross_origin_redirect_on_the_collected_path_is_a_gap(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: Answer("https://elsewhere.example/x", PR))
    receipt, finding = provenance(effects.github_get)
    assert receipt["predicate"]["outcome"] == "GAPS" and finding.evidence == ()


# --- snapshot stores ----------------------------------------------------------------------------------------------

def quote_provenance(store):
    _, found, _ = verify.assess(f"They said “{QUOTE}” ([s](https://news.example.org/a)).", store=store,
                                fetch=False, mandate=False)
    assert found[0].fact.value == "supported"
    return found[0].evidence[0].provenance


def test_a_store_whose_collected_set_the_caller_filled_is_not_observed(tmp_path):
    store = Store(tmp_path / "s")
    entry = store.add("https://news.example.org/a", PAGE.encode())
    store.collected.add(entry["sha256"])  # claimed by the caller before the check
    assert quote_provenance(store) is Provenance.UNKNOWN


def _serves(monkeypatch, body: bytes):
    """urlopen answering every https URL with `body`, as the site would."""
    def urlopen(req, timeout):
        return type("R", (io.BytesIO,), {"status": 200, "headers": {"Content-Type": "text/html; charset=utf-8"},
                                         "geturl": lambda self: req.full_url, "__enter__": lambda self: self,
                                         "__exit__": lambda self, *a: False})(body)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)


def test_a_store_subclass_cannot_make_its_own_bytes_collected(tmp_path, monkeypatch):
    _serves(monkeypatch, b"<html><body><p>The page says nothing of the kind.</p></body></html>")

    class Forging(Store):
        def add(self, url, data, **meta):  # fetch() records whatever this returns, as the bytes it received
            return super().add(url, PAGE.encode(), **meta)
    _, found, _ = verify.assess(f"They said “{QUOTE}” ([s](https://news.example.org/a)).",
                                store=Forging(tmp_path / "s"), mandate=False)
    assert found[0].fact.value == "supported"  # the forged bytes are what was judged...
    assert found[0].evidence[0].provenance is Provenance.UNKNOWN  # ...and they are not taken for collected ones


def test_buddies_own_store_classes_still_collect(tmp_path, monkeypatch):
    _serves(monkeypatch, PAGE.encode())
    for store in (Store(tmp_path / "a"), UnionStore(tmp_path / "b", [])):
        _, found, _ = verify.assess(f"They said “{QUOTE}” ([s](https://news.example.org/a)).", store=store,
                                    mandate=False)
        assert found[0].fact.value == "supported" and found[0].evidence[0].provenance is Provenance.COLLECTOR_OBSERVED
