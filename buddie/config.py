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
  context   a reply or a subagent launch past the context limit (context.py)  default block

A project without buddie.toml gets the defaults with final, prose and context off (ZERO_CONFIG): someone who only
installed the plugin is returned an answer only for what is false, a quote not on its page or an anchor that does not
hold, not for what is merely unanchored. `buddie init` writes the full defaults. BUDDIE_GATES="prose=block,
summary=block" overrides either (per class).

[intro] finals = N (what `buddie init` writes): until N final answers have passed since the last false return was
reported (`buddie intro --false`), nothing is returned: each would-be return is a warning that says what it would
have returned. `buddie enforce` ends the intro at once. The count is kept per buddie.toml in $BUDDIE_INTRO, default
~/.cache/buddie/intro.json.

[journal] text = false (the default, NEXT №104): the hook's journal keeps receipts only (time, tool, counts,
verdicts, exit code, the sha256 of the text), never words of the conversation. A promise line keeps its kind, row,
condition and the sha256 of its sentence, not the sentence; a choice line keeps the hashes of the steps the person
picked and the queue rows of a typed answer, not the questions, options or answer. text = true keeps those words
(lab's dogfood); BUDDIE_JOURNAL_TEXT=1 or 0 overrides the file.

Where a setting comes from (Source), most trusted first: TRANSPORT (what a server or transport imposes: the remote
server's dropped arguments and Budget), USER (the person's environment, BUDDIE_*, and plugin settings,
CLAUDE_PLUGIN_OPTION_*: outside the repo), CALL (the arguments of one CLI or MCP call: a person at a CLI, or the
agent itself through an MCP tool), DEFAULT (buddie's own), REPO (buddie.toml in the repo under check, which the agent
can edit). Today REPO overrides DEFAULT in both directions; `influence()` says where it weakens what would apply
without the file, the rule a later release can enforce (a less trusted source never widens what a more trusted one
set). Nothing here changes a value.
"""
from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from buddie.core import Check

CONFIG = "buddie.toml"
LEVELS = ("block", "warn", "off")
DEFAULTS = {"anchors": "block", "quotes": "block", "final": "block", "prose": "warn", "numbers": "warn",
            "work": "block", "summary": "off", "promises": "off", "context": "block"}
# no buddie.toml: return only what is false (1.1, before the plugin directory); unanchored answers, prose about work
# and the context rule are the project's choice, made with `buddie init`
ZERO_CONFIG = {**DEFAULTS, "final": "off", "prose": "off", "context": "off"}
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
context = "block"   # a reply or a subagent launch past the context limit (BUDDIE_CONTEXT_LIMIT, default 200k)

# The journal keeps receipts only (counts, verdicts, hashes), no words of the conversation; true keeps promise
# sentences and choice cards in it.
[journal]
text = false

# Intro mode: nothing is returned until this many final answers have passed without a false return; each
# would-be return is a warning. Report a false return with `buddie intro --false`; end the intro with `buddie enforce`.
[intro]
finals = {INIT_FINALS}
"""


class Source(str, Enum):
    TRANSPORT = "transport"
    USER = "user"
    CALL = "call"
    DEFAULT = "default"
    REPO = "repo"


TRUST = {Source.TRANSPORT: 4, Source.USER: 3, Source.CALL: 2, Source.DEFAULT: 1, Source.REPO: 0}
STRENGTH = {"block": 2, "warn": 1, "off": 0}


@dataclass(frozen=True)
class Setting:
    value: str
    source: Source


@dataclass(frozen=True)
class Influence:
    """Where the repo's buddie.toml makes a check weaker (or, `weakens` False, stronger) than it would be without it."""
    setting: str
    without: object
    with_repo: object
    weakens: bool


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
    from buddie.event import repos_of
    path = find(repos_of(event))
    return path, load(path)


def final_mark(event: dict) -> str | None:
    """The regex of a final answer: BUDDIE_FINAL, else final_mark of the first buddie.toml [mandate] around the
    session that sets one, else None (the plugin's default, 0.7.4: the last message at Stop is the final answer)."""
    env = os.environ.get("BUDDIE_FINAL")
    if env is not None:
        return env
    from buddie.event import repos_of
    for repo in repos_of(event):
        path = repo / CONFIG
        if path.is_file():
            try:
                mark = tomllib.loads(path.read_text(encoding="utf-8")).get("mandate", {}).get("final_mark")
            except (OSError, tomllib.TOMLDecodeError):
                continue
            if mark is not None:
                return mark
    return None


def resolve_levels(cfg: dict, configured: bool = True) -> dict[str, Setting]:
    """The level of each class and where it comes from: the defaults (ZERO_CONFIG when the project has no
    buddie.toml), then the file's [gates] (REPO), then BUDDIE_GATES (USER)."""
    out = {k: Setting(v, Source.DEFAULT) for k, v in (DEFAULTS if configured else ZERO_CONFIG).items()}
    for k, v in (cfg.get("gates") or {}).items():
        if k in out and v in LEVELS:
            out[k] = Setting(v, Source.REPO)
    for pair in os.environ.get("BUDDIE_GATES", "").split(","):
        k, _, v = pair.strip().partition("=")
        if k in out and v.strip() in LEVELS:
            out[k] = Setting(v.strip(), Source.USER)
    return out


def levels(cfg: dict, configured: bool = True) -> dict[str, str]:
    """The level of each class (resolve_levels without the sources)."""
    return {k: s.value for k, s in resolve_levels(cfg, configured).items()}


def influence(cfg: dict) -> list[Influence]:
    """What the repo's buddie.toml changes against the same session without it (the fresh-install levels, the
    person's environment applied to both). The settings it can weaken today: a gate's level, the intro mode (every
    return a warning), reading the transcript (run: anchors and the context gate), and the final mark (a regex no
    answer matches turns the final rule off); it can also widen what the journal keeps (the conversation's words)."""
    out = []
    without, with_repo = levels({}, configured=False), levels(cfg, configured=True)
    for k in DEFAULTS:
        if with_repo[k] != without[k]:
            out.append(Influence(f"gates.{k}", without[k], with_repo[k], STRENGTH[with_repo[k]] < STRENGTH[without[k]]))
    if isinstance(n := (cfg.get("intro") or {}).get("finals"), int) and n > 0:
        out.append(Influence("intro.finals", None, n, True))
    if reads_transcript({}) and not reads_transcript(cfg):
        out.append(Influence("transcript.read", True, False, True))
    if os.environ.get("BUDDIE_FINAL") is None and "final_mark" in (cfg.get("mandate") or {}):
        out.append(Influence("mandate.final_mark", None, cfg["mandate"]["final_mark"], True))
    if not journal_text({}) and journal_text(cfg):
        out.append(Influence("journal.text", False, True, True))
    return out


# The gate class of each check's finding (core.Check): what classify() reads from the blocking item's words.
# tests/test_layers.py holds the two equal, so the gate can move from the words to the findings.
CLASS_OF_CHECK = {Check.QUOTE: "quotes", Check.NUMBER: "numbers", Check.WORK_CLAIM: "work",
                  **{c: "anchors" for c in Check if c.name.endswith("_ANCHOR")}}


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
    if item.startswith("context "):
        return "context"
    if item.startswith("number "):
        return "numbers"
    if item.startswith("work claimed in prose"):
        return "prose"
    if " line " in item.split(":", 1)[0]:
        return "work"
    return None  # anything new: always block


def reads_transcript(cfg: dict) -> bool:
    """Whether the hook may open the session transcript (run: anchors, the context gate, decision cards). Off: the
    final answer comes from the Stop event's last_assistant_message, run: anchors are UNCHECKABLE. BUDDIE_TRANSCRIPT=0
    or 1, then the plugin option read_transcript (CLAUDE_PLUGIN_OPTION_READ_TRANSCRIPT), then [transcript] read in
    buddie.toml; default on."""
    return resolve_transcript(cfg).value == "on"


def resolve_transcript(cfg: dict) -> Setting:
    """reads_transcript with its source: BUDDIE_TRANSCRIPT and the plugin option are the person's (USER), [transcript]
    read the repo's (REPO), else the default (on)."""
    for name in ("BUDDIE_TRANSCRIPT", "CLAUDE_PLUGIN_OPTION_READ_TRANSCRIPT"):
        value = os.environ.get(name, "").strip().lower()
        if value in ("0", "false", "no", "off"):
            return Setting("off", Source.USER)
        if value in ("1", "true", "yes", "on"):
            return Setting("on", Source.USER)
    read = (cfg.get("transcript") or {}).get("read")
    if read is False:
        return Setting("off", Source.REPO)
    return Setting("on", Source.REPO if read is True else Source.DEFAULT)


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
