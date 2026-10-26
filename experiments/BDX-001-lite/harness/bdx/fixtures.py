"""Recorded environments (fixtures/raw/<env>/) and the tool answers built from them.

Condition C answers are cut from one real `buddie snapshot` document per environment, collected with every category
and every catalog tool requested. A request for some categories gets the recorded entries of those categories,
unchanged, with the request bookkeeping (request, authorization, supplied, limitations) recomputed the way
diagnostics.collect computes it, and the result must pass diagnostics.problems(). Categories are collected
independently of each other (diagnostics.collect runs them one by one), so the cut equals a narrower collection apart
from timing. Nothing is added that the collectors did not produce.

Condition B answers are the recorded stdout, stderr and exit status of the commands asked for.
"""
from __future__ import annotations

import hashlib
import json
import sys
from functools import lru_cache

from bdx import REPO, ROOT

RAW = ROOT / "fixtures" / "raw"
MENU = ROOT / "fixtures" / "collect" / "shell_menu.json"

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from buddie import diagnostics, mcp  # noqa: E402  (read-only use of buddie's observer and adapter code)


@lru_cache(maxsize=None)
def env(name: str) -> dict:
    d = RAW / name
    return {"buddie": json.loads((d / "buddie_full.json").read_text(encoding="utf-8")),
            "catalog": json.loads((d / "buddie_catalog.json").read_text(encoding="utf-8")),
            "shell": json.loads((d / "shell.json").read_text(encoding="utf-8")),
            "meta": json.loads((d / "meta.json").read_text(encoding="utf-8"))}


def environments() -> list[str]:
    return sorted(p.name for p in RAW.iterdir() if p.is_dir())


@lru_cache(maxsize=None)
def menu() -> list[str]:
    return [i["id"] for i in json.loads(MENU.read_text(encoding="utf-8"))["items"]]


# --- condition C ------------------------------------------------------------------------------------------------------

def _tools_entry(entry: dict, named: list[str], bad: list[dict], when: str) -> dict:
    """software.tools as diagnostics._category builds it for these tool names, from the all-tools recording."""
    if not named and not bad:
        return {"status": "unavailable", "reason": "no_tools_given", "tier": entry["tier"], "methods": [],
                "observations": {}}
    obs = {k: v for k, v in entry["observations"].items() if k in named}
    methods = [m for m in entry["methods"] if m["method"].removeprefix("tool:") in named]
    for b in bad:
        if b["name"]:
            obs[b["name"]] = {"status": "unavailable", "value": None, "basis": None, "method": None,
                              "observed_at": when, "reason": "not_in_catalog", "concerns": "runtime"}
    seen = sum(o["status"] == "observed" for o in obs.values())
    status = "collected" if seen and seen == len(obs) else "partial" if seen else "unavailable"
    return {"status": status, "reason": "nothing_observed" if status == "unavailable" else None,
            "tier": entry["tier"], "methods": methods, "observations": dict(sorted(obs.items()))}


def buddie_answer(env_name: str, args: dict, request_id: str) -> tuple[dict, bool]:
    """(data, is_error) as mcp.environment_snapshot would return them on the recorded machine."""
    if extra := sorted(set(args) - mcp.ENVIRONMENT_ARGS):
        return {"error": f"unknown arguments {', '.join(extra)}: what is collected is decided by the person's "
                         "grants file and the protected policy, not by the request (buddie snapshot --grants)"}, True
    rec = env(env_name)
    if args.get("list"):
        return rec["catalog"], False
    full = rec["buddie"]
    categories, tools, task, path = args.get("categories"), args.get("tools"), args.get("task"), args.get("path")
    try:
        known, rejected, named, bad, task = diagnostics.validate(categories, tools, task)
        if path is not None and (type(path) is not str or not path or len(path) > 4096 or "\0" in path):
            raise ValueError("path: a directory")
    except ValueError as error:
        return {"error": str(error)}, True
    order = [c for c in diagnostics.REGISTRY if c in known] + [c for c in diagnostics.UNSUPPORTED if c in known]
    cats = {}
    for cid in order:
        entry = json.loads(json.dumps(full["categories"][cid]))
        if cid == "software.tools" and entry["status"] not in ("denied", "unsupported"):
            entry = _tools_entry(entry, named, bad, full["finished_at"])
        cats[cid] = entry
    allowed = set(full["authorization"]["effective"])
    doc = {
        "format": full["format"], "collector": full["collector"],
        "request": {"id": request_id, "categories": [c for c in categories if isinstance(c, str)
                                                     and diagnostics.ID.match(c)][:diagnostics.MAX_CATEGORIES],
                    "rejected": rejected, "tools": named, "rejected_tools": bad, "path_given": path is not None},
        "authorization": {"grants": full["authorization"]["grants"], "policy": full["authorization"]["policy"],
                          "effective": sorted(c for c in known if c in diagnostics.REGISTRY and c in allowed)},
        "started_at": full["started_at"], "finished_at": full["finished_at"],
        "observations_concern": full["observations_concern"],
        "categories": cats,
        "supplied": {"task": task} if task is not None else {},
        "limitations": sorted(x for x in full["limitations"] if x.split(":")[0] in cats),
        "scopes": full["scopes"], "snapshot": None,
    }
    return doc, False


def buddie_text(data: dict, is_error: bool) -> str:
    """The text content mcp.handle sends for environment_snapshot."""
    text = json.dumps(data, ensure_ascii=False, indent=1)
    if not is_error and data.get("format", "").endswith("diagnostics-v1"):
        text = "\n".join(diagnostics.lines(data)) + "\n" + text
    return text


# --- condition B ------------------------------------------------------------------------------------------------------

def shell_text(env_name: str, commands: list[str]) -> str:
    records = {r["command"]: r for r in env(env_name)["shell"]["records"]}
    parts = []
    for c in commands:
        r = records[c]
        out = r["stdout"].rstrip("\n")
        err = r["stderr"].rstrip("\n")
        body = "\n".join(x for x in (out, err) if x)
        code = "timeout" if r["exit"] is None else r["exit"]
        parts.append(f"$ {c}\n{body}\n[exit code: {code}]".replace("\r\n", "\n"))
    return "\n\n".join(parts)


def request_id(run_id: str, n: int) -> str:
    return hashlib.sha256(f"{run_id}:{n}".encode()).hexdigest()[:32]
