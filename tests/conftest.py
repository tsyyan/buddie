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
