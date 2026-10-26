import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_release_channels as channels


def listing(notes=None, version="2.0.2"):
    return {"listing": {"id": "buddie-mcp", "source": {"kind": "pypi", "value": "buddie"},
                        "delivery": "direct", "hosting": "local"},
            "releases": [{"version": version, "notes": [] if notes is None else notes}]}


def test_empty_notes_is_missing_not_success():
    assert channels.observe(listing(), "2.0.2", "Expected notes")["notes"] == "missing"


def test_exact_visible_text_and_version_are_observed():
    result = channels.observe(listing(["Expected notes"]), "2.0.2", "Expected notes")
    assert result["version"] == "observed" and result["notes"] == "observed"


@pytest.mark.parametrize("data", [None, {}, [], {"listing": {}}, {"challenge": True}])
def test_unknown_shapes_are_unverified(data):
    assert channels.observe(data, "2.0.2", "Expected notes")["notes"] == "unknown"


def test_stale_or_foreign_listing_is_not_delivery():
    assert channels.observe(listing(version="2.0.1"), "2.0.2", "Expected notes")["version"] == "missing"
    data = listing(["Expected notes"])
    data["listing"]["source"]["kind"] = "git"
    assert channels.observe(data, "2.0.2", "Expected notes")["notes"] == "unknown"
    assert channels.observe(listing(["Other text"]), "2.0.2", "Expected notes")["notes"] == "different"


def test_blank_expected_notes_never_confirm_delivery():
    assert channels.observe(listing([" "]), "2.0.2", " \n")["notes"] == "unknown"


def test_saved_snapshot_is_not_current_delivery(tmp_path, monkeypatch, capsys):
    import json
    notes, snapshot = tmp_path / "notes.md", tmp_path / "listing.json"
    notes.write_text("Expected notes", encoding="utf-8")
    snapshot.write_text(json.dumps(listing(["Expected notes"])), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["check", "--version", "2.0.2", "--notes", str(notes), "--snapshot", str(snapshot)])
    assert channels.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["freshness"] == "unverified" and "observed_at" not in result
