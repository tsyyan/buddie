"""The decisions of release.yml's publish run (docs/release.md), kept here so they can be tested without publishing:
who may publish what, whether a stage is already done, and the GitHub Release.

    python scripts/release_publish.py authorize RC --run RUN_JSON --candidate ID --repo O/R --sha SHA --ref-type T
        --ref-name NAME --tag-commit SHA --on-main yes|no --version V --confirm TEXT [--only STAGE]
    python scripts/release_publish.py pypi-plan RC PYPI_JSON|-          # prints upload or done
    python scripts/release_publish.py registry-check SERVER_JSON LISTED_JSON
    python scripts/release_publish.py github-release RC --repo O/R --tag vV --sha SHA --version V --notes FILE

RC is the downloaded candidate (scripts/release_manifest.py). Each command exits 0 when it may go on and 1 with every
reason on stderr. github-release talks to the GitHub API with $GH_TOKEN; the tests drive it through a fake API.
Nothing here overwrites or deletes: a file that differs from the candidate, or one whose bytes cannot be checked,
stops the run for a person to look at.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import release_manifest as rm  # noqa: E402

WORKFLOW = ".github/workflows/release.yml"
API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"


class Stop(Exception):
    """A state this run must not change: a person decides."""


# --- authorize -------------------------------------------------------------------------------------------------------

def confirmation(version: str, only: str = "all") -> str:
    """The words a person types to approve `only`: publishing, or promoting the plugin to plugin-stable. One
    approval never covers the other."""
    return f"promote buddie {version} to plugin-stable" if only == "plugin-stable" else f"publish buddie {version}"


def authorize(rc: Path, run: dict, candidate: str, *, repo: str, sha: str, ref_type: str, ref_name: str,
              tag_commit: str, on_main: bool, version: str, confirm: str, only: str = "all") -> list[str]:
    """Every reason this run may not publish (or, with only="plugin-stable", promote) the candidate in `rc`.
    `run` is the GitHub API's record of the candidate run, `tag_commit` what the tag names now (git rev-parse),
    `on_main` whether that commit is in main's history, `version` buddie.__version__ at the checked-out tag."""
    tag = f"v{version}"
    checks = [
        (ref_type == "tag", f"publish runs on a release tag, not the {ref_type or 'unknown'} {ref_name}"),
        (ref_name == tag, f"tag {ref_name} but buddie.__version__ is {version}"),
        (tag_commit == sha, f"the tag {ref_name} names {tag_commit}, the run checked out {sha}"),
        (on_main, f"{sha} is not in main's history"),
        (confirm == confirmation(version, only), f"confirm must be exactly: {confirmation(version, only)}"),
        (str(candidate).isdigit() and str(run.get("id")) == str(candidate),
         f"candidate {candidate!r} is not the run the API returned ({run.get('id')})"),
        (run.get("path") == WORKFLOW, f"the candidate run is {run.get('path')}, not {WORKFLOW}"),
        ((run.get("repository") or {}).get("full_name") == repo, "the candidate run belongs to another repository"),
        ((run.get("head_repository") or {}).get("full_name") == repo, "the candidate was built from another repository"),
        (run.get("event") in ("push", "workflow_dispatch"), f"the candidate run's event is {run.get('event')}"),
        (run.get("head_branch") == tag, f"the candidate ran on {run.get('head_branch')}, not {tag}"),
        (run.get("head_sha") == sha, f"the candidate built {run.get('head_sha')}, the tag is {sha}"),
        ((run.get("status"), run.get("conclusion")) == ("completed", "success"),
         f"the candidate run is {run.get('status')}/{run.get('conclusion')}, not completed/success"),
    ]
    problems = [why for ok, why in checks if not ok]
    problems += rm.verify(rc, version, sha)
    if not problems:
        record = rm.load(rc)
        if str(record.get("run_id")) != str(candidate):
            problems.append(f"the artifact records run {record.get('run_id')}, not {candidate}")
        if record.get("repository") != repo:
            problems.append(f"the artifact records repository {record.get('repository')}")
        if record.get("ref") != f"refs/tags/{tag}":
            problems.append(f"the artifact was built for {record.get('ref')}, not refs/tags/{tag}")
    return problems


# --- PyPI --------------------------------------------------------------------------------------------------------------

def pypi_plan(rc: Path, release: dict | None) -> str:
    """'upload' when PyPI lacks some of the candidate's files and holds nothing else for the version, 'done' when it
    serves exactly the candidate's files by SHA-256; Stop when it holds anything that is not the candidate's."""
    if release is None:
        return "upload"
    problems = rm.pypi(rc, release)
    conflicts = [p for p in problems if not p.startswith("PyPI has no ")]
    if conflicts:
        raise Stop("; ".join(conflicts) + ". A version on PyPI is never replaced: release the next version")
    return "upload" if problems else "done"


# --- MCP Registry ------------------------------------------------------------------------------------------------------

def _identity(server: dict) -> dict:
    """What the registry entry must say for it to be this release: the name, the version, the repository, and the
    package it sends clients to. The registry stores no digest; the bytes are PyPI's, checked there."""
    return {"name": server.get("name"), "version": server.get("version"),
            "repository": (server.get("repository") or {}).get("url"),
            "release_metadata": (server.get("_meta") or {}).get(rm.rn.META),
            "packages": [{k: p.get(k) for k in ("registryType", "registryBaseUrl", "identifier", "version")}
                         | {"transport": (p.get("transport") or {}).get("type"),
                            "arguments": [a.get("value") for a in p.get("packageArguments", [])]}
                         for p in server.get("packages", [])]}


def registry_check(local: dict, listed: dict) -> list[str]:
    """The registry's entry for the version against server.json: same identity, field by field."""
    mine, theirs = _identity(local), _identity(listed.get("server", listed))
    return [f"the registry's {k} is {theirs[k]!r}, server.json says {mine[k]!r}" for k in mine if mine[k] != theirs[k]]


# --- GitHub Release ----------------------------------------------------------------------------------------------------

class GitHub:
    """The few REST calls the release needs. `call` is the only network access; tests replace it."""

    def __init__(self, repo: str, token: str | None = None):
        self.repo, self.token = repo, token

    def call(self, method: str, url: str, body: bytes | None = None, headers: dict | None = None):
        request = urllib.request.Request(url, data=body, method=method, headers={
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
            **({"Authorization": f"Bearer {self.token}"} if self.token else {}), **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 (fixed https hosts)
                data = response.read()
                status = response.status
        except urllib.error.HTTPError as error:
            data, status = error.read(), error.code
        if (headers or {}).get("Accept") == "application/octet-stream":
            return status, data
        return status, json.loads(data) if data else None

    def _json(self, method, path, obj=None):
        body = json.dumps(obj).encode() if obj is not None else None
        return self.call(method, f"{API}/repos/{self.repo}{path}", body,
                         {"Content-Type": "application/json"} if body else None)

    def tag_commit(self, tag: str) -> str | None:
        status, ref = self._json("GET", f"/git/ref/tags/{urllib.parse.quote(tag)}")
        if status != 200:
            return None
        obj = ref["object"]
        while obj.get("type") == "tag":  # an annotated tag names a tag object first
            status, tagobj = self._json("GET", f"/git/tags/{obj['sha']}")
            if status != 200:
                return None
            obj = tagobj["object"]
        return obj.get("sha") if obj.get("type") == "commit" else None

    def published(self, tag: str) -> dict | None:
        status, release = self._json("GET", f"/releases/tags/{urllib.parse.quote(tag)}")
        return release if status == 200 else None

    def releases(self) -> list[dict]:
        out, page = [], 1
        while True:
            status, batch = self._json("GET", f"/releases?per_page=100&page={page}")
            if status != 200:
                raise Stop(f"listing releases answered {status}")
            out += batch
            if len(batch) < 100:
                return out
            page += 1

    def release(self, rid: int) -> dict:
        status, release = self._json("GET", f"/releases/{rid}")
        if status != 200:
            raise Stop(f"release {rid} answered {status}")
        return release

    def create_draft(self, tag: str, sha: str, title: str, notes: str) -> dict:
        status, release = self._json("POST", "/releases", {"tag_name": tag, "target_commitish": sha, "name": title,
                                                            "body": notes, "draft": True})
        if status != 201:
            raise Stop(f"creating the draft answered {status}: {release}")
        return release

    def upload(self, rid: int, name: str, data: bytes) -> dict:
        status, asset = self.call("POST", f"{UPLOADS}/repos/{self.repo}/releases/{rid}/assets?"
                                  + urllib.parse.urlencode({"name": name}), data,
                                  {"Content-Type": "application/octet-stream"})
        if status != 201:
            raise Stop(f"uploading {name} answered {status}: {asset}")
        return asset

    def download(self, asset_id: int) -> bytes | None:
        status, data = self.call("GET", f"{API}/repos/{self.repo}/releases/assets/{asset_id}", None,
                                 {"Accept": "application/octet-stream"})
        return data if status == 200 else None

    def publish(self, rid: int) -> dict:
        status, release = self._json("PATCH", f"/releases/{rid}", {"draft": False})
        if status != 200:
            raise Stop(f"publishing the draft answered {status}")
        return release


def _wanted(rc: Path) -> dict[str, tuple[Path, str]]:
    """Each file the release carries: its name, where it is in the candidate, its SHA-256."""
    files = {Path(f["path"]).name: (rc / f["path"], f["sha256"]) for f in rm.load(rc)["files"]}
    for extra in (rm.MANIFEST, rm.SUMS):
        files[extra] = (rc / extra, hashlib.sha256((rc / extra).read_bytes()).hexdigest())
    return files


def _audit(gh: GitHub, release: dict, wanted: dict) -> list[str]:
    """The names still missing from `release`; Stop for an asset that is not the candidate's file, one whose
    upload did not finish, one GitHub gives no digest for and that cannot be downloaded, and a name the candidate
    does not have."""
    if release.get("body") != wanted["release-notes.md"][0].read_text(encoding="utf-8"):
        raise Stop("release body differs from the approved candidate notes")
    missing = set(wanted)
    for asset in release.get("assets", []):
        name = asset.get("name")
        if name not in wanted:
            raise Stop(f"the release carries {name}, which is not a candidate file")
        if asset.get("state") != "uploaded":
            raise Stop(f"{name} on the release is {asset.get('state')!r}, an upload that did not finish: delete that "
                       "asset by hand after looking at it, then run the stage again")
        digest = str(asset.get("digest") or "")
        if digest.startswith("sha256:"):
            got = digest.removeprefix("sha256:")
        else:  # no digest from the API: hash the bytes themselves, or stop
            data = gh.download(asset["id"])
            if data is None:
                raise Stop(f"{name}: GitHub gives no digest and the file cannot be downloaded, so it cannot be checked")
            got = hashlib.sha256(data).hexdigest()
        if got != wanted[name][1]:
            raise Stop(f"{name} on the release is not the candidate's file (sha256 {got}); it is never replaced")
        missing.discard(name)
    return sorted(missing)


def github_release(gh: GitHub, rc: Path, *, tag: str, sha: str, version: str, notes: str) -> dict:
    """Create or find the draft for `tag`, upload what it lacks, check every asset against the candidate, publish
    it, and check again. A published release is only checked: never added to or changed."""
    problems = rm.verify(rc, version, sha)
    if problems:
        raise Stop("; ".join(problems))
    if notes.encode("utf-8") != (rc / "metadata/release-notes.md").read_bytes():
        raise Stop("notes differ from the approved candidate notes")
    if tag != f"v{version}":
        raise Stop(f"tag {tag} is not v{version}")
    named = gh.tag_commit(tag)
    if named != sha:
        raise Stop(f"the tag {tag} names {named}, the candidate is {sha}")
    wanted = _wanted(rc)
    release = gh.published(tag)
    if release is not None:
        missing = _audit(gh, release, wanted)
        if missing:
            raise Stop(f"the release {tag} is published without {', '.join(missing)}: add them by hand after checking")
        return release
    drafts = [r for r in gh.releases() if r.get("tag_name") == tag and r.get("draft")]
    if len(drafts) > 1:
        raise Stop(f"{len(drafts)} draft releases for {tag}: delete the extra ones by hand")
    rid = drafts[0]["id"] if drafts else gh.create_draft(tag, sha, f"buddie {version}", notes)["id"]
    release = gh.release(rid)  # the release by its id, not by a listing
    if release.get("tag_name") != tag:
        raise Stop(f"release {rid} is for {release.get('tag_name')}, not {tag}")
    for name in _audit(gh, release, wanted):
        gh.upload(rid, name, wanted[name][0].read_bytes())
    release = gh.release(rid)
    if missing := _audit(gh, release, wanted):
        raise Stop(f"still missing after upload: {', '.join(missing)}")
    gh.publish(rid)
    release = gh.published(tag)
    if release is None or release.get("id") != rid or release.get("draft"):
        raise Stop(f"the release {tag} is not published as release {rid}")
    if missing := _audit(gh, release, wanted):
        raise Stop(f"the published release lacks {', '.join(missing)}")
    return release


# --- command line ------------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("authorize")
    a.add_argument("rc", type=Path)
    for opt in ("--run", "--candidate", "--repo", "--sha", "--ref-type", "--ref-name", "--tag-commit", "--on-main",
                "--version", "--confirm"):
        a.add_argument(opt, required=True)
    a.add_argument("--only", default="all")
    p = sub.add_parser("pypi-plan")
    p.add_argument("rc", type=Path)
    p.add_argument("json")
    r = sub.add_parser("registry-check")
    r.add_argument("server", type=Path)
    r.add_argument("listed", type=Path)
    g = sub.add_parser("github-release")
    g.add_argument("rc", type=Path)
    for opt in ("--repo", "--tag", "--sha", "--version", "--notes"):
        g.add_argument(opt, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "authorize":
            problems = authorize(args.rc, json.loads(Path(args.run).read_text(encoding="utf-8")), args.candidate,
                                 repo=args.repo, sha=args.sha, ref_type=args.ref_type, ref_name=args.ref_name,
                                 tag_commit=args.tag_commit, on_main=args.on_main == "yes", version=args.version,
                                 confirm=args.confirm, only=args.only)
        elif args.command == "pypi-plan":
            release = None if args.json == "-" else json.loads(Path(args.json).read_text(encoding="utf-8"))
            print(pypi_plan(args.rc, release))
            problems = []
        elif args.command == "registry-check":
            problems = registry_check(json.loads(args.server.read_text(encoding="utf-8")),
                                      json.loads(args.listed.read_text(encoding="utf-8")))
        else:
            gh = GitHub(args.repo, os.environ.get("GH_TOKEN"))
            release = github_release(gh, args.rc, tag=args.tag, sha=args.sha, version=args.version,
                                     notes=Path(args.notes).read_text(encoding="utf-8"))
            print(f"release {release['id']} {release.get('html_url', '')}: published, every asset the candidate's")
            problems = []
    except Stop as stop:
        problems = [str(stop)]
    for problem in problems:
        print(f"release_publish: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
