"""Text that crosses a process or a file boundary is UTF-8 whatever the locale: a Russian Windows (cp1251) or a
Western one (cp1252, CI's) must read what git and the snapshot store wrote. Each case failed on such a locale."""
from __future__ import annotations

import locale
import subprocess

import pytest

from buddie import anchors, promises
from buddie.verbatim.store import Store

# not in cp1251 nor in cp1252 (⚓, CJK), and UTF-8 bytes neither decodes (И is d0 98, Ё is d0 81)
WORDS = "⚓ 東京 Исправлено ИЁ"


def test_the_snapshot_index_is_utf8(tmp_path):
    store = Store(tmp_path / "s")
    store.add("https://例え.jp/ページ", b"x", error=WORDS)
    assert (tmp_path / "s" / "index.json").read_bytes().decode("utf-8")  # written as UTF-8
    assert Store(tmp_path / "s").latest("https://例え.jp/ページ")["error"] == WORDS


@pytest.mark.skipif(locale.getpreferredencoding(False).lower().replace("-", "") == "utf8",
                    reason="the locale is UTF-8: an older index was UTF-8 too")
def test_an_index_an_older_version_wrote_in_the_locale_is_still_read(tmp_path):
    root = tmp_path / "s"
    root.mkdir()
    enc = locale.getpreferredencoding(False)
    word = next(w for w in ("été", "Иван", "ÄÖÜ") if _encodes(w, enc))  # whatever this locale has
    legacy = '{"https://e.example/": [{"sha256": null, "error": "%s"}]}' % word
    (root / "index.json").write_bytes(legacy.encode(enc))
    assert Store(root).latest("https://e.example/")["error"] == word


def _encodes(word: str, enc: str) -> bool:
    try:
        word.encode(enc)
        return True
    except UnicodeEncodeError:
        return False


def test_a_repo_under_a_non_ascii_path_is_found(tmp_path):
    repo = tmp_path / "Иван" / "проект"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    assert [p.resolve() for p in anchors.find_repos(repo)] == [repo.resolve()]


def test_a_commit_subject_in_cyrillic_does_not_break_the_launch_gate(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.org"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", WORDS], check=True)
    monkeypatch.setenv("BUDDIE_GITHUB", "1")
    # not a merge of a PR: no verdict, and no UnicodeDecodeError on the way to that answer
    assert promises.comment_verdict(1, "HEAD", {"repo": str(repo)}, {"comment": "automerge"}) is None
