"""PR #26: the parts the hook calls no longer import the hook; config says where each setting comes from; the gate's
classes match the typed findings; the hook's behaviour at each outcome is pinned."""
from __future__ import annotations

import ast
import hashlib
import io
import itertools
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from buddie import anchors, config, core, hook
from buddie.config import Source
from buddie.verbatim.store import Store
from buddie.verify import assess

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = {"hook", "cli", "__main__", "mcp", "remote"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("buddie"):
            out |= {a.name for a in n.names} if n.module == "buddie" else {n.module.split(".")[1]}
        elif isinstance(n, ast.Import):
            out |= {a.name.split(".")[1] for a in n.names if a.name.startswith("buddie.")}
    return out


def test_no_shared_part_imports_an_adapter():
    """Only the adapters (Claude Code hook, CLI, MCP servers) may import an adapter; the hook is imported by no one
    but the CLI that runs it."""
    for path in sorted((ROOT / "buddie").glob("*.py")):
        if path.stem in ADAPTERS:
            continue
        assert not _imports(path) & ADAPTERS, path.name
    assert {p.stem for p in (ROOT / "buddie").glob("*.py") if "hook" in _imports(p)} == {"cli"}


def test_importing_the_shared_parts_reads_and_writes_no_file():
    script = """
import sys
opened = []
def audit(event, args):
    if event == "open" and isinstance(args[0], str) and not args[0].endswith((".py", ".pyc")):
        opened.append(args[0])
sys.addaudithook(audit)
import buddie.core, buddie.findings, buddie.config, buddie.logbook, buddie.event, buddie.verify, buddie.hook
print(opened)
"""
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=ROOT, check=True).stdout
    assert out.strip() == "[]"


# --- settings: same values as before, and their sources -----------------------------------------------------------

def _levels_before(cfg, configured, env):
    """config.levels as of #25, for comparison."""
    out = dict(config.DEFAULTS if configured else config.ZERO_CONFIG)
    for k, v in (cfg.get("gates") or {}).items():
        if k in out and v in config.LEVELS:
            out[k] = v
    for pair in env.split(","):
        k, _, v = pair.strip().partition("=")
        if k in out and v.strip() in config.LEVELS:
            out[k] = v.strip()
    return out


@pytest.mark.parametrize("env", ["", "quotes=off", "prose=block, final=warn", "nonsense=block,quotes=maybe"])
def test_levels_resolve_as_before(env, monkeypatch):
    monkeypatch.setenv("BUDDIE_GATES", env)
    for configured, quotes, prose, extra in itertools.product((True, False), (None, "warn", "off", "bad"),
                                                              (None, "block"), (None, {"unknown": "off"})):
        gates = {k: v for k, v in (("quotes", quotes), ("prose", prose)) if v} | (extra or {})
        cfg = {"gates": gates}
        assert config.levels(cfg, configured) == _levels_before(cfg, configured, env)


def test_each_level_names_its_source(monkeypatch):
    monkeypatch.setenv("BUDDIE_GATES", "prose=block")
    got = config.resolve_levels({"gates": {"quotes": "off", "prose": "off"}})
    assert got["quotes"] == config.Setting("off", Source.REPO)
    assert got["prose"] == config.Setting("block", Source.USER)  # the person's environment wins over the repo
    assert got["anchors"] == config.Setting("block", Source.DEFAULT)
    assert config.TRUST[Source.USER] > config.TRUST[Source.CALL] > config.TRUST[Source.DEFAULT] > config.TRUST[Source.REPO]


@pytest.mark.parametrize("env, option, repo, want", [
    (None, None, None, ("on", Source.DEFAULT)), (None, None, False, ("off", Source.REPO)),
    (None, "false", None, ("off", Source.USER)), ("1", "false", False, ("on", Source.USER)),
    (None, "true", False, ("on", Source.USER)), ("0", None, True, ("off", Source.USER))])
def test_transcript_reading_conflicts(env, option, repo, want, monkeypatch):
    for name, value in (("BUDDIE_TRANSCRIPT", env), ("CLAUDE_PLUGIN_OPTION_READ_TRANSCRIPT", option)):
        monkeypatch.delenv(name, raising=False) if value is None else monkeypatch.setenv(name, value)
    cfg = {} if repo is None else {"transcript": {"read": repo}}
    got = config.resolve_transcript(cfg)
    assert (got.value, got.source) == want and config.reads_transcript(cfg) == (want[0] == "on")


# --- the hook: one Stop at each outcome, and the checks that are off ----------------------------------------------

URL = "https://news.example.org/outage"
PAGE = ("<p>" + "Background paragraph about the service. " * 40 + "</p><p>The company said the outage began at 14:59 "
        "UTC and was resolved within two hours.</p>").encode()
HELLO = hashlib.sha256(b"hello\n").hexdigest()


@pytest.fixture
def session(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "data.txt").write_bytes(b"hello\n")
    Store(tmp_path / "store").add(URL, PAGE, content_type="text/html")
    for k in ("BUDDIE_FINAL", "BUDDIE_GATES", "BUDDIE_TRANSCRIPT", "CLAUDE_PLUGIN_OPTION_READ_TRANSCRIPT", "BUDDIE_NUMBERS"):
        monkeypatch.delenv(k, raising=False)
    for k, v in (("BUDDIE_FETCH", "0"), ("BUDDIE_GITHUB", "0"), ("BUDDIE_LOG", str(tmp_path / "hook.jsonl")),
                 ("BUDDIE_STATE", str(tmp_path / "pending")), ("BUDDIE_REPOS", str(repo)),
                 ("VERBATIM_STORE", str(tmp_path / "store")), ("BUDDIE_SHARED_LOG", "0"), ("BUDDIE_INTRO", "0")):
        monkeypatch.setenv(k, v)

    def stop(text):
        err = io.StringIO()
        code = hook.run({"hook_event_name": "Stop", "session_id": "s", "cwd": str(repo),
                         "last_assistant_message": text}, err, io.StringIO())
        line = json.loads((tmp_path / "hook.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        return code, line, err.getvalue()
    return repo, stop


GOOD = f"The vendor wrote that “the outage began at 14:59 UTC and was resolved within two hours” ([r]({URL}))."
BAD = GOOD.replace("14:59", "14:58")


def test_the_hook_at_each_outcome(session, monkeypatch):
    _, stop = session
    code, line, _ = stop(f"Done. `⚓ data.txt#{HELLO[:12]}`")
    assert (code, line["outcome"]) == (0, "PASS")
    code, line, err = stop(f"Done. `⚓ data.txt#{'0' * 12}`")
    assert (code, line["outcome"]) == (2, "FAIL") and "data.txt" in err
    code, line, _ = stop(f"Done. `⚓ gone.txt#{HELLO[:12]}`")
    assert (code, line["outcome"]) == (0, "GAPS")
    # UNKNOWN: a status no checker returns. receipt-v0 says GAPS, and the gate lets the answer out
    monkeypatch.setattr(anchors, "check_one", lambda a, repos, cache, ctx=None: {"anchor": a, "status": "PROBABLY"})
    code, line, _ = stop(f"Done. `⚓ data.txt#{HELLO[:12]}`")
    assert (code, line["outcome"]) == (0, "GAPS")


def test_the_outcome_is_not_the_gates_decision(session, monkeypatch):
    """A FAIL the gate does not block: anchors at warn. The outcome stays FAIL; the decision is the gate's."""
    repo, stop = session
    (repo / "buddie.toml").write_text('[gates]\nanchors = "warn"\nfinal = "off"\n', encoding="utf-8")
    code, line, _ = stop(f"Done. `⚓ data.txt#{'0' * 12}`")
    assert (code, line["outcome"], line.get("warned")) == (0, "FAIL", 1)


@pytest.mark.parametrize("gates, text", [("quotes=off", BAD), ("anchors=off", f"Done. `⚓ data.txt#{'0' * 12}`")])
def test_a_check_turned_off_lets_its_finding_out_but_the_outcome_says_it(session, monkeypatch, gates, text):
    _, stop = session
    monkeypatch.setenv("BUDDIE_GATES", gates)
    code, line, _ = stop(text)
    assert (code, line["outcome"]) == (0, "FAIL")


# --- the agent's buddie.toml can lower a gate today; the model says so --------------------------------------------

def test_repo_config_lowers_a_gate_and_influence_reports_it(session):
    repo, stop = session
    text = f"{BAD} `⚓ data.txt#{HELLO[:12]}`"  # an anchor that holds, so the final rule has nothing to say
    assert stop(text)[0] == 2  # no buddie.toml: a quote not on its page goes back
    (repo / "buddie.toml").write_text('[gates]\nquotes = "off"\n', encoding="utf-8")
    code, line, _ = stop(text)
    assert (code, line["outcome"]) == (0, "FAIL")  # reproduced: the file the agent can write let it out
    weak = [i for i in config.influence(config.load(repo / "buddie.toml")) if i.weakens]
    assert [(i.setting, i.without, i.with_repo) for i in weak] == [("gates.quotes", "block", "off")]


def test_influence_lists_every_repo_lever(monkeypatch):
    for k in ("BUDDIE_FINAL", "BUDDIE_GATES", "BUDDIE_TRANSCRIPT", "CLAUDE_PLUGIN_OPTION_READ_TRANSCRIPT",
              "BUDDIE_JOURNAL_TEXT"):
        monkeypatch.delenv(k, raising=False)
    cfg = {"gates": {"anchors": "warn", "final": "block"}, "intro": {"finals": 50}, "transcript": {"read": False},
           "mandate": {"final_mark": "(?!)"}, "journal": {"text": True}}
    got = {i.setting: i.weakens for i in config.influence(cfg)}
    assert got == {"gates.anchors": True, "gates.final": False, "gates.prose": False, "gates.context": False,
                   "intro.finals": True, "transcript.read": True, "mandate.final_mark": True, "journal.text": True}
    monkeypatch.setenv("BUDDIE_GATES", "anchors=block")  # the person's environment holds: no longer a repo lever
    assert "gates.anchors" not in {i.setting for i in config.influence(cfg)}


# --- the gate's classes from the words and from the findings agree ------------------------------------------------

def test_classify_agrees_with_the_finding_checks(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "data.txt").write_bytes(b"hello\n")
    Store(tmp_path / "store").add(URL, PAGE, content_type="text/html")
    texts = [BAD, f"`⚓ data.txt#{'0' * 12}` `⚓ ../x#{'0' * 12}` `⚓ not an anchor`",
             f"It is worth $9.9 billion ([z]({URL})). {BAD}", f"`⚓ data.txt@{'b' * 7}` `⚓ x.count=3`"]
    seen = Counter()
    for text in texts:
        receipt, found, _ = assess(text, store=str(tmp_path / "store"), fetch=False, repos=[repo], numbers="fail")
        blocked = [f for f in found if core.Policy(True).decide(f) is core.Decision.BLOCK]
        words = Counter(config.classify(i) for i in receipt["predicate"]["blocking"])
        assert words == Counter(config.CLASS_OF_CHECK[f.check] for f in blocked), text
        seen += words
    assert set(seen) == {"quotes", "anchors", "numbers"}
    # a work claim's item, as mandate writes it
    assert config.classify("done line 4: row №3 is not done") == config.CLASS_OF_CHECK[core.Check.WORK_CLAIM]
