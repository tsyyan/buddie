"""PR #28: the protected policy. What the agent can write (buddie.toml, the hook's environment, buddie's state) does
not weaken what the administrator's policy file requires; a policy that cannot be used does not loosen anything."""
from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from buddie import config, hook, policy, resolved, verify
from buddie.config import Source
from buddie.verbatim.store import Store

REAL_LOCATION = policy.location  # before conftest points it at a missing file
URL = "https://news.example.org/outage"
PAGE = ("<p>" + "Background paragraph about the service. " * 40 + "</p><p>The company said the outage began at 14:59 "
        "UTC and was resolved within two hours.</p>").encode()
HELLO = hashlib.sha256(b"hello\n").hexdigest()[:12]
HOLDS = f"`⚓ data.txt#{HELLO}`"
GOOD_Q = f"The vendor wrote that “the outage began at 14:59 UTC and was resolved within two hours” ([r]({URL}))."
BAD = GOOD_Q.replace("14:59", "14:58") + " " + HOLDS
GOOD = "Done. " + HOLDS
PRE = "\nbuddie: some of this may be unchecked."
POLICY = 'version = 1\n[gates]\nquotes = "block"\nanchors = "block"\nfinal = "block"\n'


def with_top(top: str) -> str:
    """POLICY with top-level keys, which TOML wants before the first table."""
    return POLICY.replace("version = 1\n", "version = 1\n" + top, 1)


@pytest.fixture
def world(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "data.txt").write_bytes(b"hello\n")
    Store(tmp_path / "store").add(URL, PAGE, content_type="text/html")
    for k in ("BUDDIE_GATES", "BUDDIE_FINAL", "BUDDIE_TRANSCRIPT", "CLAUDE_PLUGIN_OPTION_READ_TRANSCRIPT",
              "BUDDIE_JOURNAL_TEXT", "BUDDIE_FREE", "BUDDIE_NUMBERS"):
        monkeypatch.delenv(k, raising=False)
    for k, v in (("BUDDIE_FETCH", "0"), ("BUDDIE_GITHUB", "0"), ("BUDDIE_LOG", str(tmp_path / "hook.jsonl")),
                 ("BUDDIE_STATE", str(tmp_path / "pending")), ("BUDDIE_REPOS", str(repo)), ("BUDDIE_INTRO", str(tmp_path / "intro.json")),
                 ("VERBATIM_STORE", str(tmp_path / "store")), ("BUDDIE_LESSONS", "0"), ("BUDDIE_PROMISES", "0")):
        monkeypatch.setenv(k, v)
    place = tmp_path / "system" / "policy.toml"
    monkeypatch.setattr(policy, "location", lambda: place)

    def install(text: str | bytes | None, protected: bool = True):
        """The administrator's file. `protected` stands for root or admin ownership, which a test cannot create;
        protection_problem itself is tested on real files below."""
        if text is None:
            place.unlink(missing_ok=True)
        else:
            place.parent.mkdir(parents=True, exist_ok=True)
            place.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        monkeypatch.setattr(policy, "protection_problem", (lambda p: None) if protected else REAL_PROTECTION)

    return repo, install, tmp_path


REAL_PROTECTION = policy.protection_problem


def run(repo: Path, text: str, monkeypatch, capsys, **extra) -> tuple[int, str, str]:
    event = {"hook_event_name": "Stop", "session_id": "s", "cwd": str(repo), "last_assistant_message": text, **extra}
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(event).encode("utf-8"))))
    code = hook.main()
    got = capsys.readouterr()
    return code, got.err, got.out


def last(tmp: Path) -> dict:
    return json.loads((tmp / "hook.jsonl").read_text(encoding="utf-8").splitlines()[-1])


# --- 1, 9: a trusted policy applies; no policy changes nothing ----------------------------------------------------

def test_no_policy_is_the_legacy_behaviour(world, monkeypatch, capsys):
    repo, install, tmp = world
    (repo / "buddie.toml").write_text('[gates]\nquotes = "off"\n', encoding="utf-8")
    ctx = resolved.resolve({"cwd": str(repo)})
    assert ctx.policy.status is policy.Status.ABSENT and ctx.refused == () and ctx.level["quotes"] == "off"
    assert run(repo, BAD, monkeypatch, capsys)[0] == 0  # legacy: the project may lower a gate
    assert "policy" not in last(tmp)


def test_a_protected_policy_sets_floors(world):
    repo, install, _ = world
    install(POLICY + 'numbers = "warn"\n')
    (repo / "buddie.toml").write_text('[gates]\nquotes = "off"\nanchors = "warn"\nprose = "block"\n', encoding="utf-8")
    ctx = resolved.resolve({"cwd": str(repo)})
    assert ctx.policy.status is policy.Status.ACTIVE
    assert ctx.levels["quotes"] == config.Setting("block", Source.PROTECTED)
    assert ctx.levels["anchors"] == config.Setting("block", Source.PROTECTED)
    assert ctx.levels["prose"] == config.Setting("block", Source.REPO)  # stricter than nothing: kept
    assert ctx.levels["numbers"].value == "warn"  # the default meets the floor
    assert set(ctx.refused) == {"gates.quotes", "gates.anchors"}


# --- 2, 3: the agent's sources cannot lower or disable a check ----------------------------------------------------

def test_the_repos_buddie_toml_cannot_lower_a_floor(world, monkeypatch, capsys):
    repo, install, tmp = world
    install(POLICY)
    (repo / "buddie.toml").write_text('[gates]\nquotes = "off"\n', encoding="utf-8")
    code, err, _ = run(repo, BAD, monkeypatch, capsys)
    assert code == 2 and "14:58" in err
    assert last(tmp)["policy"] == {"status": "active", "refused": ["gates.quotes"]}


def test_the_hooks_environment_cannot_lower_a_floor(world, monkeypatch, capsys):
    """BUDDIE_GATES reaches the hook from the project's .claude/settings.json `env`, which the agent can write."""
    repo, install, _ = world
    install(POLICY)
    monkeypatch.setenv("BUDDIE_GATES", "quotes=off,anchors=off,final=off")
    assert run(repo, BAD, monkeypatch, capsys)[0] == 2
    assert run(repo, f"Done. `⚓ data.txt#{'0' * 12}`", monkeypatch, capsys)[0] == 2


def test_the_intro_mode_cannot_turn_returns_into_warnings(world, monkeypatch, capsys):
    repo, install, _ = world
    (repo / "buddie.toml").write_text("[intro]\nfinals = 100\n", encoding="utf-8")
    assert run(repo, BAD, monkeypatch, capsys)[0] == 0  # legacy: the intro only warns
    install(POLICY)
    assert run(repo, BAD, monkeypatch, capsys)[0] == 2
    install(POLICY + "[project]\nintro = true\n")  # the policy's own word lets it apply
    assert run(repo, BAD, monkeypatch, capsys)[0] == 0


def test_an_empty_final_mark_cannot_turn_the_final_rule_off(world, monkeypatch, capsys):
    repo, install, _ = world
    monkeypatch.setenv("BUDDIE_FINAL", "")  # an empty mark: no answer is final, the rule is off
    assert run(repo, "We checked 73 of 84 files.", monkeypatch, capsys)[0] == 0
    install(POLICY)
    code, err, _ = run(repo, "We checked 73 of 84 files.", monkeypatch, capsys)
    assert code == 2 and "final answer has no anchor" in err


def test_turning_return_tracking_off_does_not_make_a_pre_written_line_count(world, monkeypatch, capsys):
    """BUDDIE_STATE=0 makes every `buddie:` line count, before a return as after; under a policy it is ignored."""
    repo, install, _ = world
    monkeypatch.setenv("BUDDIE_STATE", "0")
    assert run(repo, BAD + PRE, monkeypatch, capsys)[0] == 0  # legacy
    install(POLICY)
    monkeypatch.setattr(resolved, "state_root", lambda limits: str(world[2] / "kept-state") if limits else None)
    code, err, _ = run(repo, BAD + PRE, monkeypatch, capsys)
    assert code == 2 and "written before buddie checked it" in err
    assert run(repo, BAD + PRE, monkeypatch, capsys)[0] == 0  # after the return: a disclosure, as always


# --- 4: disclosure cannot be suppressed, and the policy can make it unavailable -----------------------------------

def test_a_policy_without_disclosure_lets_only_a_fix_out(world, monkeypatch, capsys):
    repo, install, _ = world
    install(with_top("disclosure = false\n"))
    assert run(repo, BAD, monkeypatch, capsys)[0] == 2
    assert run(repo, BAD + PRE, monkeypatch, capsys)[0] == 2  # after the return, still no
    assert run(repo, GOOD_Q + " " + HOLDS, monkeypatch, capsys)[0] == 0  # fixed


def test_an_error_return_is_not_released_by_a_line_when_disclosure_is_off(world, monkeypatch, capsys):
    repo, install, _ = world
    install(with_top("disclosure = false\n"))
    monkeypatch.setattr(verify, "assess", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert run(repo, GOOD, monkeypatch, capsys)[0] == 2
    assert run(repo, GOOD + PRE, monkeypatch, capsys)[0] == 2
    code, _, out = run(repo, GOOD, monkeypatch, capsys, stop_hook_active=True)  # never a loop, the person is told
    assert code == 0 and "not checked" in json.loads(out)["systemMessage"]


# --- 5: a policy that is missing, unprotected, broken or of another version ---------------------------------------

@pytest.mark.parametrize("text, why", [
    ("this is [ not toml", "not valid TOML"), (b"version = 1\n# \xff\n", "not UTF-8"),
    ("version = 2\n", "unsupported version"), ("[gates]\nquotes = \"block\"\n", "unsupported version None"),
    ('version = 1\nallow_everything = true\n', "unknown keys"), ('version = 1\n[gates]\nquotes = "never"\n', "[gates]"),
    ('version = 1\n[project]\nintro = "yes"\n', "[project]"), ('version = 1\ntranscript = "maybe"\n', "transcript"),
    ('version = 1\nfinal_mark = "("\n', "final_mark")])
def test_a_policy_that_cannot_be_used_is_strict_and_said(world, monkeypatch, capsys, text, why):
    repo, install, tmp = world
    install(text)
    loaded = policy.load()
    assert loaded.status is policy.Status.INVALID and why in loaded.error
    (repo / "buddie.toml").write_text('[gates]\nquotes = "off"\n[intro]\nfinals = 9\n', encoding="utf-8")
    ctx = resolved.resolve({"cwd": str(repo)})
    assert all(ctx.level[c] == "block" for c in policy.VERIFYING) and not ctx.intro_allowed
    code, err, _ = run(repo, GOOD, monkeypatch, capsys)  # nothing false in it, but the policy is broken
    assert code == 2 and "protected policy cannot be used" in err
    assert last(tmp)["policy"]["status"] == "invalid"
    assert run(repo, GOOD + PRE, monkeypatch, capsys)[0] == 0  # after the return, the reader is told


def test_a_pre_written_line_does_not_pass_a_broken_policy(world, monkeypatch, capsys):
    repo, install, _ = world
    install("version = 7\n")
    code, err, _ = run(repo, GOOD + PRE, monkeypatch, capsys)
    assert code == 2 and "written before buddie checked it" in err


def test_a_writable_policy_is_not_protected(world, monkeypatch, capsys):
    """The real check, on a real file this user owns and can write: not the administrator's."""
    repo, install, _ = world
    install(POLICY + "[project]\nintro = true\n", protected=False)
    loaded = policy.load()
    assert loaded.status is policy.Status.INVALID and loaded.error.startswith("not protected")
    assert run(repo, GOOD, monkeypatch, capsys)[0] == 2


@pytest.mark.skipif(sys.platform != "win32", reason="Windows file attributes")
def test_a_read_only_attribute_is_not_protection(world):
    repo, install, _ = world
    install(POLICY, protected=False)
    place = policy.location()
    os.chmod(place, stat.S_IREAD)  # FILE_ATTRIBUTE_READONLY: its owner can clear it
    try:
        # write-open is now refused, but the file is still this user's: its owner can clear the attribute
        assert "is owned by this user" in policy.protection_problem(place)
        assert policy.load().status is policy.Status.INVALID
    finally:
        os.chmod(place, stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX ownership")
def test_a_file_of_this_user_is_not_protected_even_read_only(world):
    repo, install, _ = world
    install(POLICY, protected=False)
    os.chmod(policy.location(), 0o444)
    assert "not owned by root" in policy.protection_problem(policy.location())


def test_the_location_is_not_moved_by_the_environment(monkeypatch, tmp_path):
    first = REAL_LOCATION()
    for k in ("ProgramData", "PROGRAMDATA", "ALLUSERSPROFILE", "BUDDIE_POLICY", "HOME", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(k, str(tmp_path))
    assert REAL_LOCATION() == first and str(tmp_path) not in str(first)


# --- 6: precedence and conflicts ----------------------------------------------------------------------------------

@pytest.mark.parametrize("rule, env, option, repo, want", [
    ("required", "0", None, False, ("on", Source.PROTECTED)), ("required", None, "false", None, ("on", Source.PROTECTED)),
    ("forbidden", "1", "true", True, ("off", Source.PROTECTED)), ("project", "0", None, True, ("off", Source.USER)),
    ("project", None, None, False, ("off", Source.REPO))])
def test_transcript_reading_under_a_policy(world, monkeypatch, rule, env, option, repo, want):
    repo_dir, install, _ = world
    install(f'version = 1\ntranscript = "{rule}"\n')
    for name, value in (("BUDDIE_TRANSCRIPT", env), ("CLAUDE_PLUGIN_OPTION_READ_TRANSCRIPT", option)):
        monkeypatch.delenv(name, raising=False) if value is None else monkeypatch.setenv(name, value)
    if repo is not None:
        (repo_dir / "buddie.toml").write_text(f"[transcript]\nread = {str(repo).lower()}\n", encoding="utf-8")
    got = resolved.resolve({"cwd": str(repo_dir)}).transcript
    assert (got.value, got.source) == want


def test_a_stricter_lower_source_keeps_its_level(world, monkeypatch):
    repo, install, _ = world
    install('version = 1\n[gates]\nprose = "warn"\nnumbers = "off"\n')
    monkeypatch.setenv("BUDDIE_GATES", "prose=block,numbers=block")
    ctx = resolved.resolve({"cwd": str(repo)})
    assert ctx.levels["prose"] == config.Setting("block", Source.USER)
    assert ctx.levels["numbers"] == config.Setting("block", Source.USER) and ctx.refused == ()


# --- 7: no new collection or execution from below -----------------------------------------------------------------

def test_the_environment_cannot_name_a_command_to_run(world, monkeypatch, tmp_path):
    from buddie import promises
    ran = tmp_path / "ran"
    monkeypatch.setenv("BUDDIE_FREE", f'"{sys.executable}" -c "open(r\'{ran}\', \'w\')"')
    repo, install, _ = world
    install(POLICY)
    assert promises.free_now(2, {"repo": str(repo)}, {}) is None and not ran.exists()
    # the policy's own command runs (its answer: row 2 taken), and still not the environment's
    script = tmp_path / "free.py"
    script.write_text("import json\nprint(json.dumps({'free': False, 'reasons': ['taken by the policy']}))\n",
                      encoding="utf-8")
    install(with_top(f"free_command = '\"{sys.executable}\" \"{script}\" {{n}}'\n"))
    assert promises.free_now(2, {"repo": str(repo)}, {}) == {"free": False, "reasons": ["taken by the policy"]}
    assert not ran.exists()


def test_the_project_cannot_turn_journal_words_on(world, monkeypatch):
    repo, install, _ = world
    monkeypatch.setenv("BUDDIE_JOURNAL_TEXT", "1")
    assert config.journal_text({"journal": {"text": True}}) is True  # legacy
    install(POLICY)
    assert config.journal_text({"journal": {"text": True}}) is False
    assert resolved.resolve({"cwd": str(repo)}).journal_text is False
    install(with_top('journal_text = "project"\n'))
    assert config.journal_text({"journal": {"text": True}}) is True


def test_a_policy_can_forbid_the_network_and_nothing_below_reopens_it(world, monkeypatch, capsys):
    repo, install, _ = world
    install(with_top('network = "forbidden"\n'))
    monkeypatch.setenv("BUDDIE_FETCH", "1")
    monkeypatch.setenv("BUDDIE_GITHUB", "1")
    seen = {}
    real = verify.assess

    def spy(text, **kw):
        seen.update(fetch=kw["fetch"], github=kw["github"])
        return real(text, **kw)
    monkeypatch.setattr(verify, "assess", spy)
    run(repo, GOOD, monkeypatch, capsys)
    assert seen == {"fetch": False, "github": None}


# --- 8: an update or a removal applies at the next event ----------------------------------------------------------

def test_update_and_rollback(world, monkeypatch, capsys):
    repo, install, _ = world
    (repo / "buddie.toml").write_text('[gates]\nquotes = "off"\n', encoding="utf-8")
    install(POLICY)
    assert run(repo, BAD, monkeypatch, capsys)[0] == 2
    install('version = 1\n[gates]\nanchors = "block"\n')  # the administrator lowers the quotes floor
    assert run(repo, BAD, monkeypatch, capsys)[0] == 0
    install(None)  # and removes the policy: the legacy behaviour
    assert run(repo, BAD, monkeypatch, capsys)[0] == 0 and resolved.resolve({"cwd": str(repo)}).refused == ()


# --- 10: receipts and the rest are as before ----------------------------------------------------------------------

def test_receipts_do_not_change_under_a_policy(world):
    repo, install, tmp = world
    kw = dict(store=str(tmp / "store"), fetch=False, repos=[repo], now="2026-10-22T00:00:00Z")
    before = verify.verify(BAD, **kw)
    install(with_top('network = "forbidden"\ndisclosure = false\n'))
    assert verify.verify(BAD, **kw) == before


def test_the_policy_command(world, capsys):
    from buddie import cli
    repo, install, _ = world
    assert cli.main(["policy", "check"]) == 0 and "absent" in capsys.readouterr().out
    install(POLICY)
    (repo / "buddie.toml").write_text('[gates]\nquotes = "off"\n', encoding="utf-8")
    assert cli.main(["policy", "show", "--repo", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "status: active" in out and "quotes=block*" in out and "gates.quotes" in out
    install("version = 9\n")
    assert cli.main(["policy", "check"]) == 1
    capsys.readouterr()
    assert cli.main(["policy", "template"]) == 0
    template = capsys.readouterr().out
    assert template == policy.TEMPLATE
    assert policy.parse(__import__("tomllib").loads(template)).floors["quotes"] == "block"
