"""buddie.toml for the hook (0.8, NEXT №93, audit/20 §3.2–3.3): a level per class of claims, and the intro mode.

[gates] sets each class to "block" (the text goes back to the model), "warn" (it leaves, and the person sees what
the gate would have said, as a systemMessage) or "off" (not checked):

  anchors   a broken anchor (path@commit, path#sha, pr:, ci:, run:)          default block
  quotes    a quote not on its source                                        default block
  final     a final answer with no anchor, or a count line without one       default block
  prose     work claimed in prose with no anchor on the line                 default warn
  numbers   a number of a cited sentence not in its source                   default warn
  work      a claim about the work queue that does not hold ([mandate])      default block
  summary   a Stop returned once for the summary of the subagents' results   default off
  promises  a Stop returned for a promise whose condition holds              default off

BUDDIE_GATES="prose=block,summary=block" overrides the file (per class). A project without buddie.toml gets the
defaults.

[intro] finals = N (what `buddie init` writes): until N final answers have passed since the last false return was
reported (`buddie intro --false`), nothing is returned: each would-be return is a warning that says what it would
have returned. `buddie enforce` ends the intro at once. The count is kept per buddie.toml in $BUDDIE_INTRO, default
~/.cache/buddie/intro.json.

[journal] text = false (the default, NEXT №104): the hook's journal keeps receipts only (time, tool, counts,
verdicts, exit code, the sha256 of the text), never words of the conversation. A promise line keeps its kind, row,
condition and the sha256 of its sentence, not the sentence; a choice line keeps the hashes of the steps the person
picked and the queue rows of a typed answer, not the questions, options or answer. text = true keeps those words
(lab's dogfood); BUDDIE_JOURNAL_TEXT=1 or 0 overrides the file.
"""
from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

CONFIG = "buddie.toml"
LEVELS = ("block", "warn", "off")
DEFAULTS = {"anchors": "block", "quotes": "block", "final": "block", "prose": "warn", "numbers": "warn",
            "work": "block", "summary": "off", "promises": "off"}
INIT_FINALS = 20

TEMPLATE = f"""# buddie config (buddie init). Each class of claims is "block", "warn" or "off".
[gates]
anchors = "block"   # a broken anchor: path@commit, path#sha256, pr:, ci:, run:
quotes = "block"    # a quote not on its source
final = "block"     # a final answer with no anchor, or a count line without one
prose = "warn"      # "merged", "tests passed" in prose with no anchor on the line
numbers = "warn"    # a number of a cited sentence not in its source
summary = "off"     # return a Stop once for the summary of the subagents' results
promises = "off"    # return a Stop for a promise whose condition holds

# The journal keeps receipts only (counts, verdicts, hashes), no words of the conversation; true keeps promise
# sentences and choice cards in it.
[journal]
text = false

# Intro mode: nothing is returned until this many final answers have passed without a false return; each
# would-be return is a warning. Report a false return with `buddie intro --false`; end the intro with `buddie enforce`.
[intro]
finals = {INIT_FINALS}
"""


def find(repos: list[Path]) -> Path | None:
    for repo in repos:
        if (repo / CONFIG).is_file():
            return repo / CONFIG
    return None


def load(path: Path | None) -> dict:
    if path is None:
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def of_event(event: dict) -> tuple[Path | None, dict]:
    from buddie.promises import repos_of
    path = find(repos_of(event))
    return path, load(path)


def levels(cfg: dict) -> dict[str, str]:
    out = dict(DEFAULTS)
    for k, v in (cfg.get("gates") or {}).items():
        if k in out and v in LEVELS:
            out[k] = v
    for pair in os.environ.get("BUDDIE_GATES", "").split(","):
        k, _, v = pair.strip().partition("=")
        if k in out and v.strip() in LEVELS:
            out[k] = v.strip()
    return out


def numbers_mode(level: str) -> str:
    """The verify mode a numbers level needs: a warning is a blocking item demoted by the gate."""
    return {"block": "fail", "warn": "fail", "off": "off"}[level]


def classify(item: str) -> str | None:
    """The class of one blocking item of the gate (verify's blocking strings, hook.unbacked, hook.prose_claims)."""
    if item.startswith("quote "):
        return "quotes"
    if item.startswith("anchor line "):
        return "anchors"
    if item.startswith(("final answer has no anchor", "number without anchor")):
        return "final"
    if item.startswith("number "):
        return "numbers"
    if item.startswith("work claimed in prose"):
        return "prose"
    if " line " in item.split(":", 1)[0]:
        return "work"
    return None  # the context gate and anything new: always block


def journal_text(cfg: dict) -> bool:
    """Whether the journal may keep words of the conversation (promise sentences, choice cards); default no."""
    env = os.environ.get("BUDDIE_JOURNAL_TEXT")
    if env in ("0", "1"):
        return env == "1"
    return (cfg.get("journal") or {}).get("text") is True


def _intro_file() -> Path | None:
    target = os.environ.get("BUDDIE_INTRO", str(Path.home() / ".cache" / "buddie" / "intro.json"))
    return None if target in ("", "0") else Path(target)


def _intro_state() -> dict:
    f = _intro_file()
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f and f.is_file() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(state: dict) -> None:
    f = _intro_file()
    if f is None:
        return
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    except OSError:
        pass


def _key(path: Path) -> str:
    return str(path.resolve())


def intro(path: Path | None, cfg: dict) -> dict | None:
    """The intro of this buddie.toml while it lasts: {finals, seen}; None once enforced or with no [intro]."""
    n = (cfg.get("intro") or {}).get("finals")
    if path is None or not isinstance(n, int) or n <= 0:
        return None
    mine = _intro_state().get(_key(path), {})
    if mine.get("enforced") or mine.get("seen", 0) >= n:
        return None
    return {"finals": n, "seen": mine.get("seen", 0)}


def count_final(path: Path) -> int:
    state = _intro_state()
    mine = state.setdefault(_key(path), {})
    mine["seen"] = mine.get("seen", 0) + 1
    _save(state)
    return mine["seen"]


def false_return(path: Path) -> None:
    state = _intro_state()
    mine = state.setdefault(_key(path), {})
    mine["seen"], mine["false"] = 0, mine.get("false", 0) + 1
    _save(state)


def enforce(path: Path) -> None:
    state = _intro_state()
    state.setdefault(_key(path), {})["enforced"] = True
    _save(state)


def init(repo: Path) -> Path:
    path = repo / CONFIG
    if path.exists():
        raise FileExistsError(path)
    path.write_text(TEMPLATE, encoding="utf-8")
    return path
