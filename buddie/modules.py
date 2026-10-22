"""The verification modules: which checks buddie has, grouped by the evidence they need, under stable names.

A module is a fixed part of buddie, not a plugin: the registry below is the whole list, nothing is loaded from a
path, an entry point or a config file, and no third-party code runs. A module declares
  id        a stable name (CLI --modules, MCP `modules`, the docs), never reused for something else
  checks    the core.Check kinds it produces: every Check belongs to exactly one module (tests/test_modules.py)
  inputs    what it reads to judge them, for a caller deciding what to hand in
and nothing else: the checking itself stays where it was (verbatim, anchors.py, effects.py, mandate.py), called by
verify.assess, which skips the checks of a module that is not selected and says so in its Coverage.

Selection is explicit and checked: an unknown id is an error (UnknownModule), never ignored; the order of results
is the registry's whatever order the ids came in; no selection means every module, which is what verify did before
modules existed. The hook always runs every module: what blocks there is set per gate class (config.py) under the
protected policy's floors, not by switching modules off.

Nothing here names an agent provider or a transport. A module's inputs are plain values (a store, repos, a GitHub
GET function, a transcript path); which agent wrote the text and how it arrived is the caller's business.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from buddie import core
from buddie.core import Check


class UnknownModule(ValueError):
    pass


@dataclass(frozen=True)
class Module:
    id: str
    checks: tuple[Check, ...]
    inputs: tuple[str, ...]
    summary: str


REGISTRY: tuple[Module, ...] = (
    Module("sources", (Check.QUOTE, Check.NUMBER), ("store", "fetch"),
           "quotations and the numbers of cited sentences, against snapshots of the pages they link"),
    Module("github", (Check.FILE_ANCHOR, Check.COMMIT_ANCHOR, Check.FACT_ANCHOR, Check.PR_ANCHOR, Check.CI_ANCHOR,
                      Check.OTHER_ANCHOR), ("repos", "github"),
           "repository and GitHub anchors: path#sha256, path@commit, fact=, pr:, ci: (and text in an anchor's place)"),
    Module("execution", (Check.RUN_ANCHOR, Check.CHOICE_ANCHOR, Check.WORK_CLAIM), ("transcript", "journal", "mandate"),
           "what the session ran and decided: run: against the transcript, choice: against the journal, work claims "
           "against the queue"),
)
IDS = tuple(m.id for m in REGISTRY)


def select(ids: Iterable[str] | None = None) -> tuple[Module, ...]:
    """The modules named, in registry order; None: all of them. An empty selection or an unknown id is an error."""
    if ids is None:
        return REGISTRY
    wanted = {i.strip() for i in ids if i and i.strip()}
    if unknown := sorted(wanted - set(IDS)):
        raise UnknownModule(f"unknown module(s): {', '.join(unknown)}; known: {', '.join(IDS)}")
    if not wanted:
        raise UnknownModule(f"no module selected; known: {', '.join(IDS)}")
    return tuple(m for m in REGISTRY if m.id in wanted)


def parse(spec: str | None) -> tuple[Module, ...]:
    """A comma list of ids (CLI --modules), None or "all": every module."""
    return REGISTRY if spec in (None, "all") else select(spec.split(","))


def module_of(check: Check) -> Module:
    for m in REGISTRY:
        if check in m.checks:
            return m
    raise LookupError(f"no module provides {getattr(check, 'value', check)!r}")


def checks(selected: Iterable[Module]) -> frozenset[Check]:
    return frozenset(c for m in selected for c in m.checks)


@dataclass(frozen=True)
class ModuleResult:
    module: str
    selected: bool
    findings: tuple[core.Finding, ...]
    outcome: core.Outcome | None      # core.outcome of its findings; None when it was not selected


def results(found: Iterable[core.Finding], selected: Iterable[Module],
            policy: core.Policy = core.Policy()) -> tuple[ModuleResult, ...]:
    """Each registered module's findings and outcome, in registry order. A finding of a check no module provides is
    an error, not dropped."""
    found, on = list(found), {m.id for m in selected}
    by: dict[str, list[core.Finding]] = {m.id: [] for m in REGISTRY}
    for f in found:
        by[module_of(f.check).id].append(f)
    return tuple(ModuleResult(m.id, m.id in on, tuple(by[m.id]),
                              core.outcome(by[m.id], policy=policy) if m.id in on else None) for m in REGISTRY)
