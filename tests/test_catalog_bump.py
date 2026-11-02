"""scripts/catalog_bump.py: only the uvx pin and tagged links move, never backwards."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import catalog_bump as cb  # noqa: E402

CLINE = ('{"install": {"args": ["buddie", "--", "uvx", "buddie@2.0.5", "serve"], "notes": "run `uvx buddie@2.0.5 '
         '--version` first. Privacy: https://github.com/tsyyan/buddie/blob/v2.0.5/PRIVACY.md"}, "version": "1.0.0"}')
KILO = 'content: |\n  {"command": "uvx", "args": ["buddie@2.0.8", "serve"]}\n'


def test_pins_and_tagged_links_move_and_nothing_else():
    new, found = cb.bump(CLINE, "2.1.0")
    assert found == ["2.0.5"] and new.count("2.1.0") == 3 and '"version": "1.0.0"' in new
    assert cb.bump(KILO, "2.1.0")[0] == KILO.replace("2.0.8", "2.1.0")


def test_never_downgraded_and_never_guessed():
    with pytest.raises(ValueError, match="newer"):
        cb.bump(KILO, "2.0.7")
    with pytest.raises(ValueError, match="no buddie"):
        cb.bump('{"args": ["serve"]}', "2.1.0")


def test_cli_writes_reports_and_checks(tmp_path, capsys):
    f = tmp_path / "MCP.yaml"
    f.write_text(KILO, encoding="utf-8")
    assert cb.main([str(f), "2.1.0", "--check"]) == 1 and "2.0.8" in f.read_text()
    assert cb.main([str(f), "2.1.0"]) == 0 and "buddie@2.1.0" in f.read_text()
    assert cb.main([str(f), "2.1.0"]) == 0 and "already 2.1.0" in capsys.readouterr().out
    assert cb.main([str(f), "2.1"]) == 2


def test_the_catalogs_named_are_the_two_prs():
    assert {k: v[2] for k, v in cb.CATALOGS.items()} == {"cline": "cline/marketplace",
                                                        "kilo": "Kilo-Org/kilo-marketplace"}
