"""Offline unit tests for the release payload budget gate."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("release_size_gate", ROOT / "scripts" / "release_size_gate.py")
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def records(wheel=260_000, sdist=270_000, mcpb=340_000, plugin=905_000):
    return [
        {"kind": "wheel", "size": wheel},
        {"kind": "sdist", "size": sdist},
        {"kind": "mcpb", "size": mcpb},
        {"kind": "plugin", "size": plugin},
        {"kind": "plugin-manifest", "size": 2048},
    ]


def test_ordinary_compact_distribution_passes():
    assert gate.check(records()) == []


def test_oversized_distribution_fails_closed():
    errors = gate.check(records(plugin=2 * gate.MIB + 1))
    assert any("plugin:" in x and "exceeds" in x for x in errors)


def test_missing_or_duplicate_archive_fails():
    assert "missing wheel artifact" in gate.check(records()[1:])
    assert "duplicate wheel artifact" in gate.check(records() + records()[:1])


def test_malformed_size_fails():
    assert any("invalid size" in e for e in gate.check(records(wheel=-1)))
    assert any("invalid size" in e for e in gate.check(records(wheel=True)))


def write_candidate(root, **sizes):
    files = []
    for item in records(**sizes):
        name = f"{item['kind']}.bin"
        (root / name).write_bytes(b"\0" * item["size"])
        files.append({**item, "path": name})
    (root / "release-manifest.json").write_text(json.dumps({"files": files}), encoding="utf-8")
    return files


def test_cli_read_only_success_and_oversize(tmp_path, capsys):
    write_candidate(tmp_path)
    assert gate.main([str(tmp_path)]) == 0
    assert "PASS" in capsys.readouterr().out
    write_candidate(tmp_path, mcpb=3 * gate.MIB)
    assert gate.main([str(tmp_path)]) == 1
    assert "exceeds" in capsys.readouterr().err


def test_cli_size_is_read_from_the_files_not_the_manifest(tmp_path, capsys):
    files = write_candidate(tmp_path)
    (tmp_path / "plugin.bin").write_bytes(b"\0" * (2 * gate.MIB + 1))  # manifest still claims 905000
    assert gate.main([str(tmp_path)]) == 1
    assert "differs from file size" in capsys.readouterr().err
    (tmp_path / "plugin.bin").unlink()
    assert gate.main([str(tmp_path)]) == 1
    files[0]["path"] = "../wheel.bin"
    (tmp_path / "release-manifest.json").write_text(json.dumps({"files": files}), encoding="utf-8")
    assert gate.main([str(tmp_path)]) == 1
    assert "unsafe" in capsys.readouterr().err


def test_cli_missing_manifest_fails(tmp_path):
    assert gate.main([str(tmp_path)]) == 1
