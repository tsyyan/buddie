"""PR #28 review: the Windows ACL check, the launcher without Python, and one policy reading per hook event."""
from __future__ import annotations

import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from buddie import hook, policy, winacl
from buddie.winacl import ACCESS_ALLOWED, INHERIT_ONLY, Node, judge

ROOT = Path(__file__).resolve().parents[1]
ME = "S-1-5-21-1-2-3-1001"
ADMINS, SYSTEM, USERS, EVERYONE = "S-1-5-32-544", "S-1-5-18", "S-1-5-32-545", "S-1-1-0"
READ = 0x120089


def file_(owner=ADMINS, aces=((ACCESS_ALLOWED, 0, 0x1F01FF, ADMINS), (ACCESS_ALLOWED, 0, READ, USERS)), granted=None):
    return Node("C:\\ProgramData\\buddie\\policy.toml", False, owner, aces, granted)


def dir_(owner=SYSTEM, aces=((ACCESS_ALLOWED, 0, 0x1F01FF, SYSTEM), (ACCESS_ALLOWED, 0, READ | 0x2 | 0x4, USERS)),
         granted=None):
    return Node("C:\\ProgramData\\buddie", True, owner, aces, granted)


# --- the decision, on any OS --------------------------------------------------------------------------------------

def test_an_administrators_file_in_a_system_directory_is_protected():
    # Users may add files to the directory (ProgramData's default), which does not let them replace this one
    assert judge([file_(), dir_()], ME) is None


@pytest.mark.parametrize("node, why", [
    (file_(owner=ME), "owned by this user"),
    (file_(owner="S-1-5-21-9-9-9-500"), "not by SYSTEM, Administrators or TrustedInstaller"),
    (file_(owner=None), "owner cannot be read"),
    (file_(aces=None), "no DACL"),
    (file_(aces=((ACCESS_ALLOWED, 0, 0x2, USERS),)), "Users may change or replace it"),
    (file_(aces=((ACCESS_ALLOWED, 0, 0x40000, EVERYONE),)), "Everyone"),  # WRITE_DAC
    (file_(aces=((ACCESS_ALLOWED, 0, 0x10000, ME),)), "this user"),  # DELETE
    (file_(aces=((ACCESS_ALLOWED, 0, 0x40000000, "S-1-5-11"),)), "Authenticated Users"),  # GENERIC_WRITE
    (file_(aces=((ACCESS_ALLOWED, 0, 0x100, "S-1-3-4"),)), "OWNER RIGHTS"),  # FILE_WRITE_ATTRIBUTES
    (file_(granted=0x2 | READ), "this user's token is granted"),
])
def test_the_file_is_not_protected(node, why):
    got = judge([node, dir_()], ME)
    assert got is not None and why in got


@pytest.mark.parametrize("directory, why", [
    (dir_(aces=((ACCESS_ALLOWED, 0, 0x40, USERS),)), "Users may change or replace"),  # FILE_DELETE_CHILD
    (dir_(aces=((ACCESS_ALLOWED, 0, 0x10000, EVERYONE),)), "Everyone"),  # DELETE: rename the directory away
    (dir_(owner=ME), "owned by this user"),
    (dir_(granted=0x40000), "token is granted"),
])
def test_a_directory_above_it_is_not_protected(directory, why):
    got = judge([file_(), directory, dir_()], ME)
    assert got is not None and why in got


def test_inherit_only_aces_do_not_apply_and_deny_aces_do_not_help():
    inherit_only = (ACCESS_ALLOWED, INHERIT_ONLY, 0x1F01FF, "S-1-3-0")  # CREATOR OWNER, for children only
    assert judge([file_(), dir_(aces=dir_().aces + (inherit_only,))], ME) is None
    deny_then_allow = ((1, 0, 0x2, USERS), (ACCESS_ALLOWED, 0, 0x2, USERS))  # a deny is not subtracted
    assert judge([file_(aces=deny_then_allow), dir_()], ME) is not None


@pytest.mark.parametrize("kind", [5, 9, 11, 4, 0x7F])  # allowed object, callback, callback object; compound; unknown
def test_an_allow_ace_this_check_does_not_read_is_not_protection(kind):
    # a conditional or object ACE may grant this user anything; what is not read is not judged harmless
    got = judge([file_(aces=file_().aces + ((kind, 0, 0x2, ""),)), dir_()], ME)
    assert got is not None and f"type {kind}" in got
    assert judge([file_(), dir_(aces=dir_().aces + ((kind, INHERIT_ONLY, 0x2, ""),))], ME) is None  # children only


@pytest.mark.parametrize("kind", [1, 6, 10, 12])  # denied, denied object, denied callback, denied callback object
def test_deny_aces_of_any_type_are_not_a_problem(kind):
    assert judge([file_(aces=file_().aces + ((kind, 0, 0x2, ""),)), dir_()], ME) is None


def test_a_check_that_raises_makes_the_policy_invalid(tmp_path, monkeypatch):
    place = tmp_path / "policy.toml"
    place.write_text("version = 1\n", encoding="utf-8")
    monkeypatch.setattr(policy, "protection_problem", lambda p: (_ for _ in ()).throw(AttributeError("no API")))
    got = policy.load(place)
    assert got.status is policy.Status.INVALID and "cannot establish protection" in got.error


# --- the real descriptors, on Windows -----------------------------------------------------------------------------

windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows security descriptors")


@windows
def test_a_file_this_user_made_is_not_protected(tmp_path):
    f = tmp_path / "policy.toml"
    f.write_text("version = 1\n", encoding="utf-8")
    assert "owned by this user" in winacl.problem(str(f))
    assert "owned by this user" in policy.protection_problem(f)


@windows
def test_a_system_file_is_protected_for_a_user_who_is_not_elevated():
    if winacl.elevated():
        pytest.skip("an elevated token may write anything; the check is meant for the agent's ordinary token")
    hosts = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"
    assert winacl.problem(str(hosts)) is None


# --- the launcher without Python ----------------------------------------------------------------------------------

SH = shutil.which("sh")
launcher = pytest.mark.skipif(SH is None, reason="no sh")


def _launch(event: dict, env: dict | None = None, *, compact: bool = False) -> subprocess.CompletedProcess:
    body = json.dumps(event, separators=(",", ":") if compact else None).encode()
    return subprocess.run([SH, (ROOT / "hooks" / "run.sh").as_posix(), "hook"], input=body,
                          capture_output=True, env=env, timeout=60)


@launcher
@pytest.mark.parametrize("compact", [False, True])
def test_no_python_is_not_a_pass_and_does_not_loop(tmp_path, compact):
    no_python = {"PATH": str(tmp_path / "empty"), "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}
    first = _launch({"hook_event_name": "Stop", "stop_hook_active": False, "session_id": "s"}, no_python, compact=compact)
    assert first.returncode == 2 and b"nothing was checked" in first.stderr
    again = _launch({"hook_event_name": "Stop", "stop_hook_active": True, "session_id": "s"}, no_python, compact=compact)
    assert again.returncode == 0 and "not checked" in json.loads(again.stdout)["systemMessage"]
    for other in ({"hook_event_name": "SessionStart"}, {"hook_event_name": "PreToolUse", "tool_name": "SendMessage"},
                  {"hook_event_name": "PostToolUse", "tool_name": "Read"}):
        got = _launch(other, no_python, compact=compact)
        assert got.returncode == 0 and b"nothing was checked" in got.stderr and got.stdout == b""


@launcher
def test_the_launcher_runs_python_isolated(tmp_path):
    """PYTHONPATH can come from a project's settings; with -I it loads nothing into buddie."""
    inject = tmp_path / "inject"
    inject.mkdir()
    marker = tmp_path / "loaded"
    (inject / "sitecustomize.py").write_text(f"open(r'{marker}', 'w').write('x')\n", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(inject), "BUDDIE_LOG": str(tmp_path / "h.jsonl"), "BUDDIE_SHARED_LOG": "0",
           "BUDDIE_STATE": str(tmp_path / "p"), "BUDDIE_FETCH": "0", "BUDDIE_GITHUB": "0", "BUDDIE_LESSONS": "0"}
    got = _launch({"hook_event_name": "SessionStart", "session_id": "s", "cwd": str(tmp_path)}, env)
    assert got.returncode == 0 and not marker.exists()


@launcher
@pytest.mark.parametrize("chosen", ["python3", "python", "py"])
@pytest.mark.parametrize("backslashes", [False, True])
def test_launcher_fallback_preserves_event_arguments_and_isolation(tmp_path, chosen, backslashes):
    """Store stubs/old interpreters fail probes; only a working interpreter receives stdin."""
    package = tmp_path / "plugin with spaces"
    (package / "hooks").mkdir(parents=True)
    shutil.copyfile(ROOT / "hooks" / "run.sh", package / "hooks" / "run.sh")
    (package / "run.py").write_text(
        "import json, sys\n"
        "print(json.dumps({'event': json.load(sys.stdin), 'args': sys.argv[1:], 'isolated': sys.flags.isolated}))\n",
        encoding="utf-8")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for name in ("python3", "python", "py"):
        stub = bin_ / name
        body = "#!/bin/sh\n"
        if name != chosen:
            body += "exit 1\n"
        else:
            if name == "py":
                body += '[ "$1" = "-3" ] || exit 98\nshift\n'
            body += f'exec {shlex.quote(Path(sys.executable).as_posix())} "$@"\n'
        stub.write_text(body, encoding="utf-8", newline="\n")
        stub.chmod(0o755)
    # Git Bash still needs its auxiliary tools; only our controlled Python choices are on PATH.
    if sys.platform == "win32":
        shell_tools = Path(SH).parent
        if not (shell_tools / "tr.exe").is_file():  # Git/bin/sh.exe vs Git/usr/bin/sh.exe
            shell_tools = shell_tools.parent / "usr" / "bin"
        tool_paths = [str(shell_tools)]
    else:
        tool_paths = ["/usr/bin", "/bin"]  # macOS keeps tr/dirname in /usr/bin
    env = {**os.environ, "PATH": os.pathsep.join([str(bin_), *tool_paths])}
    script = str(package / "hooks" / "run.sh") if backslashes else (package / "hooks" / "run.sh").as_posix()
    event = {"hook_event_name": "SessionStart", "session_id": "stdin-survives-probes"}
    got = subprocess.run([SH, script, "hook", "one argument with spaces"], input=json.dumps(event).encode(),
                         capture_output=True, env=env, timeout=30)
    assert got.returncode == 0, got.stderr
    assert json.loads(got.stdout) == {"event": event, "args": ["hook", "one argument with spaces"], "isolated": 1}


# --- one policy reading per event ---------------------------------------------------------------------------------

def test_one_policy_reading_per_hook_event(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "data.txt").write_bytes(b"hello\n")
    (repo / "buddie.toml").write_text("[journal]\ntext = true\n", encoding="utf-8")
    place = tmp_path / "system" / "policy.toml"
    place.parent.mkdir()
    place.write_text('version = 1\njournal_text = "project"\n[gates]\nquotes = "block"\n', encoding="utf-8")
    monkeypatch.setattr(policy, "location", lambda: place)
    monkeypatch.setattr(policy, "protection_problem", lambda p: None)
    for k, v in (("BUDDIE_FETCH", "0"), ("BUDDIE_GITHUB", "0"), ("BUDDIE_LOG", str(tmp_path / "h.jsonl")),
                 ("BUDDIE_STATE", "0"), ("BUDDIE_REPOS", str(repo)), ("BUDDIE_LESSONS", "0")):
        monkeypatch.setenv(k, v)
    reads, real = [], policy.load

    def counted(path=None):
        reads.append(1)
        return real(path)
    monkeypatch.setattr(policy, "load", counted)
    event = {"hook_event_name": "Stop", "session_id": "s", "cwd": str(repo),
             "last_assistant_message": "Done, and I will run №3 after lab#5 is merged."}
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(event).encode("utf-8"))))
    hook.main()
    capsys.readouterr()
    # the gate, the return state (BUDDIE_STATE=0 asks the policy), the journal's words (promises) and the free
    # command all asked; the file was read once
    assert len(reads) == 1
    assert policy._SNAPSHOT.get() is None  # nothing left behind after the event
