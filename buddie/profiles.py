"""Verification profiles: named presets of the checks buddie runs, resolved to an explicit set of modules and checks.

A profile is configuration, not an engine: it names which core.Check kinds verify.assess_selected runs, through
the same module registry (buddie/modules.py) and the same code as every other check. The four:

  developer   github, execution   repos, commits, PRs, CI, what the session ran and decided, work claims
  research    sources             quotations and the numbers of cited sentences
  complete    every module        what buddie runs without a profile
  custom      what is listed      `modules` and/or `checks`, at least one

Resolution is deterministic: the same names give the same Selection, its checks in core.Check order and its
modules in registry order, whatever order they were given in. An unknown profile, module or check is an error
naming the known ones (UnknownProfile), never a fallback. A built-in profile takes no modules or checks of its own:
listing some is an error too, so `developer` always means the same set.

What a profile is not: it grants nothing, authorizes no source and changes no provenance. A check it leaves out is
not run, and Coverage says so with the claims of that kind the text holds (verify.assess_selected): left out is
never verified. In the hook, a profile only lowers to "off" the default level of each gate class none of its checks
feed (gate_levels); buddie.toml's [gates], BUDDIE_GATES and the plugin options still set levels above it, and the
protected policy's floors above those, and a class that ends up on is checked whatever the profile said.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from buddie import modules as mods
from buddie.core import Check

BUILT_IN = {
    "developer": ("github", "execution"),
    "research": ("sources",),
    "complete": mods.IDS,
}
NAMES = (*BUILT_IN, "custom")
CHECK_IDS = tuple(c.value for c in Check)

# the gate classes a profile can switch off, and the checks that feed each (config.DEFAULTS has the others: final,
# summary, promises and context judge the answer's form and the workflow, not a module's claims). prose is work
# claimed in words: it goes with the checks that could have backed it with an anchor
CLASS_CHECKS = {
    "quotes": frozenset({Check.QUOTE}),
    "numbers": frozenset({Check.NUMBER}),
    "anchors": frozenset(c for c in Check if c.name.endswith("_ANCHOR")),
    "work": frozenset({Check.WORK_CLAIM}),
    "prose": frozenset({Check.WORK_CLAIM, Check.PR_ANCHOR, Check.CI_ANCHOR, Check.RUN_ANCHOR}),
}


class UnknownProfile(ValueError):
    pass


@dataclass(frozen=True)
class Selection:
    profile: str
    modules: tuple[mods.Module, ...]    # registry order: every module with a selected check
    checks: frozenset[Check]

    @property
    def check_ids(self) -> tuple[str, ...]:
        return tuple(c.value for c in Check if c in self.checks)

    @property
    def excluded(self) -> tuple[str, ...]:
        return tuple(c.value for c in Check if c not in self.checks)

    def describe(self) -> str:
        """One line for a person: what this selection checks and what it leaves out."""
        out = f"profile {self.profile}: modules {', '.join(m.id for m in self.modules)}"
        return out + (f"; not checked: {', '.join(self.excluded)}" if self.excluded else "; every check")


def _check(name: str) -> Check:
    try:
        return Check(name.strip())
    except ValueError:
        raise UnknownProfile(f"unknown check {name.strip()!r}; known: {', '.join(CHECK_IDS)}") from None


def resolve(profile: str | None = None, modules: Iterable[str] | None = None,
            checks: Iterable[str] | None = None) -> Selection | None:
    """The Selection a profile and its options name, or None: no profile, module or check given (everything, as
    before profiles). `modules` or `checks` without a profile mean "custom", as --modules did in #29."""
    modules = None if modules is None else [m for m in modules if m and m.strip()]
    checks = None if checks is None else [c for c in checks if c and c.strip()]
    if profile is None and modules is None and checks is None:
        return None
    name = (profile or "custom").strip()
    if name not in NAMES:
        raise UnknownProfile(f"unknown profile {name!r}; known: {', '.join(NAMES)}")
    if name in BUILT_IN:
        if modules is not None or checks is not None:
            raise UnknownProfile(f"profile {name} selects its own modules; list modules or checks with custom")
        chosen = set(mods.checks(mods.select(BUILT_IN[name])))
    else:
        if not modules and not checks:
            raise UnknownProfile("profile custom needs modules or checks; known modules: "
                                 f"{', '.join(mods.IDS)}; known checks: {', '.join(CHECK_IDS)}")
        try:
            chosen = set(mods.checks(mods.select(modules))) if modules else set()
        except mods.UnknownModule as error:
            raise UnknownProfile(str(error)) from None
        chosen |= {_check(c) for c in checks or ()}
    return Selection(name, tuple(m for m in mods.REGISTRY if chosen & set(m.checks)), frozenset(chosen))


def from_config(cfg: dict) -> Selection | None:
    """The Selection buddie.toml's [verify] names (profile, modules, checks), None without one. UnknownProfile when
    it names something unknown or is not a table of strings: buddie.toml then counts as unusable
    (config.read_toml), so the gate returns the answer with the reason instead of running a weaker set."""
    section = cfg.get("verify")
    if section is None:
        return None
    if not isinstance(section, dict) or (bad := sorted(set(section) - {"profile", "modules", "checks"})):
        raise UnknownProfile(f"[verify]: {', '.join(bad) if isinstance(section, dict) else 'not a table'}: keys "
                             "profile, modules, checks")
    profile, modules, checks = section.get("profile"), section.get("modules"), section.get("checks")
    if profile is not None and not isinstance(profile, str):
        raise UnknownProfile("[verify] profile: a string")
    for key, v in (("modules", modules), ("checks", checks)):
        if v is not None and not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
            raise UnknownProfile(f"[verify] {key}: a list of strings")
    return resolve(profile, modules, checks)


def note(selection: Selection | None, coverage) -> str | None:
    """The diagnostics line for a check run with a selection (CLI, MCP): what it checked, what it left out, and the
    claims of the left-out kinds the text holds, so a smaller check never reads as a complete one. None without."""
    if selection is None:
        return None
    seen = [f"{s.count} {s.what.removeprefix('excluded:')}" for s in coverage.skipped if s.what.startswith("excluded:")]
    return selection.describe() + (f"; in the text and not checked: {', '.join(seen)}" if seen else "")


def gate_levels(selection: Selection | None) -> dict[str, str]:
    """The gate classes this selection turns off by default: each one none of its checks feed. The hook applies
    them below every explicit level (config.resolve_levels)."""
    if selection is None:
        return {}
    return {cls: "off" for cls, feeding in CLASS_CHECKS.items() if not feeding & selection.checks}
