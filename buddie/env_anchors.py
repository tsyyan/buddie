"""`⚓ env:CATEGORY.OBSERVATION=VALUE`: a claim about this machine, against what buddie observes on it.

An agent that tells a person "you have Python 3.12 and bash" can anchor it: `⚓ env:software.python.interpreters=3.12`,
`⚓ env:system.shell.default=bash`. The check collects the categories the anchors name through diagnostics.collect,
so the person's grants and the protected policy decide what may be read, exactly as for environment_snapshot; the
anchor grants nothing. One collection serves every env: anchor of a text.

  HOLDS        the observation was made and its value is the claimed one: equal ignoring case, or a version the
               claim names a prefix of ("3.12" holds for "3.12.3", "6.1" for "6.1.1-3ubuntu5"; "3.1" does not for
               "3.12.3"). A list (Python interpreters, GPU adapters) holds when one of its items does; an item or a
               record is compared by its own values, one level deep.
  BROKEN       the observation was made with another value; or the anchor names a category or an observation
               buddie does not have (the message lists the ones it has)
  UNCHECKABLE  not observed: the category is not granted or not allowed, the observation is unavailable (a program
               not found on PATH is not "absent"), a category needs a directory or tool names an anchor cannot give,
               or this check observes no machine (the remote server, `environment=False`)

What holds is what buddie's process saw: its user, its PATH, the guest when it runs in a container or WSL
(`concerns` in the row). The person's own terminal may differ; the row says so instead of claiming the host.
"""
from __future__ import annotations

import re

ENV = re.compile(r"^env:(?P<category>[a-z]+\.[a-z_]+)\.(?P<observation>[a-z0-9][a-z0-9_+-]*)=(?P<value>\S+)$")
VERSION = re.compile(r"^v?\d+(?:\.\d+)*$")
HOLDS, BROKEN, UNCHECKABLE = "HOLDS", "BROKEN", "UNCHECKABLE"
OFF = "this check observes no machine (environment=False, or the remote server)"


def is_env(anchor: str) -> bool:
    return anchor.startswith("env:")


def _known() -> dict[str, tuple[str, ...]]:
    from buddie import diagnostics
    return {m.id: m.observations for m in diagnostics.REGISTRY.values()}


def parse(anchor: str) -> tuple[str, str, str] | str:
    """(category, observation, value), or why the anchor is not one buddie can judge."""
    m = ENV.match(anchor)
    if not m:
        return "not an env: anchor: expected env:CATEGORY.OBSERVATION=VALUE, e.g. env:system.os.version=24.04"
    known = _known()
    if m["category"] not in known:
        return f"no category {m['category']}; buddie observes {', '.join(known)}"
    if m["observation"] not in known[m["category"]]:
        return f"{m['category']} has no {m['observation']}; it has {', '.join(known[m['category']])}"
    return m["category"], m["observation"], m["value"]


def plan(anchors) -> tuple[list[str], list[str]]:
    """The categories (registry order) and catalog tool names the judgeable env: anchors need."""
    from buddie import diagnostics
    cats, tools = set(), []
    for a in anchors:
        got = parse(a)
        if isinstance(got, str):
            continue
        cats.add(got[0])
        if diagnostics.REGISTRY[got[0]].scope == "tools" and got[1] not in tools:
            tools.append(got[1])
    return [c for c in diagnostics.REGISTRY if c in cats], tools


def observe(anchors, collect=None) -> dict | None:
    """One diagnostics document for the env: anchors of a text; None when none of them is judgeable. collect: the
    function to call (tests), else diagnostics.collect with the person's grants."""
    cats, tools = plan(anchors)
    if not cats:
        return None
    from buddie import diagnostics
    collect = collect or diagnostics.collect
    try:
        return collect(cats, task="check env: anchors in a report", tools=tools or None)
    except (ValueError, RuntimeError) as error:
        return {"error": str(error)}


def _plain(v) -> str:
    return ("true" if v else "false") if isinstance(v, bool) else str(v).strip().lower()


def matches(claimed: str, observed) -> bool:
    c = claimed.strip().lower()
    if isinstance(observed, list):
        return any(matches(claimed, item) for item in observed)
    if isinstance(observed, dict):
        return any(matches(claimed, v) for v in observed.values() if not isinstance(v, (dict, list)))
    o = _plain(observed)
    if c == o:
        return True
    if VERSION.match(c):  # a prefix of a version, cut at a component: "3.12" of "3.12.3", not "3.1" of "3.12.3"
        c, o = c.removeprefix("v"), o.removeprefix("v")
        return o.startswith(c) and (len(o) == len(c) or not o[len(c)].isdigit())
    return False


def _short(value) -> str:
    from buddie import diagnostics
    return diagnostics._short(value)


def check(anchor: str, doc: dict | None | bool) -> dict:
    """The row for one env: anchor against `doc` (observe's document; False: no machine is observed here)."""
    out = {"anchor": anchor}  # a state anchor, as path#sha256 is: no "kind" (that marks pr:, ci:, run: effects)
    got = parse(anchor)
    if isinstance(got, str):
        return dict(out, status=BROKEN, why=got)
    category, observation, value = got
    if doc is False:
        return dict(out, status=UNCHECKABLE, why=OFF)
    if not doc or doc.get("error"):
        return dict(out, status=UNCHECKABLE, why=f"the environment was not observed: {(doc or {}).get('error')}")
    cat = (doc.get("categories") or {}).get(category) or {}
    if cat.get("status") not in ("collected", "partial"):
        return dict(out, status=UNCHECKABLE, why=f"{category} was not observed: {cat.get('reason') or cat.get('status')}"
                    " (the person's grants decide: buddie snapshot --grants)")
    obs = (cat.get("observations") or {}).get(observation)
    if not obs or obs.get("status") != "observed":
        why = (obs or {}).get("reason") or "not observed"
        return dict(out, status=UNCHECKABLE, why=f"{category}.{observation} not observed: {why}")
    row = dict(out, observed=_short(obs.get("value")), concerns=obs.get("concerns") or doc.get("observations_concern"),
               at=obs.get("observed_at"))
    if matches(value, obs.get("value")):
        return dict(row, status=HOLDS)
    return dict(row, status=BROKEN, why=f"observed {category}.{observation} = {_short(obs.get('value'))}")
