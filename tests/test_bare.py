"""NEXT №97: the bare anchor (⚓ without backticks) and no ready anchor from a call unrelated to the claim.

E017 (experiments/E017-subtle-traps): every report with a return got a false «final answer has no anchor» while it
carried anchors in the form of the SKILL.md table, only without backticks, and was offered «ready anchors» from
a file write (`cat > REPORT.md <<'EOF'`) or the SubagentHandback call itself.
"""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
from pathlib import Path

import pytest

from buddie import anchors, hook, suggest
from buddie.anchors import ANCHOR

GATE = Path(__file__).resolve().parents[3] / "experiments" / "E017-subtle-traps" / "results" / "raw" / "gate"
NO_ANCHOR = "final answer has no anchor"
# the rounds E017 returned for «no anchor» though the report had ⚓ (results/raw/gate/<round>.json)
FALSE_RETURNS = ["001cb9.0", "076000.0", "076000.1", "1b5dca.0", "4f69ef.0", "7ce07f.0", "80108e.0", "994c1b.0",
                 "994c1b.1", "b64e30.0", "e46a22.0", "e9a65f.0", "f61511.0", "f61511.1"]
e017 = pytest.mark.skipif(not GATE.is_dir(), reason="outside lab")


def test_bare_forms():
    line = ("Я закоммитил company.md ⚓ company.md@7c30a8bc64cbcdbd7bcb1b6c6170d7b839492d35 "
            "⚓ run:cd /w && ls -la && git log --oneline | head => nstruments was founded in 1987.</p>")
    assert ANCHOR.findall(line) == ["company.md@7c30a8bc64cbcdbd7bcb1b6c6170d7b839492d35",
                                    "run:cd /w && ls -la && git log --oneline | head => nstruments was founded in 1987.</p>"]
    assert ANCHOR.findall("Файл (⚓ a.md#0123456789ab).") == ["a.md#0123456789ab"]
    assert ANCHOR.findall("Тесты прошли. ⚓ run:./ci.sh => 2 passed in 0.00s.") == ["run:./ci.sh => 2 passed in 0.00s"]
    assert ANCHOR.findall("⚓ e002.claims=115, ⚓ pr:o/r#5=merged@abcdef1; ⚓ ci:o/r@abcdef1=success") == [
        "e002.claims=115", "pr:o/r#5=merged@abcdef1", "ci:o/r@abcdef1=success"]
    # a table row: run: ends at the cell's border
    assert ANCHOR.findall("| 3 | ⚓ run:pytest -q => 3 passed | ок |") == ["run:pytest -q => 3 passed"]
    # bare next to backticked, in line order
    assert ANCHOR.findall("`⚓ x.md#0123456789ab` и ⚓ y.md@abcdef0") == ["x.md#0123456789ab", "y.md@abcdef0"]
    assert ANCHOR.sub(" ", "файл ⚓ y.md@abcdef0 готов") == "файл   готов"


def test_bare_sign_without_an_anchor_is_not_one():
    """The sign in prose, inside code, or before the table's placeholders (a gate's return quoted back) claims
    nothing: a bare anchor counts only in an anchor's own form."""
    quoted = ("final answer has no anchor: anchor its result (⚓ path@commit, ⚓ path#sha256, ⚓ fact=value, "
              "⚓ pr:OWNER/REPO#N=merged, ⚓ ci:OWNER/REPO@SHA=success or ⚓ run:CMD => OUTPUT)")
    for text in (quoted, "⚓ я подумал и решил", "знак `⚓ ` в коде", "all `⚓` anchors in `markdown` hold",
                 "⚓ run:<команда> => <вывод>", "⚓ README.md"):
        assert ANCHOR.findall(text) == [] and not ANCHOR.search(text), text


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    (path / "data.txt").write_bytes(b"hello\n")
    git = ["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(git + ["add", "."], check=True)
    subprocess.run(git + ["commit", "-qm", "init"], check=True)
    commit = subprocess.run(git + ["rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    return path, commit, hashlib.sha256(b"hello\n").hexdigest()


def test_bare_anchor_is_checked(repo):
    path, commit, sha = repo
    text = f"Файл ⚓ data.txt#{sha[:12]}, коммит ⚓ data.txt@{commit[:7]}, старый ⚓ data.txt#{'0' * 12}"
    assert [a["status"] for a in anchors.check_text(text, [path])] == ["HOLDS", "HOLDS", "BROKEN"]


@e017
@pytest.mark.parametrize("rnd", FALSE_RETURNS)
def test_e017_reports_have_anchors(rnd, tmp_path, monkeypatch):
    """Each false return of E017 again, offline: the gate now reads the report's anchors (results/regate-097.json)."""
    for k, v in {"BUDDIE_FINAL": "Итог:", "BUDDIE_LOG": "0", "BUDDIE_SHARED_LOG": "0", "BUDDIE_LESSONS": "0",
                 "BUDDIE_STATE": str(tmp_path / "state"), "BUDDIE_REPOS": str(tmp_path), "BUDDIE_GITHUB": "0",
                 "BUDDIE_FETCH": "0", "BUDDIE_GATES": "prose=block", "BUDDIE_NUMBERS": "gap",
                 "VERBATIM_STORE": str(tmp_path / "store")}.items():
        monkeypatch.setenv(k, v)
    text = (GATE / f"{rnd}.md").read_text(encoding="utf-8")
    assert NO_ANCHOR in json.loads((GATE / f"{rnd}.json").read_text(encoding="utf-8"))["text"]
    assert ANCHOR.findall(text)
    err = io.StringIO()
    hook.run({"hook_event_name": "PreToolUse", "tool_name": "SubagentHandback", "session_id": rnd,
              "cwd": str(tmp_path), "tool_input": {"message": text}}, err=err)
    assert NO_ANCHOR not in err.getvalue()


def _transcript(path, calls):
    rows = []
    for i, (name, args, out) in enumerate(calls):
        rows.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": f"toolu_{i}", "name": name, "input": args}]}})
        rows.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"toolu_{i}", "content": out}]}})
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return str(path)


def test_no_ready_anchor_from_a_file_write_or_the_handback(tmp_path):
    """E017 076000.0 and 001cb9.0: the only calls the gate found were the report's own write and its handback."""
    t = _transcript(tmp_path / "t.jsonl", [
        ("Bash", {"command": "cd /w && cat > REPORT.md <<'EOF'\nИтог: сделано\nEOF\nbuddie-verify REPORT.md"},
         "buddie PASS: quotes 2/2 found; numbers 2/2 found"),
        ("Bash", {"command": "sed -i 's/a/b/' f.py && python -m pytest -q"}, "2 passed in 0.01s"),
        ("SubagentHandback", {"message": "Отчёт исполнителя.\n\nИтог: сделано"},
         '{"success":true,"message":"Report delivered to your caller."}')])
    items = [{"kind": "final_no_anchor", "line": None, "text": ""}]
    assert suggest.ready_anchors("Сделано.\n\nИтог: сделано", items, transcript=t) == []
    bare = [{"kind": "final_bare", "line": 1, "text": "2 passed"}]
    assert suggest.ready_anchors("Тесты: 2 passed.", bare, transcript=t) == []


def test_ready_anchor_still_from_a_run(tmp_path):
    t = _transcript(tmp_path / "t.jsonl", [
        ("Bash", {"command": "cd /w && cat > a.py <<'EOF'\nx = 1\nEOF"}, ""),
        ("Bash", {"command": "python -m pytest -q"}, "2 passed in 0.01s"),
        ("SubagentHandback", {"message": "Итог: сделано"}, '{"success":true}')])
    items = [{"kind": "final_bare", "line": 1, "text": "2 passed"}]
    assert suggest.ready_anchors("Тесты: 2 passed.", items, transcript=t) == [
        "- line 1: `⚓ run:python -m pytest -q => 2 passed in 0.01s`"]


@pytest.mark.parametrize("first,writes", [
    ("cd /w && cat > REPORT.md <<'EOF'", True), ("cat <<EOF > a.txt", True), ("tee -a log <<EOF", True),
    ("sed -i 's/a/b/' f && grep b f", True), ("python -m pytest -q 2>&1 | tail -3", False),
    ("git log --oneline | head", False), ("cat REPORT.md", False), ("python - <<'EOF'", False),
    ("echo done >&2", False)])
def test_writes_file(first, writes):
    assert suggest.writes_file(first) is writes
