"""Evidence freshness: whether evidence is bound to the revision a claim is about (docs/freshness.md).

Validity (where evidence came from, whether it is well formed), freshness (whether it applies to the target's
revision) and age (how long ago it was observed) are three answers. This module gives the second, from immutable
revision identifiers only:

  CURRENT         the evidence is bound to the target's revision, by an identifier buddie observed
  STALE           it is bound to another revision of the same target: genuine, perhaps, but not for this claim
  UNKNOWN         the target's revision or the evidence's could not be established from trustworthy information
  NOT_APPLICABLE  revision binding means nothing for this evidence (reserved)

assess() is pure: it compares two Bindings already made. Resolving a target (a PR's head now) and collecting
evidence (the commit a CI result is for) are separate functions, and a Binding counts as buddie's observation only
when buddie's own code made it (recognised by identity, never by a field a caller can set). A CI outcome (success,
failure, pending) is reported beside the freshness state, never instead of it: CURRENT is not "passed", STALE is not
"failed". Nothing here is a receipt, and nothing here changes one.
"""
from __future__ import annotations

import json
import re
import weakref
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType

from buddie.core import Provenance

FORMAT = "https://github.com/tsyyan/buddie#freshness-v0"
CURRENT, STALE, UNKNOWN, NOT_APPLICABLE = "CURRENT", "STALE", "UNKNOWN", "NOT_APPLICABLE"
STATES = (CURRENT, STALE, UNKNOWN, NOT_APPLICABLE)
FULL = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
HEX = re.compile(r"^[0-9a-f]{7,64}$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
OK_CONCLUSIONS = {"success", "neutral", "skipped"}  # as effects.py counts them for ci:


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True, eq=False)
class Binding:
    """One side of a comparison: what is bound (`kind`), in which repository, to which revision. `revision` is None
    when it could not be established, and `reason` says why. `provenance` says how the revision is known; only a
    Binding buddie made (observed()) is taken for buddie's observation, whatever this field says."""
    kind: str                          # commit, pr_head, github_ci, repository, artifact
    repository: str | None             # owner/name (GitHub), or "local" for the repository on disk
    ref: str                           # what was asked for: a SHA, "#7", a path
    revision: str | None
    provenance: Provenance
    reason: str | None = None
    observed_at: str | None = None
    details: Mapping = field(default_factory=dict)  # what the evidence says beside its revision (the CI outcome)

    def __post_init__(self):
        # frozen all the way down: what was observed cannot be edited after the fact (a read-only mapping of
        # tuples); render() gives new plain objects, so a document shares nothing with the binding
        object.__setattr__(self, "details", _freeze(self.details if self.details is not None else {}))

    def __reduce__(self):
        # copy, deepcopy and pickle rebuild a Binding from its fields: a new object, which buddie did not observe
        return (Binding, (self.kind, self.repository, self.ref, self.revision, self.provenance, self.reason,
                          self.observed_at, _thaw(self.details)))


def _freeze(value):
    """`value` as read-only data: dicts as read-only mappings with string keys, lists as tuples, JSON scalars as
    they are. Anything else is refused (ValueError): details are data, never objects with behaviour."""
    if type(value) in (dict, MappingProxyType):
        if any(type(k) is not str for k in value):
            raise ValueError("details: keys are strings")
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if type(value) in (list, tuple):
        return tuple(_freeze(v) for v in value)
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise ValueError(f"details: {type(value).__name__} is not JSON data")


def _thaw(value):
    if type(value) is MappingProxyType:
        return {k: _thaw(v) for k, v in value.items()}
    if type(value) is tuple:
        return [_thaw(v) for v in value]
    return value


# Bindings buddie's own code made, by identity. This tells buddie's observations from data: a Binding built from
# fields, copied, unpickled or read from JSON is not one. It is not a sandbox: Python code running in this
# interpreter can call _observed() as it can replace github_get itself (docs/freshness.md, "Trust boundaries").
_OBSERVED: weakref.WeakSet = weakref.WeakSet()


def _observed(binding: Binding) -> Binding:
    _OBSERVED.add(binding)
    return binding


def observed(binding) -> bool:
    """Whether `binding` is one buddie's code made (resolve_*, ci_*, repository_*, artifact_*)."""
    return type(binding) is Binding and any(binding is b for b in _OBSERVED)


def claimed(kind: str, repository: str | None, revision: str | None, ref: str | None = None) -> Binding:
    """A caller's own statement of a target: the claim being evaluated ("commit A passed"), not evidence."""
    return Binding(kind, repository, ref or (revision or ""), revision, Provenance.CALLER_SUPPLIED,
                   None if revision else "not_given")


@dataclass(frozen=True)
class Freshness:
    state: str
    reason: str
    target: Binding
    evidence: Binding


def _repo_key(repo: str | None) -> str | None:
    return repo.lower() if type(repo) is str else None


def assess(target: Binding, evidence: Binding) -> Freshness:
    """The freshness of `evidence` for `target` (docs/freshness.md, "The comparison"). Pure: no network, no disk."""
    def out(state, reason):
        return Freshness(state, reason, target, evidence)
    if type(target) is not Binding or type(evidence) is not Binding:
        return out(UNKNOWN, "not_a_binding")
    if target.revision is None:
        return out(UNKNOWN, "target_unresolved")
    if evidence.revision is None:
        return out(UNKNOWN, "evidence_unresolved")
    if not (type(target.revision) is str and FULL.match(target.revision)
            and type(evidence.revision) is str and FULL.match(evidence.revision)):
        return out(UNKNOWN, "not_immutable")
    if _repo_key(target.repository) is None or _repo_key(target.repository) != _repo_key(evidence.repository):
        return out(UNKNOWN, "different_repository")
    if not observed(evidence) or evidence.provenance is Provenance.CALLER_SUPPLIED:
        return out(UNKNOWN, "evidence_not_observed")
    if target.kind == "pr_head" and (not observed(target) or target.provenance is Provenance.CALLER_SUPPLIED):
        return out(UNKNOWN, "target_not_resolved")
    if target.revision == evidence.revision:
        return out(CURRENT, "same_revision")
    return out(STALE, "different_revision")


# --- GitHub: a PR's head now, the commit a CI result is for ---------------------------------------------------------

def _provenance(get) -> Provenance:
    """COLLECTOR_OBSERVED for buddie's own GitHub GET to the default API or the protected policy's, over a network
    nothing in the environment stood in; UNKNOWN otherwise (an API the environment named, a caller's function)."""
    from buddie import effects, evidence
    _, chosen = effects.api()
    return Provenance.COLLECTOR_OBSERVED if (effects.own_get(get) and chosen != "environment"
                                             and evidence.network_clean()) else Provenance.UNKNOWN


def _ask(get, path: str, off: str | None = None):
    """(data, None) or (None, reason): GitHub off (`off` says why: github_off, network_forbidden), unreachable or
    refused, or nothing at that path."""
    from buddie.effects import GitHubUnavailable
    if get is None:
        return None, off or "github_off"
    try:
        data = get(path)
    except GitHubUnavailable:
        return None, "github_unavailable"
    return (data, None) if data is not None else (None, "not_found")


def resolve_pr_head(repository: str, number: int, get, clock=_now, off: str | None = None) -> Binding:
    """The head commit of PR `number` in `repository` as GitHub gives it now. The PR's base repository must be the
    one asked for (a PR number names a PR in one repository only)."""
    ref = f"#{number}"
    if not (type(repository) is str and REPO.match(repository)) or type(number) is not int or number < 1:
        return _observed(Binding("pr_head", repository, ref, None, Provenance.UNKNOWN, "invalid_target"))
    prov = _provenance(get)
    data, why = _ask(get, f"/repos/{repository}/pulls/{number}", off)
    at = clock()
    if why:
        return _observed(Binding("pr_head", repository, ref, None, prov, why, at))
    head = data.get("head") if isinstance(data, dict) else None
    base = ((data.get("base") or {}).get("repo") or {}).get("full_name") if isinstance(data, dict) else None
    sha = head.get("sha") if isinstance(head, dict) else None
    if not (type(sha) is str and FULL.match(sha)):
        return _observed(Binding("pr_head", repository, ref, None, prov, "malformed_answer", at))
    if type(base) is not str or base.lower() != repository.lower():
        return _observed(Binding("pr_head", repository, ref, None, prov, "different_repository", at))
    state = "merged" if data.get("merged") else data.get("state")
    return _observed(Binding("pr_head", repository, ref, sha, prov, None, at,
                             {"pr_state": state if type(state) is str else None}))


def _ci_runs(repository: str, sha: str, get) -> tuple[list[dict] | None, list[dict] | None, str | None]:
    """(check runs, statuses, None) on the full `sha`, each bound to the commit its own payload names, or
    (None, None, reason). A run or status whose commit is not `sha` makes the answer inconsistent."""
    runs, page = [], 1
    while True:
        # filter=latest, said rather than left to GitHub's default: the latest run of each check in each check
        # suite, so a re-run replaces the attempt before it. Suites stay apart: GitHub does not say which of two
        # suites on one commit is the one that counts
        data, why = _ask(get, f"/repos/{repository}/commits/{sha}/check-runs?filter=latest&per_page=100&page={page}")
        if why:
            return None, None, why
        got = data.get("check_runs") if isinstance(data, dict) else None
        if not isinstance(got, list):
            return None, None, "malformed_answer"
        for r in got:
            if not isinstance(r, dict) or type(r.get("name")) is not str or type(r.get("status")) is not str:
                return None, None, "malformed_answer"
            if r.get("head_sha") != sha:
                return None, None, "inconsistent_answer"
            suite = (r.get("check_suite") or {}).get("id") if isinstance(r.get("check_suite"), dict) else None
            runs.append({"name": r["name"], "status": r["status"],
                         "conclusion": r.get("conclusion") if type(r.get("conclusion")) is str else None,
                         "check_suite": suite if type(suite) is int else None})
        if len(got) < 100:
            break
        page += 1
        if page > 20:
            return None, None, "too_many_checks"
    data, why = _ask(get, f"/repos/{repository}/commits/{sha}/status")
    if why == "not_found":
        data, why = {"sha": sha, "statuses": []}, None
    if why:
        return None, None, why
    if not isinstance(data, dict) or not isinstance(data.get("statuses"), list):
        return None, None, "malformed_answer"
    if data["statuses"] and data.get("sha") != sha:
        return None, None, "inconsistent_answer"
    statuses = []
    for s in data["statuses"]:
        if not isinstance(s, dict) or type(s.get("context")) is not str or type(s.get("state")) is not str:
            return None, None, "malformed_answer"
        statuses.append({"context": s["context"], "state": s["state"]})
    runs.sort(key=lambda r: (r["name"], r["check_suite"] or 0, r["status"], r["conclusion"] or ""))
    statuses.sort(key=lambda s: (s["context"], s["state"]))
    return runs, statuses, None


def duplicates(runs, statuses) -> list[str]:
    """Check names that appear more than once among the latest runs (in several check suites: two workflows, the
    same workflow on two events) and status contexts that appear more than once. GitHub gives no rule for which of
    them is the result that counts."""
    seen: dict = {}
    for key in [("run", r["name"]) for r in runs] + [("status", s["context"]) for s in statuses]:
        seen[key] = seen.get(key, 0) + 1
    return sorted({name for (_, name), n in seen.items() if n > 1})


def ci_outcome(runs, statuses, check: str | None = None) -> str:
    """success, failure, pending, ambiguous or none, from the latest runs and statuses:
      pending    a run or status is not done
      ambiguous  one check name (or status context) has a run that ended well and one that did not, in different
                 check suites: which one counts cannot be told from GitHub's answer, so neither is taken
      success    every run ended success, neutral or skipped, every status success
      failure    otherwise (cancelled, timed out, action required, ...)
      none       nothing at all"""
    if check is not None:
        runs = [r for r in runs if r["name"] == check]
        statuses = [s for s in statuses if s["context"] == check]
    if not runs and not statuses:
        return "none"
    if any(r["status"] != "completed" for r in runs) or any(s["state"] == "pending" for s in statuses):
        return "pending"
    ok: dict = {}
    for key, good in ([(("run", r["name"]), r["conclusion"] in OK_CONCLUSIONS) for r in runs]
                      + [(("status", s["context"]), s["state"] == "success") for s in statuses]):
        ok.setdefault(key, set()).add(good)
    if any(len(v) > 1 for v in ok.values()):
        return "ambiguous"
    return "success" if all(True in v for v in ok.values()) else "failure"


def ci_evidence(repository: str, ref: str, get, check: str | None = None, clock=_now,
                off: str | None = None) -> Binding:
    """The commit GitHub's CI results for `ref` are bound to, with those results. `ref` is the SHA the evidence
    names (a ci: anchor's, a report's); GitHub resolves it to a full commit id, which must start with it (a branch
    or tag of that name pointing elsewhere is not the commit), and every check run and status on it must name that
    commit. No result at all is unresolved evidence (`no_ci_results`), never a success."""
    if not (type(repository) is str and REPO.match(repository)) or not (type(ref) is str and HEX.match(ref)):
        return _observed(Binding("github_ci", repository, str(ref), None, Provenance.UNKNOWN, "invalid_evidence"))
    prov = _provenance(get)
    data, why = _ask(get, f"/repos/{repository}/commits/{ref}", off)
    at = clock()
    if why:
        return _observed(Binding("github_ci", repository, ref, None, prov, why, at))
    sha = data.get("sha") if isinstance(data, dict) else None
    if not (type(sha) is str and FULL.match(sha)):
        return _observed(Binding("github_ci", repository, ref, None, prov, "malformed_answer", at))
    if not sha.startswith(ref):
        return _observed(Binding("github_ci", repository, ref, None, prov, "ambiguous_reference", at))
    runs, statuses, why = _ci_runs(repository, sha, get)
    if why:
        return _observed(Binding("github_ci", repository, ref, None, prov, why, at))
    outcome = ci_outcome(runs, statuses, check)
    details = {"ci": outcome, "check": check, "check_runs": runs, "statuses": statuses, "selection": "latest",
               "duplicates": duplicates(runs, statuses)}
    if outcome == "none":
        return _observed(Binding("github_ci", repository, ref, None, prov, "no_ci_results", at, details))
    return _observed(Binding("github_ci", repository, ref, sha, prov, None, at, details))


# --- the local repository and its files ---------------------------------------------------------------------------

def repository_now(root, clock=_now) -> Binding:
    """The local repository's HEAD as buddie observes it now (environment.repository: hardened git). A tree that is
    dirty, hides entries from git status, or cannot be read leaves the binding unresolved: a HEAD with other files
    beside it is not that commit's state."""
    from pathlib import Path

    from buddie import environment
    facts, _ = environment.repository(Path(root), clock)
    head, tree = facts["head"], facts["worktree"]
    if head["status"] != "observed":
        return _observed(Binding("repository", "local", "HEAD", None, Provenance.AGENT_WRITABLE, head["reason"],
                                 facts["observed_at"]))
    if tree["status"] != "observed" or tree["value"] != "clean":
        why = "dirty_worktree" if tree["status"] == "observed" else tree["reason"]
        return _observed(Binding("repository", "local", "HEAD", None, Provenance.AGENT_WRITABLE, why,
                                 facts["observed_at"], {"head": head["value"]}))
    return _observed(Binding("repository", "local", "HEAD", head["value"], Provenance.AGENT_WRITABLE, None,
                             facts["observed_at"]))


def artifact_now(root, path: str, clock=_now) -> Binding:
    """The sha256 of the file `path` under `root` as buddie reads it now (environment.artifact: inside the root, no
    symlink out, stable while read)."""
    from pathlib import Path

    from buddie import environment
    rec = environment.artifact(Path(root), path, 0, [environment.MAX_TOTAL_BYTES], clock)
    return _observed(Binding("artifact", "local", rec["path"] or "", rec["sha256"], Provenance.AGENT_WRITABLE,
                             rec["reason"], rec["observed_at"]))


def assess_artifact(recorded: str | None, now: Binding) -> Freshness:
    """A recorded digest (a snapshot's, a report's) against the file now: CURRENT when the bytes are the same, STALE
    when they differ, UNKNOWN when either is missing. Equal bytes, not the same file over time."""
    target = Binding("artifact", "local", now.ref, recorded if type(recorded) is str and re.fullmatch(
        r"[0-9a-f]{64}", recorded) else None, Provenance.CALLER_SUPPLIED, None if recorded else "not_given")
    if target.revision is None:
        return Freshness(UNKNOWN, "target_unresolved", target, now)
    if now.revision is None:
        return Freshness(UNKNOWN, "evidence_unresolved", target, now)
    if not observed(now):
        return Freshness(UNKNOWN, "evidence_not_observed", target, now)
    return Freshness(CURRENT if target.revision == now.revision else STALE,
                     "same_bytes" if target.revision == now.revision else "different_bytes", target, now)


# --- rendering ------------------------------------------------------------------------------------------------------

def _binding(b: Binding) -> dict:
    return {"kind": b.kind, "repository": b.repository, "ref": b.ref, "revision": b.revision,
            "provenance": b.provenance.value, "observed_by_buddie": observed(b), "reason": b.reason,
            "observed_at": b.observed_at, "details": _thaw(b.details)}  # new objects: nothing shared


def _ci_consistent(b: Binding) -> bool:
    """A CI binding's summary is what its own runs and statuses give (ci_outcome), so no summary stands apart from
    the results it summarises."""
    d = b.details
    if b.kind != "github_ci" or "check_runs" not in d:
        return True
    return d.get("ci") == ci_outcome(d["check_runs"], d["statuses"], d.get("check")) and \
        list(d.get("duplicates", ())) == duplicates(d["check_runs"], d["statuses"])


def render(results) -> dict:
    """The freshness document for one or more Freshness results. Each state is computed again from its bindings
    (assess, or assess_artifact for artifacts), and each CI summary from its runs and statuses: a result whose state
    or summary was set by hand is refused (ValueError). Bindings and their details are read-only, so what is
    rendered is what was observed."""
    out = []
    for f in results:
        again = (assess_artifact(f.target.revision, f.evidence) if f.target.kind == "artifact"
                 else assess(f.target, f.evidence))
        if (again.state, again.reason) != (f.state, f.reason):
            raise ValueError("a freshness result that its bindings do not give")
        if not (_ci_consistent(f.target) and _ci_consistent(f.evidence)):
            raise ValueError("a CI summary that its runs and statuses do not give")
        out.append({"state": f.state, "reason": f.reason, "target": _binding(f.target),
                    "evidence": _binding(f.evidence)})
    return {"format": FORMAT, "results": out}


def dumps(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def line(f: Freshness) -> str:
    """One line for a person: the state and why, and beside it what the evidence says (the CI outcome)."""
    def short(s):
        return s[:12] if s else "?"
    text = f"freshness {f.state} ({f.reason})"
    if f.reason == "different_revision":
        text += f": the evidence is for {short(f.evidence.revision)}, the target is {short(f.target.revision)}"
    elif f.reason == "same_revision":
        text += f": both {short(f.target.revision)}"
    elif f.state == UNKNOWN:
        why = f.target.reason if f.reason.startswith("target") else f.evidence.reason
        text += f": {why}" if why else ""
    ci = f.evidence.details.get("ci") if isinstance(f.evidence.details, Mapping) else None
    if ci:
        text += f"; CI on the evidence's commit: {ci} (not a freshness answer)"
        if dup := f.evidence.details.get("duplicates"):
            text += f"; in more than one check suite: {', '.join(dup)}"
    return text
