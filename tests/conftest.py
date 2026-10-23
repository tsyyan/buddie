import os

import pytest


@pytest.fixture(autouse=True)
def _no_shared_log(tmp_path, monkeypatch):
    """The hook also logs to /mnt/project-files when it exists; tests must not write there."""
    monkeypatch.setenv("BUDDIE_SHARED_LOG", str(tmp_path / "shared-log"))


@pytest.fixture(autouse=True)
def _project_final_mark(monkeypatch):
    """Most tests replay lab's own sessions, whose final answers carry `Следующий шаг:` (lab's buddie.toml); the
    plugin's default, the last message at Stop, has its own tests (test_buddie.py, NEXT №91)."""
    monkeypatch.setenv("BUDDIE_FINAL", "Следующий шаг:")


@pytest.fixture(autouse=True)
def _project_gates(monkeypatch, tmp_path):
    """The same: lab's buddie.toml blocks prose claims and returns a Stop for the summary and promises (0.8, NEXT
    №93), and as a configured project it keeps final and context at "block" (1.1: a project without buddie.toml has
    them off). The plugin's defaults have their own tests (test_config.py). The intro count never goes to ~/.cache."""
    monkeypatch.setenv("BUDDIE_GATES", "prose=block,summary=block,promises=block,final=block,context=block")
    monkeypatch.setenv("BUDDIE_INTRO", str(tmp_path / "intro.json"))


@pytest.fixture(autouse=True)
def _project_journal_text(monkeypatch):
    """The same: lab's buddie.toml keeps promise sentences and choice cards in the journal ([journal] text = true);
    the plugin's default, receipts only (NEXT №104), has its own tests (test_privacy.py)."""
    monkeypatch.setenv("BUDDIE_JOURNAL_TEXT", "1")


@pytest.fixture(autouse=True)
def _no_system_policy(monkeypatch, tmp_path):
    """The protected policy lives at a fixed system path (buddie/policy.py); a machine that has one must not change
    what these tests see. tests/test_policy.py points it at files of its own."""
    from buddie import policy
    monkeypatch.setattr(policy, "location", lambda: tmp_path / "no-system-policy" / "policy.toml")


@pytest.fixture(autouse=True)
def _no_home_journal(monkeypatch, tmp_path):
    """A protected policy with [evidence] journal = "fixed" writes the journal to its default place whatever
    BUDDIE_LOG says; in tests that place is a file of the test's own, not ~/.cache."""
    from buddie import logbook
    monkeypatch.setattr(logbook, "default_log", lambda: tmp_path / "default-journal" / "hook.jsonl")


@pytest.fixture(autouse=True)
def _no_ambient_network_settings(monkeypatch):
    """Whether a fetched snapshot or a pr:/ci: answer counts as observed depends on the environment's proxy and CA
    settings (buddie/evidence.py); a machine or CI runner that sets them must not change what these tests see."""
    import urllib.request

    from buddie import evidence
    for k in evidence.PROXY_VARS + evidence.CA_VARS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {})
    monkeypatch.setattr(urllib.request, "_opener", None)


# --- RH-1 (docs/release-hardening.md): the test process's own standard input handle ---------------------------------
# On Windows, a launcher (the Python install manager's command shim, `%LOCALAPPDATA%\Python\bin\pytest.exe`) was seen
# to close the stdin handle it gave pytest after pytest's capture had reused that slot: every test that then starts a
# program without stdin= fails with WinError 6 or 50. The suite checks the handle after collection and after each
# test and names the first moment it is unusable, so a recurrence reads as itself. BUDDIE_RH1_STRICT=1 fails the run.

_RH1 = {"first": None, "why": None}


def stdin_problem() -> str | None:
    """Why this process's standard input handle is unusable (Windows), or None."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetStdHandle.restype = wintypes.HANDLE
    k32.GetStdHandle.argtypes = [wintypes.DWORD]
    k32.GetHandleInformation.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    h = k32.GetStdHandle(wintypes.DWORD(-10 & 0xFFFFFFFF))
    flags = wintypes.DWORD()
    if h and not k32.GetHandleInformation(h, ctypes.byref(flags)):
        return f"standard input handle {h} is not a usable handle"
    return None


def _rh1_check(where: str) -> None:
    if _RH1["first"] is None and (why := stdin_problem()):
        _RH1["first"], _RH1["why"] = where, why


def pytest_collection_finish(session):
    _rh1_check("collection")


def pytest_runtest_logreport(report):
    if report.when == "teardown":
        _rh1_check(report.nodeid)


def pytest_terminal_summary(terminalreporter):
    if _RH1["first"]:
        terminalreporter.write_sep("!", "RH-1: the test process's standard input handle became unusable")
        terminalreporter.write_line(f"{_RH1['why']}, first seen after {_RH1['first']}. Tests that start a program "
                                    "without stdin= fail from there (WinError 6 or 50). Run the suite with "
                                    "`python -m pytest`, not a launcher shim (docs/release-hardening.md, RH-1).")


def pytest_sessionfinish(session, exitstatus):
    if _RH1["first"] and os.environ.get("BUDDIE_RH1_STRICT") == "1":
        session.exitstatus = 1
