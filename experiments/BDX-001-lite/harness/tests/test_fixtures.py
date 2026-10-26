"""Fixture consistency: the recordings are complete, consistent buddie documents, and match the frozen shell menu."""
import hashlib
import json
import re

import pytest

from bdx import fixtures, scenarios
from buddie import diagnostics, probes

ENVS = fixtures.environments()


def test_five_recorded_environments():
    assert ENVS == ["debian-nopython", "linux-arm64", "linux-container-2g", "linux-x64", "win-laptop"]


@pytest.mark.parametrize("name", ENVS)
def test_buddie_document_is_consistent_and_complete(name):
    doc = fixtures.env(name)["buddie"]
    assert diagnostics.problems(doc) == []
    assert set(doc["categories"]) == set(diagnostics.REGISTRY) | set(diagnostics.UNSUPPORTED)
    assert doc["request"]["tools"] == sorted(probes.TOOLS)
    assert doc["collector"]["buddie"] == "2.0.1"
    assert fixtures.env(name)["meta"]["buddie"]["exit"] == 0


@pytest.mark.parametrize("name", ENVS)
def test_shell_recording_covers_the_frozen_menu(name):
    rec = fixtures.env(name)["shell"]
    assert [r["command"] for r in rec["records"]] == fixtures.menu()
    assert rec["menu_sha256"] == hashlib.sha256(fixtures.MENU.read_bytes()).hexdigest()


@pytest.mark.parametrize("name", ENVS)
def test_recordings_carry_no_personal_paths(name):
    for f in ("buddie_full.json", "buddie_catalog.json", "shell.json", "meta.json"):
        text = (fixtures.RAW / name / f).read_text(encoding="utf-8")
        for m in re.finditer(r"[Cc]:(?:\\\\|\\|/)Users(?:\\\\|\\|/)([^\\/\"\s;]+)", text):
            assert m.group(1) in ("user", "Public", "Default"), (f, m.group(0))
        for m in re.finditer(r"/(?:home|Users)/([a-z0-9_.-]+)", text):
            assert m.group(1) in ("user", "runner", "linuxbrew"), (f, m.group(0))


def test_recordings_agree_with_each_other():
    """The two channels describe the same machine: OS family and architecture agree."""
    for name in ENVS:
        doc, shell = fixtures.env(name)["buddie"], {r["command"]: r for r in fixtures.env(name)["shell"]["records"]}
        os_obs = doc["categories"]["system.os"]["observations"]
        arch = os_obs["architecture"]["value"]
        if os_obs["family"]["value"] == "Windows":
            assert "Windows 11" in os_obs["name"]["value"]
            assert "64" in shell["Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, "
                                 "OSArchitecture, FreePhysicalMemory"]["stdout"]
        else:
            assert arch in shell["uname -a"]["stdout"]


@pytest.mark.parametrize("sid", list(scenarios.load()))
def test_every_scenario_binds_recorded_environments(sid):
    s = scenarios.load()[sid]
    for b in s.bindings.values():
        assert b["env"] in ENVS and b["mode"] in ("live", "cached")


def test_container_limit_is_genuine_in_both_channels():
    doc = fixtures.env("linux-container-2g")["buddie"]
    assert doc["categories"]["hardware.memory"]["observations"]["cgroup_limit_bytes"]["value"] == 2147483648
    shell = {r["command"]: r for r in fixtures.env("linux-container-2g")["shell"]["records"]}
    assert shell["cat /sys/fs/cgroup/memory.max"]["stdout"].strip() == "2147483648"
    assert shell["free -b"]["exit"] == 127


def test_meta_is_json_and_redaction_recorded():
    for name in ENVS:
        meta = json.loads((fixtures.RAW / name / "meta.json").read_text(encoding="utf-8"))
        assert meta["env_id"] == name
        assert meta["redaction"]["host_alias"]
