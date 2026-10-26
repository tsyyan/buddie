"""Read-only observation of MCPRush release metadata. Never publishes or writes account data.

Unknown JSON shapes, access challenges and unavailable metadata are explicitly unknown. Expected notes are
the candidate Markdown; a catalog's transformed text is reported different for human review, never success.
"""
from __future__ import annotations

import argparse
import datetime
import json
import urllib.error
import urllib.request
from pathlib import Path

URL = "https://mcprush.com/api/servers/buddie-mcp"


def observe(data, version: str, notes: str) -> dict:
    result = {"channel": "mcprush", "version": "unknown", "notes": "unknown", "publication": "manual-unverified"}
    if not isinstance(data, dict) or not notes.strip():
        return result
    listing = data.get("listing")
    releases = data.get("releases")
    if not isinstance(listing, dict) or not isinstance(releases, list):
        return result
    source = listing.get("source")
    if (listing.get("id") != "buddie-mcp" or not isinstance(source, dict)
            or source.get("kind") != "pypi" or source.get("value") != "buddie"
            or listing.get("delivery") != "direct" or listing.get("hosting") != "local"):
        return result
    matched = [r for r in releases if isinstance(r, dict) and r.get("version") == version]
    if not matched:
        result["version"] = "missing"
        return result
    if len(matched) != 1:
        return result
    result["version"] = "observed"
    visible = matched[0].get("notes")
    if visible == [] or visible == "":
        result["notes"] = "missing"
    elif isinstance(visible, str):
        result["notes"] = "observed" if visible.strip() == notes.strip() else "different"
    elif isinstance(visible, list) and all(isinstance(n, str) for n in visible):
        result["notes"] = "observed" if "\n".join(visible).strip() == notes.strip() else "different"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", required=True)
    parser.add_argument("--notes", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, help="inspect a previously saved response without network")
    args = parser.parse_args()
    notes = args.notes.read_text(encoding="utf-8")
    failure = None
    try:
        if args.snapshot:
            data = json.loads(args.snapshot.read_text(encoding="utf-8"))
        else:
            request = urllib.request.Request(URL, headers={"Accept": "application/json", "Cache-Control": "no-cache"})
            with urllib.request.urlopen(request, timeout=20) as response:
                if response.headers.get("Age", "0") != "0":
                    raise ValueError("cached response: freshness unverified")
                data = json.loads(response.read(2 * 1024 * 1024))
    except (OSError, ValueError) as error:
        data, failure = None, type(error).__name__
    result = observe(data, args.version, notes)
    result.update(url=URL, requested_version=args.version,
                  checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  freshness="unverified" if args.snapshot or failure else "live-response",
                  evidence="saved-snapshot" if args.snapshot else "live-get")
    if failure:
        result["unavailable"] = failure
    print(json.dumps(result, indent=2))
    return 0 if not args.snapshot and result["version"] == result["notes"] == "observed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
