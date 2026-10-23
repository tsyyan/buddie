"""Phase 1 / PR 3: a repo's config, a remote client and a fetched page get no more than their contract, and every read
has a size limit applied before the bytes are in memory."""
from __future__ import annotations

import gzip
import hashlib
import os
import urllib.request

import pytest

from buddie import anchors, effects, mandate, mcp, remote
from buddie.verbatim import store as vstore
from buddie.verbatim import textlayer
from buddie.verbatim.store import Store

QUEUE = "| № | Шаг | Тема | Основание | Статус |\n|---|---|---|---|---|\n| 1 | Секрет | t | — | предложено |\n"


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "NEXT.md").write_text(QUEUE, encoding="utf-8")
    (tmp_path / "outside" / "m.jsonl").write_text('{"id": 1, "text": "secret"}\n', encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "NEXT.md").write_text(QUEUE, encoding="utf-8")
    return repo, tmp_path / "outside"


# --- configuration from the repo under check ----------------------------------------------------------------------

@pytest.mark.parametrize("path", ["../outside/NEXT.md", "..\\outside\\NEXT.md", "ABSOLUTE"])
def test_buddie_toml_paths_stay_in_the_repo(tree, path):
    repo, outside = tree
    path = (outside / "NEXT.md").as_posix() if path == "ABSOLUTE" else path
    cfg = {**mandate.DEFAULTS, "repo": str(repo)}
    assert mandate.read(cfg, "NEXT.md") == QUEUE
    with pytest.raises(FileNotFoundError):
        mandate.read(cfg, path)
    assert mandate.messages({**cfg, "messages": path.replace("NEXT.md", "m.jsonl")}) is None


def test_a_config_named_file_over_the_limit_is_not_read(tree, monkeypatch):
    repo, _ = tree
    monkeypatch.setattr(anchors, "MAX_TEXT_BYTES", 10)
    with pytest.raises(FileNotFoundError):
        mandate.read({**mandate.DEFAULTS, "repo": str(repo)}, "NEXT.md")


# --- file anchors: size --------------------------------------------------------------------------------------------

def test_a_file_anchor_over_the_limit_is_not_hashed(tmp_path, monkeypatch):
    (tmp_path / "big.txt").write_bytes(b"x" * 11)
    (tmp_path / "small.txt").write_bytes(b"hello\n")
    monkeypatch.setattr(anchors, "MAX_FILE_BYTES", 10)
    big = anchors.check_text(f"`⚓ big.txt#{hashlib.sha256(b'x' * 11).hexdigest()[:12]}`", [tmp_path])[0]
    assert big["status"] == "UNCHECKABLE" and "MiB" in big["why"]
    small = anchors.check_text(f"`⚓ small.txt#{hashlib.sha256(b'hello' + bytes([10])).hexdigest()[:12]}`", [tmp_path])
    assert small[0]["status"] == "HOLDS"


@pytest.mark.skipif(os.name != "nt", reason="Windows handle path")
def test_windows_checks_the_path_of_the_opened_handle(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_bytes(b"hello\n")
    root = tmp_path.resolve()
    fd = os.open(root / "a.txt", os.O_RDONLY)
    try:
        assert os.path.normcase(anchors._final_path(fd)) == os.path.normcase(str(root / "a.txt"))
    finally:
        os.close(fd)
    assert anchors._open(root / "a.txt", root) is not None
    # a path swapped to a file elsewhere between the check and the open: the handle tells, and nothing is read
    monkeypatch.setattr(anchors, "_final_path", lambda fd: "C:\\Windows\\win.ini")
    assert anchors._open(root / "a.txt", root) is None


# --- the remote server ---------------------------------------------------------------------------------------------

def pr_body(repo, private=False):
    return {"state": "open", "draft": False, "merged": False, "head": {"sha": "9653a7c" + "0" * 33},
            "base": {"repo": {"full_name": repo, "private": private}}}


PR_BODY = pr_body("o/pub")


@pytest.fixture
def github(monkeypatch):
    calls = []
    answers = {"/repos/o/priv": {"private": True, "full_name": "o/priv"}, "/repos/o/priv/pulls/1": pr_body("o/priv", True),
               "/repos/o/pub": {"private": False, "full_name": "o/pub"}, "/repos/o/pub/pulls/1": PR_BODY,
               "/repos/O/Pub": {"private": False, "full_name": "o/pub"}, "/repos/O/Pub/pulls/1": PR_BODY,
               # renamed: the old name answers for the new repo
               "/repos/o/old": {"private": False, "full_name": "o/new"}, "/repos/o/old/pulls/1": pr_body("o/new"),
               # a public name whose PR answer is about a private base repo
               "/repos/o/mixed": {"private": False, "full_name": "o/mixed"}, "/repos/o/mixed/pulls/1": pr_body("o/priv", True)}

    def get(path):
        calls.append(path)
        return answers.get(path)
    monkeypatch.setattr(effects, "github_get", get)
    return calls


def test_the_server_token_answers_only_for_public_repos(github):
    pub = remote.verify_report({"text": "Merged. `⚓ pr:o/pub#1=open`", "fetch": False})[0]
    assert pub["predicate"]["anchors"][0]["status"] == "HOLDS"
    priv = remote.verify_report({"text": "Merged. `⚓ pr:o/priv#1=open`", "fetch": False})[0]["predicate"]
    got = priv["anchors"][0]
    # the same answer as for a PR that does not exist: no state, no commit, not even that the repo is there
    assert got["status"] == "UNCHECKABLE" and "state" not in got and "sha" not in got
    assert priv["outcome"] == "GAPS" and "/repos/o/priv/pulls/1" not in github


def test_a_remote_client_cannot_reach_local_capabilities():
    for extra in ({"path": "/etc/passwd"}, {"repos": ["/"]}, {"store": "/tmp/x"}, {"transcript": "/tmp/t.jsonl"},
                  {"access": "default"}):
        with pytest.raises(ValueError, match="not available on the remote server"):
            remote.verify_report({"text": "hi", **extra})


def test_a_remote_report_may_not_make_the_server_fetch_without_end():
    text = " ".join(f"“quoted words number {i} here” ([s](https://e{i}.example/a))" for i in range(101))
    with pytest.raises(ValueError, match="distinct links"):
        remote.verify_report({"text": text})


def test_a_github_anchor_cannot_name_another_api_path():
    seen = []
    got = effects.check("pr:../x#1=open", {"github": lambda path: seen.append(path) or PR_BODY})
    assert got["status"] == "UNCHECKABLE" and seen == []


# --- fetched pages --------------------------------------------------------------------------------------------------

class Endless:
    """A response whose body never ends: read() with no size would never return."""
    status, headers = 200, {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def geturl(self):
        return "https://big.example/a"

    def read(self, amt=None):
        assert amt is not None and amt > 0, "read the body without a limit"
        return b"x" * amt


def test_a_page_body_over_the_limit_is_a_failed_fetch(tmp_path, monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: Endless())
    monkeypatch.setattr(vstore, "MAX_PAGE_BYTES", 1000)
    entry = Store(tmp_path).fetch("https://big.example/a")
    assert entry["sha256"] is None and "over" in entry["error"]


def test_a_compressed_body_is_not_inflated_past_the_limit(monkeypatch):
    monkeypatch.setattr(textlayer, "MAX_DECODED_BYTES", 2**20)
    bomb = gzip.compress(b"\0" * (2 * 2**20))
    with pytest.raises(textlayer.Unreadable, match="expands past"):
        textlayer.decode_body(bomb, "gzip")
    page = b"<p>" + b"ok " * 1000 + b"</p>"
    assert textlayer.decode_body(gzip.compress(page), "gzip") == page
    assert textlayer.decode_body(gzip.compress(page) + gzip.compress(page), "gzip") == page + page


# --- local MCP -----------------------------------------------------------------------------------------------------

def test_mcp_reads_a_report_file_it_is_given_within_limits(tmp_path, monkeypatch):
    report = tmp_path / "r.md"
    report.write_text("nothing to check here\n", encoding="utf-8")
    assert mcp._report({"path": str(report)}) == ("nothing to check here\n", str(report))
    with pytest.raises(ValueError, match="not a regular file"):
        mcp._report({"path": str(tmp_path)})
    monkeypatch.setattr(mcp, "MAX_REPORT_BYTES", 10)
    with pytest.raises(ValueError, match="MiB"):
        mcp._report({"path": str(report)})
    with pytest.raises(ValueError, match="MiB"):
        mcp._report({"text": "x" * 11})


# --- review fixes: public_github identity, the call budget, decoders under it -------------------------------------

@pytest.mark.parametrize("path", [
    "/repos/o/pub/contents/secret.txt", "/repos/o/pub/pulls/1?x=1", "/repos/o/pub/pulls/1#x", "/repos/../pub/pulls/1",
    "/repos/o/../pulls/1", "/repos/o/./pulls/1", "/repos/o/pub%2F..%2Fpriv/pulls/1", "/repos/o/pub/pulls/1/../../priv",
    "/repos/о/pub/pulls/1", "/repos/o/pub/commits/abc/status", "/user/repos", "/repos/o/pub" + chr(92) + "pulls/1",
    "/repos/o/old/pulls/1", "/repos/o/mixed/pulls/1", "/repos/o/priv/pulls/1"])
def test_public_github_refuses_other_shapes_and_identities(github, path):
    assert remote.public_github(effects.github_get)(path) is None
    assert not any(c.endswith("/pulls/1") and "priv" in c for c in github)


def test_public_github_answers_for_the_repo_it_checked(github):
    get = remote.public_github(effects.github_get)
    assert get("/repos/o/pub/pulls/1") == PR_BODY and get("/repos/O/Pub/pulls/1") == PR_BODY
    assert github.count("/repos/o/pub") == 1  # one look-up per repo and call


def test_the_budget_counts_every_connection(monkeypatch):
    opened = []
    monkeypatch.setattr(remote.socket, "getaddrinfo", lambda host, port, type=None: [
        (remote.socket.AF_INET, remote.socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))])

    class Sock:
        def __init__(self, *a):
            opened.append(self)

        def settimeout(self, t):
            self.timeout = t

        def connect(self, addr):
            pass

    monkeypatch.setattr(remote.socket, "socket", Sock)
    token = vstore.BUDGET.set(vstore.Budget(2, 10**6, 60))
    try:
        remote._connect(("example.com", 443), 30)
        remote._connect(("example.com", 443))  # a redirect or a retry opens a connection like any request
        with pytest.raises(vstore.BudgetSpent, match="request budget"):
            remote._connect(("example.com", 443), 30)
    finally:
        vstore.BUDGET.reset(token)
    assert len(opened) == 2 and opened[0].timeout <= 30 and opened[1].timeout <= 60


def test_the_time_left_never_exceeds_the_budget(monkeypatch):
    """A clock that has not moved since the budget began (Windows' monotonic clock ticks coarsely) leaves
    (t0 + 60) - t0, which rounding can make 60.00000000000091: a socket timeout past the budget it is cut from."""
    monkeypatch.setattr(vstore.time, "monotonic", lambda: 8191.610680565681)
    budget = vstore.Budget(2, 10**6, 60)
    assert budget.left() <= 60 and budget.connect() <= 60


def test_a_spent_budget_makes_a_fetch_fail_before_any_network(tmp_path, monkeypatch):
    monkeypatch.setattr(urllib.request, "_opener", remote.guarded_opener())
    monkeypatch.setattr(remote.socket, "getaddrinfo", lambda *a, **k: pytest.fail("resolved a host past the budget"))
    token = vstore.BUDGET.set(vstore.Budget(0, 10**6, 60))
    try:
        entry = Store(tmp_path).fetch("https://example.com/a")
    finally:
        vstore.BUDGET.reset(token)
    assert entry["sha256"] is None and "request budget spent" in entry["error"]


def test_the_budget_counts_body_bytes_and_time():
    for budget, why in ((vstore.Budget(10, 1000, 60), "byte budget"), (vstore.Budget(10, 10**9, 0), "time budget")):
        token = vstore.BUDGET.set(budget)
        try:
            with pytest.raises(vstore.BudgetSpent, match=why):
                vstore.read_body(Endless())
        finally:
            vstore.BUDGET.reset(token)


def test_a_remote_call_past_its_time_stops_with_an_error(monkeypatch):
    monkeypatch.setattr(remote, "CALL_SECONDS", 0)
    with pytest.raises(ValueError, match="time budget"):
        remote.HANDLERS["verify_report"]({"text": "It said “a sentence long enough to check” ([x](https://e.example/a)).",
                                          "fetch": False})


def test_brotli_is_not_decompressed_under_a_budget():
    token = vstore.BUDGET.set(vstore.Budget(10, 10**6, 60))
    try:
        with pytest.raises(textlayer.Unreadable, match="not decompressed on this server"):
            textlayer.decode_body(b"\x8b\x02\x80hello\x03", "br")
    finally:
        vstore.BUDGET.reset(token)


def test_pdf_text_is_not_read_past_the_limit(monkeypatch):
    if not __import__("shutil").which("pdftotext"):
        pytest.skip("no pdftotext")
    pdf = PDF_HELLO
    assert "Hello" in textlayer.pdf_text(pdf)
    monkeypatch.setattr(textlayer, "MAX_DECODED_BYTES", 3)
    with pytest.raises(textlayer.Unreadable, match="PDF"):
        textlayer.pdf_text(pdf)


# a one-page PDF with the text "Hello PDF" (hand-written, offsets computed below)
def _pdf() -> bytes:
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length 36 >>\nstream\nBT /F1 12 Tf 20 50 Td (Hello PDF) Tj ET\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


PDF_HELLO = _pdf()
