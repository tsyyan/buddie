"""Directory audit: fake secrets, loopback recording servers, no external services."""
import io
import json
import traceback
import urllib.error
import urllib.request

import pytest

from buddie import effects, policy
from test_provenance_boundaries import two_hosts, _api  # noqa: F401 (shared loopback fixture)

PATH = "/repos/o/r/pulls/1"
SECRET = "directory_fake_secret_12345"


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    for key in ("BUDDIE_GITHUB_TOKEN", "CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN"):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize("name", ["BUDDIE_GITHUB_TOKEN", "CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN"])
def test_environment_endpoint_receives_no_token(two_hosts, monkeypatch, name):
    (base, routes, seen), _ = two_hosts
    _api(monkeypatch, base)
    monkeypatch.setenv(name, SECRET)
    routes[PATH] = "{}"
    assert effects.github_get(PATH) == {}
    assert seen == [(PATH, None)]


def test_cross_origin_redirect_is_refused_before_contact(two_hosts, monkeypatch):
    (base, routes, _), (other, other_routes, seen) = two_hosts
    _api(monkeypatch, base)
    routes[PATH] = ("redirect", other + "/sink")
    other_routes["/sink"] = "{}"
    with pytest.raises(effects.GitHubUnavailable, match="another host"):
        effects.github_get(PATH)
    assert seen == []


class Answer(io.BytesIO):
    def __init__(self, url):
        super().__init__(b"{}")
        self.url = url

    def geturl(self):
        return self.url


def test_plugin_configuration_wins_over_environment_token(monkeypatch):
    monkeypatch.setenv("BUDDIE_GITHUB_TOKEN", "different_fake_secret")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN", SECRET)
    asked = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda r, timeout: asked.append(r) or Answer(r.full_url))
    effects.github_get(PATH)
    assert asked[0].get_header("Authorization") == "Bearer " + SECRET


@pytest.mark.parametrize("base", [
    "http://enterprise.example/api/v3", "https://", "https://user:password@enterprise.example/api/v3",
    "https://enterprise.example:bad/api/v3", "https://enterprise.example/api/v3?key=secret",
    "https://enterprise.example/api/v3#fragment", "https://enterprise.example/api/../v3",
    "https://enterprise.example/api/%2e%2e/v3", "https://enterprise.example\\@evil.example/api/v3",
])
def test_protected_enterprise_endpoint_is_validated(tmp_path, monkeypatch, base):
    place = tmp_path / "policy.toml"
    place.write_text('version = 1\n[evidence]\ngithub_api = ' + json.dumps(base) + '\n', encoding="utf-8")
    monkeypatch.setattr(policy, "location", lambda: place)
    monkeypatch.setattr(policy, "protection_problem", lambda p: None)
    assert policy.load().error


def test_network_error_does_not_expose_token_even_in_traceback(monkeypatch):
    monkeypatch.setenv("BUDDIE_GITHUB_TOKEN", SECRET)
    def fail(req, timeout):
        raise urllib.error.URLError("proxy rejected Bearer " + SECRET)
    monkeypatch.setattr(urllib.request, "urlopen", fail)
    try:
        effects.github_get(PATH)
    except effects.GitHubUnavailable:
        rendered = traceback.format_exc()
    else:
        pytest.fail("network failure was accepted")
    assert SECRET not in rendered


def test_transport_secret_is_absent_from_receipt_hook_output_and_journal(tmp_path, monkeypatch):
    from buddie import hook, verify
    def fail(req, timeout):
        raise urllib.error.URLError("proxy echoed Bearer " + SECRET)
    monkeypatch.setattr(urllib.request, "urlopen", fail)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN", SECRET)
    monkeypatch.setenv("BUDDIE_LOG", str(tmp_path / "journal.jsonl"))
    monkeypatch.setenv("BUDDIE_GITHUB", "1")
    monkeypatch.setenv("BUDDIE_FETCH", "0")
    monkeypatch.setenv("BUDDIE_STATE", "0")
    monkeypatch.setenv("BUDDIE_GATES", "")
    text = "State: `⚓ pr:o/r#1=open`."
    receipt = verify.verify(text, repos=[], fetch=False, github=effects.github_get, mandate=False)
    assert receipt["predicate"]["outcome"] == "GAPS"
    err, out = io.StringIO(), io.StringIO()
    hook.run({"hook_event_name": "Stop", "cwd": str(tmp_path), "last_assistant_message": text}, err, out)
    journal = (tmp_path / "journal.jsonl").read_text(encoding="utf-8")
    assert journal.strip()
    assert SECRET not in json.dumps(receipt) + err.getvalue() + out.getvalue() + journal


@pytest.mark.parametrize("suffix", ["\nbad", "\rbad", "\x1f", "\u2603"])
@pytest.mark.parametrize("name", ["BUDDIE_GITHUB_TOKEN", "CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN"])
def test_invalid_token_is_refused_without_exposure(two_hosts, monkeypatch, suffix, name):
    (base, routes, seen), _ = two_hosts
    # Isolate header handling over loopback; destination validation has its own tests above.
    monkeypatch.setattr(effects, "api", lambda: (base, "policy"))
    monkeypatch.setattr(policy, "valid_github_api", lambda value: value == base)
    monkeypatch.setenv(name, SECRET + suffix)
    routes[PATH] = "{}"
    try:
        effects.github_get(PATH)
    except effects.GitHubUnavailable:
        rendered = traceback.format_exc()
    else:
        pytest.fail("invalid credential was accepted")
    assert SECRET not in rendered
    assert seen == []


def test_unrelated_credentials_are_not_sent(two_hosts, monkeypatch):
    (base, routes, seen), _ = two_hosts
    _api(monkeypatch, base)
    for name in ("GITHUB_TOKEN", "GH_TOKEN", "AWS_SECRET_ACCESS_KEY", "BUDDIE_HTTP_TOKEN"):
        monkeypatch.setenv(name, SECRET)
    routes[PATH] = "{}"
    effects.github_get(PATH)
    assert seen == [(PATH, None)]


def test_invalid_policy_makes_no_github_request(tmp_path, monkeypatch):
    place = tmp_path / "policy.toml"
    place.write_text('version = 1\n[evidence]\ngithub_api = "https://"\n', encoding="utf-8")
    monkeypatch.setattr(policy, "location", lambda: place)
    monkeypatch.setattr(policy, "protection_problem", lambda p: None)
    monkeypatch.setenv("BUDDIE_GITHUB_TOKEN", SECRET)
    asked = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda r, timeout: asked.append(r) or Answer(r.full_url))
    with pytest.raises(effects.GitHubUnavailable, match="policy"):
        effects.github_get(PATH)
    assert asked == []


@pytest.mark.parametrize("name", ["BUDDIE_GITHUB_TOKEN", "CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN"])
def test_enterprise_policy_receives_only_selected_token(tmp_path, monkeypatch, name):
    place = tmp_path / "policy.toml"
    place.write_text('version = 1\n[evidence]\ngithub_api = "https://enterprise.example:8443/api/v3"\n', encoding="utf-8")
    monkeypatch.setattr(policy, "location", lambda: place)
    monkeypatch.setattr(policy, "protection_problem", lambda p: None)
    monkeypatch.setattr(effects, "API", "https://untrusted.example")
    monkeypatch.setenv(name, SECRET)
    asked = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda r, timeout: asked.append(r) or Answer(r.full_url))
    effects.github_get(PATH)
    assert asked[0].full_url == "https://enterprise.example:8443/api/v3/repos/o/r/pulls/1"
    assert asked[0].get_header("Authorization") == "Bearer " + SECRET
