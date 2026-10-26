"""The publish run's decisions (scripts/release_publish.py, docs/release.md), against a fake GitHub REST API held in
memory and recorded PyPI and registry answers: nothing here reaches a real service. Publishing must be impossible
unless every identity check holds, repeatable after a stage stopped halfway, and must never replace a file."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import urllib.parse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import release_manifest as rm  # noqa: E402
import release_publish as rp  # noqa: E402
from test_release_manifest import bind_plugin  # noqa: E402

V, TAG, REPO = "2.0.0", "v2.0.0", "tsyyan/buddie"
SHA = "4ae6b16566f3b5c9c2081396a28dc886a9b18fae"
OTHER = "b6464a7839274297c5c110ddd1a50557f4281c42"
RUN = "40020947041"


@pytest.fixture
def rc(tmp_path):
    root = tmp_path / "rc"
    for path in rm.expected(V):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(path.encode() * 50)
    bind_plugin(root, V, SHA)
    assert rm.write(root, V, SHA, f"refs/tags/{TAG}", REPO, RUN) == []
    return root


def _files(rc: Path) -> dict[str, bytes]:
    out = {Path(f["path"]).name: (rc / f["path"]).read_bytes() for f in rm.load(rc)["files"]}
    out.update({n: (rc / n).read_bytes() for n in (rm.MANIFEST, rm.SUMS)})
    return out


# --- a fake GitHub ------------------------------------------------------------------------------------------------------

class FakeGitHub(rp.GitHub):
    """The REST endpoints github_release uses, routed by URL. Assets carry their bytes; `digests=False` answers
    without the `digest` field, `downloads=False` refuses downloads, `interrupt` raises on that upload (1-based),
    leaving the asset absent or, with `partial`, half-made (state 'starter')."""

    def __init__(self, tags=None, digests=True, downloads=True, interrupt=None, partial=False):
        super().__init__(REPO)
        self.tags = dict(tags if tags is not None else {TAG: SHA})
        self.items, self.next_id, self.log = [], 100, []
        self.digests, self.downloads, self.interrupt, self.partial, self.uploads = digests, downloads, interrupt, partial, 0

    def add(self, draft=True, tag=TAG, files=None, **asset):
        rel = {"id": self._id(), "tag_name": tag, "draft": draft, "assets": []}
        for name, data in (files or {}).items():
            rel["assets"].append(self._asset(name, data, **asset))
        self.items.append(rel)
        return rel

    def _id(self):
        self.next_id += 1
        return self.next_id

    def _asset(self, name, data, state="uploaded", digest=None):
        return {"id": self._id(), "name": name, "size": len(data), "state": state, "data": data,
                "digest": digest if digest is not None else "sha256:" + hashlib.sha256(data).hexdigest()}

    def _view(self, rel):
        rel = copy.deepcopy(rel)
        for a in rel["assets"]:
            a.pop("data")
            if not self.digests:
                a.pop("digest")
        return rel

    def call(self, method, url, body=None, headers=None):
        self.log.append((method, url))
        parts = urllib.parse.urlsplit(url)
        path, query = parts.path.removeprefix(f"/repos/{REPO}"), dict(urllib.parse.parse_qsl(parts.query))
        if method == "GET" and path.startswith("/git/ref/tags/"):
            sha = self.tags.get(urllib.parse.unquote(path.rsplit("/", 1)[1]))
            return (200, {"object": {"type": "commit", "sha": sha}}) if sha else (404, {"message": "Not Found"})
        if method == "GET" and path.startswith("/releases/tags/"):  # GitHub never answers a draft here
            tag = urllib.parse.unquote(path.rsplit("/", 1)[1])
            hits = [r for r in self.items if r["tag_name"] == tag and not r["draft"]]
            return (200, self._view(hits[0])) if hits else (404, {"message": "Not Found"})
        if method == "GET" and path == "/releases":
            page, size = int(query.get("page", 1)), int(query.get("per_page", 30))
            return 200, [self._view(r) for r in self.items[(page - 1) * size:page * size]]
        if method == "GET" and path.startswith("/releases/assets/"):
            aid = int(path.rsplit("/", 1)[1])
            data = next(a["data"] for r in self.items for a in r["assets"] if a["id"] == aid)
            return (200, data) if self.downloads else (404, b"")
        if path.startswith("/releases/") and path.count("/") == 2:
            rel = next((r for r in self.items if r["id"] == int(path.rsplit("/", 1)[1])), None)
            if rel is None:
                return 404, {"message": "Not Found"}
            if method == "PATCH":
                rel.update(json.loads(body))
            return 200, self._view(rel)
        if method == "POST" and path == "/releases":
            obj = json.loads(body)
            rel = self.add(draft=obj["draft"], tag=obj["tag_name"])
            return 201, self._view(rel)
        if method == "POST" and parts.netloc == "uploads.github.com" and path.endswith("/assets"):
            self.uploads += 1
            rel = next(r for r in self.items if r["id"] == int(path.split("/")[2]))
            if self.interrupt == self.uploads:
                if self.partial:
                    rel["assets"].append(self._asset(query["name"], body[:3], state="starter", digest=""))
                raise ConnectionError("the upload was cut off")
            rel["assets"].append(self._asset(query["name"], body))
            return 201, self._view(rel)["assets"][-1]
        raise AssertionError(f"unexpected call {method} {url}")

    def writes(self):
        return [(m, u) for m, u in self.log if m != "GET"]


def _publish(gh, rc, **kw):
    return rp.github_release(gh, rc, tag=kw.get("tag", TAG), sha=kw.get("sha", SHA), version=V, notes="notes")


def _ok(gh, rc):
    rel = next(r for r in gh.items if r["tag_name"] == TAG)
    assert rel["draft"] is False
    assert {a["name"]: a["data"] for a in rel["assets"]} == _files(rc)
    assert len([r for r in gh.items if r["tag_name"] == TAG]) == 1


# --- GitHub Release ---------------------------------------------------------------------------------------------------

def test_no_release_creates_a_draft_uploads_everything_and_publishes_it(rc):
    gh = FakeGitHub()
    _publish(gh, rc)
    _ok(gh, rc)
    assert gh.uploads == len(_files(rc))  # every candidate file, the record and the sums
    # created as a draft, re-read by its id, published last
    writes = gh.writes()
    assert writes[0][0] == "POST" and writes[0][1].endswith("/releases") and writes[-1][0] == "PATCH"
    assert any(m == "GET" and u.endswith(f"/releases/{gh.items[0]['id']}") for m, u in gh.log)


def test_an_existing_draft_is_completed_not_duplicated(rc):
    gh = FakeGitHub()
    gh.add(draft=True)
    _publish(gh, rc)
    _ok(gh, rc)
    assert not any(m == "POST" and u.endswith("/releases") for m, u in gh.log)


def test_a_published_release_with_every_asset_is_left_alone(rc):
    gh = FakeGitHub()
    gh.add(draft=False, files=_files(rc))
    _publish(gh, rc)
    assert gh.writes() == []


def test_a_published_release_missing_an_asset_stops_unchanged(rc):
    gh = FakeGitHub()
    files = _files(rc)
    files.pop(rm.SUMS)
    gh.add(draft=False, files=files)
    with pytest.raises(rp.Stop, match="published without SHA256SUMS"):
        _publish(gh, rc)
    assert gh.writes() == []


def test_a_draft_with_some_assets_gets_only_the_missing_ones(rc):
    gh = FakeGitHub()
    files = _files(rc)
    gh.add(draft=True, files=dict(list(files.items())[:2]))
    _publish(gh, rc)
    _ok(gh, rc)
    assert gh.uploads == len(_files(rc)) - 2


def test_a_draft_with_every_asset_is_only_published(rc):
    gh = FakeGitHub()
    gh.add(draft=True, files=_files(rc))
    _publish(gh, rc)
    _ok(gh, rc)
    assert gh.uploads == 0 and [m for m, _ in gh.writes()] == ["PATCH"]


@pytest.mark.parametrize("draft", [True, False])
def test_an_asset_with_another_sha256_is_never_replaced(rc, draft):
    gh = FakeGitHub()
    files = _files(rc)
    name = f"buddie-{V}-py3-none-any.whl"
    files[name] = b"a different wheel"
    gh.add(draft=draft, files=files)
    with pytest.raises(rp.Stop, match="not the candidate's file.*never replaced"):
        _publish(gh, rc)
    assert gh.writes() == []
    assert next(a for a in gh.items[0]["assets"] if a["name"] == name)["data"] == b"a different wheel"


def test_without_a_digest_the_bytes_themselves_are_checked(rc):
    files = _files(rc)
    gh = FakeGitHub(digests=False)
    gh.add(draft=True, files=files)
    _publish(gh, rc)  # every asset downloaded and hashed
    _ok(gh, rc)
    assert sum(1 for _, u in gh.log if "/releases/assets/" in u) >= 5

    gh = FakeGitHub(digests=False)
    files[rm.MANIFEST] = b"{}"
    gh.add(draft=True, files=files)
    with pytest.raises(rp.Stop, match="release-manifest.json on the release is not the candidate's"):
        _publish(gh, rc)


def test_a_digest_that_cannot_be_had_stops(rc):
    gh = FakeGitHub(digests=False, downloads=False)
    gh.add(draft=True, files=_files(rc))
    with pytest.raises(rp.Stop, match="cannot be checked"):
        _publish(gh, rc)
    assert gh.writes() == []
    gh = FakeGitHub()
    gh.add(draft=True, files=_files(rc), digest="md5:0")  # a digest that is not sha256, and no download
    gh.downloads = False
    with pytest.raises(rp.Stop, match="cannot be checked"):
        _publish(gh, rc)


def test_a_run_cut_off_mid_upload_is_completed_by_the_next(rc):
    gh = FakeGitHub(interrupt=3)
    with pytest.raises(ConnectionError):
        _publish(gh, rc)
    rel = gh.items[0]
    assert rel["draft"] is True and len(rel["assets"]) == 2  # nothing published halfway
    gh.interrupt = None
    _publish(gh, rc)
    _ok(gh, rc)
    assert gh.uploads == 3 + len(_files(rc)) - 2  # the second run sent only the ones still missing


def test_a_half_made_asset_stops_for_a_person(rc):
    gh = FakeGitHub(interrupt=2, partial=True)
    with pytest.raises(ConnectionError):
        _publish(gh, rc)
    gh.interrupt = None
    with pytest.raises(rp.Stop, match="did not finish: delete that asset by hand"):
        _publish(gh, rc)
    assert gh.items[0]["draft"] is True


@pytest.mark.parametrize("tags, why", [({TAG: OTHER}, f"names {OTHER}"), ({}, "names None")])
def test_a_tag_on_another_commit_or_no_tag_stops_before_any_write(rc, tags, why):
    gh = FakeGitHub(tags=tags)
    with pytest.raises(rp.Stop, match=why):
        _publish(gh, rc)
    assert gh.writes() == []


def test_a_release_found_for_another_tag_or_twice_stops(rc, monkeypatch):
    gh = FakeGitHub()
    gh.add(draft=True)
    gh.add(draft=True)
    with pytest.raises(rp.Stop, match="2 draft releases"):
        _publish(gh, rc)
    gh = FakeGitHub()
    other = gh.add(draft=True, tag="v1.9.9")
    monkeypatch.setattr(gh, "releases", lambda: [dict(other, tag_name=TAG)])  # a listing that misnames it
    with pytest.raises(rp.Stop, match="is for v1.9.9"):
        _publish(gh, rc)
    assert gh.writes() == []


def test_a_modified_candidate_is_not_published(rc):
    (rc / f"bundle/buddie-{V}.mcpb").write_bytes(b"swapped")
    gh = FakeGitHub()
    with pytest.raises(rp.Stop, match="not the file the candidate recorded"):
        _publish(gh, rc)
    assert gh.log == []


# --- authorize ----------------------------------------------------------------------------------------------------------

def _run(**over):
    run = {"id": int(RUN), "path": rp.WORKFLOW, "repository": {"full_name": REPO},
           "head_repository": {"full_name": REPO}, "event": "push", "head_branch": TAG, "head_sha": SHA,
           "status": "completed", "conclusion": "success"}
    run.update(over)
    return run


GOOD = dict(repo=REPO, sha=SHA, ref_type="tag", ref_name=TAG, tag_commit=SHA, on_main=True, version=V,
            confirm=f"publish buddie {V}")


def test_the_approved_candidate_on_its_tag_is_authorized(rc):
    assert rp.authorize(rc, _run(), RUN, **GOOD) == []
    assert rp.authorize(rc, _run(event="workflow_dispatch"), RUN, **GOOD) == []


@pytest.mark.parametrize("change, why", [
    (dict(ref_type="branch", ref_name="main"), "not the branch main"),
    (dict(ref_name="v2.0.1"), "but buddie.__version__ is 2.0.0"),
    (dict(version="2.0.1", ref_name="v2.0.1", confirm="publish buddie 2.0.1"), "candidate is version"),
    (dict(confirm="publish buddie 2.0"), "confirm must be exactly"),
    (dict(confirm=""), "confirm must be exactly"),
    (dict(tag_commit=OTHER), f"names {OTHER}"),
    (dict(on_main=False), "not in main's history"),
])
def test_the_run_itself_must_be_the_approved_release(rc, change, why):
    assert any(why in p for p in rp.authorize(rc, _run(), RUN, **(GOOD | change)))


@pytest.mark.parametrize("run, why", [
    (_run(repository={"full_name": "someone/buddie"}), "belongs to another repository"),
    (_run(head_repository={"full_name": "someone/buddie"}), "built from another repository"),
    (_run(head_sha=OTHER), f"the candidate built {OTHER}"),
    (_run(conclusion="failure"), "completed/failure"),
    (_run(status="in_progress", conclusion=None), "in_progress/None"),
    (_run(path=".github/workflows/ci.yml"), "not .github/workflows/release.yml"),
    (_run(event="pull_request"), "event is pull_request"),
    (_run(head_branch="main"), "ran on main"),
    (_run(id=1), "not the run the API returned"),
])
def test_the_candidate_run_must_be_this_repositorys_release_run_for_this_commit(rc, run, why):
    assert any(why in p for p in rp.authorize(rc, run, RUN, **GOOD))


def test_a_modified_or_foreign_artifact_is_refused(rc):
    (rc / f"dist/buddie-{V}.tar.gz").write_bytes(b"rebuilt")
    assert any("not the file the candidate recorded" in p for p in rp.authorize(rc, _run(), RUN, **GOOD))


@pytest.mark.parametrize("field, value, why", [("run_id", "1", "records run 1"),
                                                ("repository", "someone/buddie", "records repository"),
                                                ("ref", "refs/heads/main", "built for refs/heads/main")])
def test_the_artifacts_own_record_must_name_this_run_repository_and_tag(tmp_path, field, value, why):
    root = tmp_path / "rc"
    for path in rm.expected(V):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(b"x")
    bind_plugin(root, V, SHA)
    meta = {"ref": f"refs/tags/{TAG}", "repository": REPO, "run_id": RUN} | {field: value}
    assert rm.write(root, V, SHA, meta["ref"], meta["repository"], meta["run_id"]) == []
    assert any(why in p for p in rp.authorize(root, _run(), RUN, **GOOD))


def test_authorize_on_the_command_line(rc, tmp_path):
    run = tmp_path / "run.json"
    run.write_text(json.dumps(_run()), encoding="utf-8")
    args = ["authorize", str(rc), "--run", str(run), "--candidate", RUN, "--repo", REPO, "--sha", SHA,
            "--ref-type", "tag", "--ref-name", TAG, "--tag-commit", SHA, "--on-main", "yes", "--version", V]
    assert rp.main(args + ["--confirm", f"publish buddie {V}"]) == 0
    assert rp.main(args + ["--confirm", "yes"]) == 1


# --- PyPI ---------------------------------------------------------------------------------------------------------------

def _pypi(rc, keep=("wheel", "sdist"), change=None):
    urls = [{"filename": Path(f["path"]).name, "digests": {"sha256": f["sha256"]}}
            for f in rm.load(rc)["files"] if f["kind"] in keep]
    if change:
        urls[0]["digests"]["sha256"] = change
    return {"urls": urls}


def test_pypi_without_the_version_is_uploaded(rc):
    assert rp.pypi_plan(rc, None) == "upload"


def test_pypi_with_exactly_the_candidates_files_is_done(rc):
    assert rp.pypi_plan(rc, _pypi(rc)) == "done"


def test_pypi_with_one_of_the_files_gets_the_other(rc):
    assert rp.pypi_plan(rc, _pypi(rc, keep=("wheel",))) == "upload"


def test_pypi_with_another_file_stops(rc):
    with pytest.raises(rp.Stop, match="never replaced"):
        rp.pypi_plan(rc, _pypi(rc, change="f" * 64))
    extra = _pypi(rc)
    extra["urls"].append({"filename": f"buddie-{V}-cp312-win_amd64.whl", "digests": {"sha256": "0" * 64}})
    with pytest.raises(rp.Stop, match="which the candidate does not"):
        rp.pypi_plan(rc, extra)


# --- MCP Registry -------------------------------------------------------------------------------------------------------

def _server():
    return json.loads((ROOT / "server.json").read_text(encoding="utf-8"))


def test_the_registry_entry_for_the_version_matches_server_json():
    listed = {"server": _server(), "_meta": {"io.modelcontextprotocol.registry/official": {"isLatest": True}}}
    # the registry drops false values (isRequired: false) and reorders keys: identity is what is compared
    for var in listed["server"]["packages"][0]["environmentVariables"]:
        var.pop("isRequired", None)
    assert rp.registry_check(_server(), listed) == []


@pytest.mark.parametrize("path, value, why", [
    (("version",), "0.0.0", "version"),  # never server.json's own version, whichever release this is
    (("repository", "url"), "https://github.com/someone/buddie", "repository"),
    (("packages", 0, "identifier"), "buddie-fork", "packages"),
    (("packages", 0, "version"), "1.1.1", "packages"),
    (("packages", 0, "registryType"), "npm", "packages"),
])
def test_a_registry_entry_that_names_another_package_or_version_is_refused(path, value, why):
    listed = {"server": _server()}
    node = listed["server"]
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    assert any(why in p for p in rp.registry_check(_server(), listed))
