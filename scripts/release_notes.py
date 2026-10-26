"""Strict public release records and deterministic UTF-8/LF channel adapters."""
from __future__ import annotations
import argparse
import datetime
import hashlib
import json
import re
from pathlib import Path

SCHEMA = "buddie-public-release-v1"
FIELDS = {"schema", "version", "date", "summary", "changes", "upgrade", "permissions", "security", "limitations"}
CHANNELS = ("pypi", "claude", "desktop", "codex")
META = "io.modelcontextprotocol.registry/publisher-provided"
NAMESPACE = "io.github.tsyyan/buddie"

def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out: raise ValueError(f"duplicate field {key}")
        out[key] = value
    return out

def parse_release(text: str, version: str) -> dict:
    record = json.loads(text, object_pairs_hook=_pairs)
    validate(record, version)
    return record

def load_release(path: Path, version: str) -> dict:
    return parse_release(path.read_text(encoding="utf-8"), version)

def validate(record: dict, version: str) -> None:
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise ValueError("release fields must match the public schema exactly")
    if record["schema"] != SCHEMA: raise ValueError("unsupported public release schema")
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", version) or record["version"] != version:
        raise ValueError("release version mismatch or invalid version")
    if not isinstance(record["date"], str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", record["date"]):
        raise ValueError("invalid release date")
    datetime.date.fromisoformat(record["date"])
    def text(value):
        return isinstance(value, str) and bool(value.strip()) and not any(ord(c)<32 and c != "\n" for c in value)
    for field in FIELDS - {"changes"}:
        if not text(record[field]): raise ValueError(f"empty or invalid {field}")
    if not isinstance(record["changes"], list) or not record["changes"] or not all(text(x) for x in record["changes"]):
        raise ValueError("changes must be a nonempty list of public text")

def render_markdown(record: dict) -> str:
    validate(record, record.get("version", ""))
    parts = [f"# Buddie {record['version']}", record["date"], record["summary"], "## Changes", "\n".join("- " + x for x in record["changes"])]
    for field in ("upgrade", "permissions", "security", "limitations"):
        parts += ["## " + field.title(), record[field]]
    return "\n\n".join(parts) + "\n"

def canonical_url(record: dict) -> str:
    return f"https://github.com/tsyyan/buddie/releases/download/v{record['version']}/release-notes.md"

def render_package_readme(record: dict, channel: str) -> str:
    if channel not in CHANNELS: raise ValueError("unknown release channel")
    intro = "Buddie checks agent reports against primary evidence with local deterministic checks."
    marker = "<!-- mcp-name: io.github.tsyyan/buddie -->\n\n" if channel == "pypi" else ""
    install = f"Install: `pip install buddie=={record['version']}`."
    if channel == "codex":
        install = ("Install this Codex plugin profile through the supported manual plugin installation flow. "
                   "Review and explicitly trust the bundled MCP launcher and optional hooks before enabling them; "
                   "installing the Python package alone does not install the Codex profile.")
    return (marker + intro + "\n\n" + install + "\n\n"
            + f"[Repository](https://github.com/tsyyan/buddie) | [Privacy](https://github.com/tsyyan/buddie/blob/v{record['version']}/PRIVACY.md) | [Release notes]({canonical_url(record)})\n\n"
            + render_markdown(record))

def registry_payload(server: dict, record: dict) -> dict:
    import copy
    result = copy.deepcopy(server)
    if result.get("version") != record["version"] or not result.get("packages") or any(p.get("version") != record["version"] for p in result["packages"]):
        raise ValueError("Registry payload version mismatch")
    if result.get("name") != NAMESPACE or result.get("repository", {}).get("url") != "https://github.com/tsyyan/buddie" or len(result["packages"]) != 1:
        raise ValueError("Registry payload identity mismatch")
    package = result["packages"][0]
    if (package.get("identifier"), package.get("registryType"), package.get("registryBaseUrl"), package.get("transport")) != ("buddie", "pypi", "https://pypi.org", {"type": "stdio"}):
        raise ValueError("Registry package identity mismatch")
    result.setdefault("_meta", {}).setdefault(META, {})[NAMESPACE] = {
        "url": canonical_url(record), "version": record["version"],
        "sha256": hashlib.sha256(render_markdown(record).encode("utf-8")).hexdigest()}
    return result

def write_candidate_metadata(record: dict, out: Path, server: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    payloads = {"release-notes.md": render_markdown(record), "release-notes.json": json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                "server.json": json.dumps(registry_payload(server, record), indent=2, ensure_ascii=False) + "\n"}
    payloads.update({channel + "-readme.md": render_package_readme(record, channel) for channel in CHANNELS})
    for name, text in payloads.items(): (out / name).write_text(text, encoding="utf-8", newline="\n")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    record = load_release(args.root / "releases" / (args.version + ".json"), args.version)
    write_candidate_metadata(record, args.out, json.loads((args.root / "server.json").read_text(encoding="utf-8")))

if __name__ == "__main__": main()
