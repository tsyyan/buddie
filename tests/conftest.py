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
    №93); the plugin's defaults have their own tests (test_config.py). The intro count never goes to ~/.cache."""
    monkeypatch.setenv("BUDDIE_GATES", "prose=block,summary=block,promises=block")
    monkeypatch.setenv("BUDDIE_INTRO", str(tmp_path / "intro.json"))


@pytest.fixture(autouse=True)
def _project_journal_text(monkeypatch):
    """The same: lab's buddie.toml keeps promise sentences and choice cards in the journal ([journal] text = true);
    the plugin's default, receipts only (NEXT №104), has its own tests (test_privacy.py)."""
    monkeypatch.setenv("BUDDIE_JOURNAL_TEXT", "1")
