import pytest


@pytest.fixture(autouse=True)
def _no_shared_log(tmp_path, monkeypatch):
    """The hook also logs to /mnt/project-files when it exists; tests must not write there."""
    monkeypatch.setenv("BUDDIE_SHARED_LOG", str(tmp_path / "shared-log"))
