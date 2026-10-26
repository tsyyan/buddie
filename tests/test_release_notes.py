import copy
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import release_notes as rn

RECORD = {"schema": "buddie-public-release-v1", "version": "2.0.2", "date": "2026-10-26", "summary": "Public runtime release.", "changes": ["Bind notes to candidates."], "upgrade": "Install buddie==2.0.2.", "permissions": "Optional GitHub credentials.", "security": "Local deterministic checks.", "limitations": "No claim of catalog display."}

def test_deterministic_public_outputs(tmp_path):
    p=tmp_path / "release.json"
    p.write_text(json.dumps(RECORD), encoding="utf-8")
    record=rn.load_release(p, "2.0.2")
    assert rn.render_markdown(record) == rn.render_markdown(record)
    for channel in ("pypi", "claude", "desktop", "codex"):
        text=rn.render_package_readme(record, channel)
        assert "2.0.2" in text and "Permissions" in text
    assert "mcp-name: io.github.tsyyan/buddie" in rn.render_package_readme(record, "pypi")

@pytest.mark.parametrize("field,value", [("version","2.0.1"),("date","2026-02-30"),("summary"," "),("changes",[]),("extra","x"),("schema",1),("security",["x"])])
def test_invalid_records_fail_closed(tmp_path, field, value):
    record=copy.deepcopy(RECORD); record[field]=value
    p=tmp_path / "release.json"; p.write_text(json.dumps(record),encoding="utf-8")
    with pytest.raises(ValueError): rn.load_release(p,"2.0.2")

def test_duplicate_keys_rejected(tmp_path):
    p=tmp_path / "release.json"
    p.write_text(json.dumps(RECORD)[:-1]+',"version":"2.0.2"}',encoding="utf-8")
    with pytest.raises(ValueError,match="duplicate"): rn.load_release(p,"2.0.2")

def test_candidate_payloads_and_registry_digest(tmp_path):
    server=json.loads((Path(__file__).resolve().parents[1] / "server.json").read_text())
    rn.write_candidate_metadata(RECORD,tmp_path,server)
    payload=json.loads((tmp_path / "server.json").read_text())
    import hashlib
    meta=payload["_meta"]["io.modelcontextprotocol.registry/publisher-provided"]["io.github.tsyyan/buddie"]
    assert meta["sha256"] == hashlib.sha256((tmp_path / "release-notes.md").read_bytes()).hexdigest()
    assert meta["version"] == "2.0.2"
    assert "v2.0.2" in meta["url"]


def test_registry_rejects_foreign_same_version_server():
    server={"version":"2.0.2", "name":"foreign/server", "repository":{"url":"https://example.org"}, "packages":[{"version":"2.0.2"}]}
    with pytest.raises(ValueError,match="identity"): rn.registry_payload(server, RECORD)
