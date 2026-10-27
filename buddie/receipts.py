"""Receipt contracts: one verify.Assessment, rendered as receipt-v0 (as verify() always gave it) or receipt-v1.

The contract version is the predicateType, and only that: `…#receipt-v0` or `…#receipt-v1`. The in-toto Statement
around it (`_type`, `subject`) is the same for both. Rendering never checks anything again and never changes what
was checked: the version a caller asks for decides the shape of the answer, not its content.

receipt-v1 keeps apart what receipt-v0 folds into one word:

  verification.outcome   what the checks that ran established, from their typed findings:
                         FAIL     a finding the policy blocks (a contradicted quote, anchor or work claim; a
                                  contradicted number with numbers="fail")
                         UNKNOWN  a verdict buddie does not recognize (never taken for support)
                         GAPS     something undetermined: a source unreadable, a repo or GitHub out of reach, a
                                  number not on its page with numbers="gap"
                         PASS     every finding supported (or a claim the text does not make)
                         EMPTY    checks ran and found nothing to judge: no quotation, anchor or work claim of an
                                  executed kind
                         NOT_RUN  no check ran
  scope                  what was asked for, what that came to, what ran, and what did not and why:
                         requested   the profile and checks asked for (null: none, so everything)
                         effective   the checks selected after the profile, the gate levels and the protected
                                     policy's floors
                         executed    the checks whose checker ran
                         excluded    every other check, with one reason: profile (the requested profile leaves it
                                     out), gate_level (the requested profile has it, the effective levels turned it
                                     off), call_option (selected, but an option of the call turned it off:
                                     anchors only, numbers off, no work claims), unavailable (selected and asked
                                     for, but this run had nothing to check it with: no buddie.toml [mandate]); and
                                     `detected`, how many claims of that kind the text holds where that can be
                                     counted without checking (quotations, anchors: 0 when there are none), else
                                     null (numbers, work claims: what counts as one takes the check)
                         coverage    NONE (nothing ran), PARTIAL (something left out on purpose: profile,
                                     gate_level or call_option), UNKNOWN (only unavailable checks are missing: whether
                                     they apply cannot be told), FULL (every check buddie has ran)
  evidence.provenance    how many evidence references of each core.Provenance the findings carry

FULL is about which checks ran, not about the text: a check finds the claims written in its form (a quotation with
a link, an anchor), and a claim written otherwise is not detected by any check. PASS is about what the checks
established, not about the report being true.

The mapping between the two outcomes, for the same Assessment (tests/test_receipts.py): v0 FAIL is v1 FAIL; v0 PASS
is v1 PASS; v0 GAPS is v1 GAPS or UNKNOWN (an unrecognized verdict); v0 EMPTY is v1 EMPTY or NOT_RUN. receipt-v0
never says what did not run; receipt-v1's scope does.

A receipt is buddie's statement of what it did, made by whoever ran buddie: it is not signed, and nothing in it is
proof that a protected policy was in force. problems() checks a receipt-v1 for internal consistency, not for
authenticity.
"""
from __future__ import annotations

import json

from buddie import core
from buddie import modules as mods

V0 = "https://github.com/tsyyan/buddie#receipt-v0"
V1 = "https://github.com/tsyyan/buddie#receipt-v1"
VERSIONS = {"v0": V0, "v1": V1}
OUTCOMES = ("PASS", "FAIL", "GAPS", "UNKNOWN", "EMPTY", "NOT_RUN")
COVERAGE = ("FULL", "PARTIAL", "UNKNOWN", "NONE")
REASONS = ("profile", "gate_level", "call_option", "unavailable")
DELIBERATE = {"profile", "gate_level", "call_option"}
CHECKS = tuple(c.value for c in core.Check)


class UnknownReceiptVersion(ValueError):
    pass


def version_of(name: str | None) -> str:
    """"v0" or "v1" from a caller's choice (None: v0, the default everywhere); anything else is an error."""
    if name is None:
        return "v0"
    if name not in VERSIONS:
        raise UnknownReceiptVersion(f"unknown receipt version {name!r}; known: {', '.join(VERSIONS)}")
    return name


def render(assessment, version: str | None = None) -> dict:
    """The receipt of `assessment` in contract `version` ("v0", default, or "v1")."""
    return assessment.receipt if version_of(version) == "v0" else v1(assessment)


def _ids(checks) -> list[str]:
    return [c.value for c in core.Check if c in checks]


def _finding(f: core.Finding, policy: core.Policy) -> dict:
    return {"check": f.check.value, "module": mods.module_of(f.check).id, "line": f.line, "subject": f.subject,
            "verdict": f.verdict, "fact": f.fact.value, "reason": f.reason.value,
            "decision": policy.decide(f).value, "message": f.message,
            "evidence": [{"kind": e.kind, "locator": e.locator, "provenance": e.provenance.value, "digest": e.digest,
                          "source": e.source, "observed_at": e.observed_at} for e in f.evidence]}


def outcome(findings, executed, policy: core.Policy) -> str:
    """receipt-v1's verification.outcome (see the module's docstring)."""
    if not executed:
        return "NOT_RUN"
    if not findings:
        return "EMPTY"
    return core.outcome(findings, None, policy).value  # coverage is scope's, not the outcome's


def coverage_state(executed, reasons: dict) -> str:
    if not executed:
        return "NONE"
    if any(r in DELIBERATE for r in reasons.values()):
        return "PARTIAL"
    return "UNKNOWN" if reasons else "FULL"


def v1(a) -> dict:
    """receipt-v1 of verify.Assessment `a`."""
    policy = core.Policy(a.numbers == "fail")
    requested_checks = a.requested.checks if a.requested is not None else frozenset(core.Check)
    detected = dict(a.detected)
    reasons = {}
    for check, why in a.not_run:
        if why == "selection":  # left out by the selection: by the profile, or by the levels it came to
            why = "profile" if check not in requested_checks else "gate_level"
        reasons[check] = why
    provenance = {p.value: 0 for p in core.Provenance}
    for f in a.findings:
        for e in f.evidence:
            provenance[e.provenance.value] += 1
    counts = {fact.value: 0 for fact in core.Fact}
    for f in a.findings:
        counts[f.fact.value] += 1
    v0 = a.receipt
    return {
        "_type": v0["_type"],
        "subject": v0["subject"],
        "predicateType": V1,
        "predicate": {
            "producer": {"buddie": v0["predicate"]["tool"]["buddie"], "verbatim": v0["predicate"]["tool"]["verbatim"]},
            "checked_at": v0["predicate"]["checked_at"],
            "verification": {
                "outcome": outcome(a.findings, a.executed, policy),
                "numbers": a.numbers,
                "counts": counts,
                "findings": [_finding(f, policy) for f in a.findings],
            },
            "scope": {
                "requested": {"profile": a.requested.profile if a.requested is not None else None,
                              "checks": _ids(a.requested.checks) if a.requested is not None else None},
                "effective": _ids(a.effective.checks if a.effective is not None else core.Check),
                "executed": _ids(a.executed),
                "excluded": [{"check": c.value, "module": mods.module_of(c).id, "reason": reasons[c],
                              "detected": detected.get(c)} for c in core.Check if c in reasons],
                "coverage": coverage_state(a.executed, reasons),
                "signals": {s.what: s.count for s in a.coverage.skipped
                            if not s.capability and s.count and not s.what.startswith("excluded:")},
            },
            "evidence": {"provenance": provenance},
        },
    }


def line(receipt: dict) -> str:
    """One line for a person: the outcome and the coverage of a receipt-v1."""
    pred = receipt["predicate"]
    scope = pred["scope"]
    out = f"buddie {pred['verification']['outcome']} (receipt-v1, coverage {scope['coverage']}"
    out += f": {len(scope['executed'])} of {len(CHECKS)} checks ran"
    left = [f"{e['check']} ({e['reason']}{', ' + str(e['detected']) + ' in the text' if e['detected'] else ''})"
            for e in scope["excluded"]]
    return out + (f"; not run: {', '.join(left)})" if left else ")")


def dumps(receipt: dict) -> str:
    """A receipt as canonical JSON: keys sorted, UTF-8 characters as they are, the same bytes for the same receipt."""
    return json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# --- the schema and the rules it cannot express -------------------------------------------------------------------

_NULL_STR = {"type": ["string", "null"]}
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": V1,
    "title": "buddie receipt-v1",
    "type": "object",
    "required": ["_type", "subject", "predicateType", "predicate"],
    "additionalProperties": False,
    "properties": {
        "_type": {"const": "https://in-toto.io/Statement/v1"},
        "subject": {"type": "array", "minItems": 1, "items": {
            "type": "object", "required": ["name", "digest"], "additionalProperties": False,
            "properties": {"name": {"type": "string"}, "digest": {
                "type": "object", "required": ["sha256"], "additionalProperties": False,
                "properties": {"sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}}}}},
        "predicateType": {"const": V1},
        "predicate": {
            "type": "object", "required": ["producer", "checked_at", "verification", "scope", "evidence"],
            "additionalProperties": False,
            "properties": {
                "producer": {"type": "object", "required": ["buddie", "verbatim"], "additionalProperties": False,
                             "properties": {"buddie": {"type": "string"}, "verbatim": _NULL_STR}},
                "checked_at": {"type": "string"},
                "verification": {
                    "type": "object", "required": ["outcome", "numbers", "counts", "findings"],
                    "additionalProperties": False,
                    "properties": {
                        "outcome": {"enum": list(OUTCOMES)},
                        "numbers": {"enum": ["gap", "fail", "off"]},
                        "counts": {"type": "object", "required": [f.value for f in core.Fact],
                                   "additionalProperties": False,
                                   "properties": {f.value: {"type": "integer", "minimum": 0} for f in core.Fact}},
                        "findings": {"type": "array", "items": {"$ref": "#/$defs/finding"}},
                    }},
                "scope": {
                    "type": "object",
                    "required": ["requested", "effective", "executed", "excluded", "coverage", "signals"],
                    "additionalProperties": False,
                    "properties": {
                        "requested": {"type": "object", "required": ["profile", "checks"],
                                      "additionalProperties": False,
                                      "properties": {"profile": _NULL_STR,
                                                     "checks": {"type": ["array", "null"],
                                                                "items": {"$ref": "#/$defs/check"}}}},
                        "effective": {"type": "array", "items": {"$ref": "#/$defs/check"}},
                        "executed": {"type": "array", "items": {"$ref": "#/$defs/check"}},
                        "excluded": {"type": "array", "items": {
                            "type": "object", "required": ["check", "module", "reason", "detected"],
                            "additionalProperties": False,
                            "properties": {"check": {"$ref": "#/$defs/check"}, "module": {"$ref": "#/$defs/module"},
                                           "reason": {"enum": list(REASONS)},
                                           "detected": {"type": ["integer", "null"], "minimum": 0}}}},
                        "coverage": {"enum": list(COVERAGE)},
                        "signals": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 0}},
                    }},
                "evidence": {"type": "object", "required": ["provenance"], "additionalProperties": False,
                             "properties": {"provenance": {
                                 "type": "object", "required": [p.value for p in core.Provenance],
                                 "additionalProperties": False,
                                 "properties": {p.value: {"type": "integer", "minimum": 0}
                                                for p in core.Provenance}}}},
            }},
    },
    "$defs": {
        "check": {"enum": list(CHECKS)},
        "module": {"enum": list(mods.IDS)},
        "finding": {
            "type": "object", "additionalProperties": False,
            "required": ["check", "module", "line", "subject", "verdict", "fact", "reason", "decision", "message",
                         "evidence"],
            "properties": {
                "check": {"$ref": "#/$defs/check"}, "module": {"$ref": "#/$defs/module"},
                "line": {"type": ["integer", "null"]}, "subject": {"type": "string"}, "verdict": {"type": "string"},
                "fact": {"enum": [f.value for f in core.Fact]},
                "reason": {"enum": [r.value for r in core.ReasonCode]},
                "decision": {"enum": [d.value for d in core.Decision]}, "message": _NULL_STR,
                "evidence": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["kind", "locator", "provenance", "digest", "source", "observed_at"],
                    "properties": {"kind": {"type": "string"}, "locator": {"type": "string"},
                                   "provenance": {"enum": [p.value for p in core.Provenance]},
                                   "digest": _NULL_STR, "source": _NULL_STR, "observed_at": _NULL_STR}}},
            }},
    },
}


def problems(receipt: dict) -> list[str]:
    """What is inconsistent in a receipt-v1 beyond its JSON Schema: each check once and in core.Check order,
    executed within effective, excluded exactly the rest with the reason the requested and effective selections
    imply (profile: neither; gate_level: requested, not effective; call_option, unavailable: effective, not run;
    nothing requested is every check requested), coverage and outcome as the rest of
    the receipt implies, counts and provenance as its findings say. [] when it holds together. A receipt anyone
    edited can still hold together: this is consistency, not authenticity."""
    out: list[str] = []
    try:
        pred, scope = receipt["predicate"], receipt["predicate"]["scope"]
        verification = pred["verification"]
    except (KeyError, TypeError):
        return ["not a receipt-v1: no predicate with scope and verification"]
    if receipt.get("predicateType") != V1:
        out.append(f"predicateType is {receipt.get('predicateType')!r}, not {V1}")

    def ordered(name, ids):
        if any(i not in CHECKS for i in ids):
            out.append(f"scope.{name}: unknown check {[i for i in ids if i not in CHECKS]}")
        elif list(ids) != [c for c in CHECKS if c in ids]:
            out.append(f"scope.{name}: not each check once in core.Check order")
    effective, executed = scope.get("effective", []), scope.get("executed", [])
    excluded = scope.get("excluded", [])
    ordered("effective", effective)
    ordered("executed", executed)
    ordered("excluded", [e.get("check") for e in excluded])
    requested = scope.get("requested") or {}
    asked = requested.get("checks")
    if (requested.get("profile") is None) != (asked is None):
        out.append("scope.requested: a profile and its checks, or neither (nothing requested: every check)")
    if asked is not None:
        ordered("requested.checks", asked)
    asked = set(CHECKS) if asked is None else set(asked)  # nothing requested is every registered check
    if set(executed) - set(effective):
        out.append(f"scope.executed has checks not in scope.effective: {sorted(set(executed) - set(effective))}")
    if both := sorted(set(executed) & {e.get("check") for e in excluded}):
        out.append(f"scope: {both} both executed and excluded")
    if {e.get("check") for e in excluded} != set(CHECKS) - set(executed):
        out.append("scope.excluded is not exactly the checks that did not run")
    # a check outside effective was left out by the requested profile (profile) or, though requested, by the levels
    # it came to (gate_level); a check inside effective that did not run was turned off by the call (call_option) or
    # had nothing to be checked with (unavailable). A check effective holds beyond the request (a policy floor's) ran
    for e in excluded:
        check, reason, inside = e.get("check"), e.get("reason"), e.get("check") in effective
        if reason in ("profile", "gate_level") and inside:
            out.append(f"scope.excluded {check}: {reason} but it is in scope.effective")
        if reason in ("call_option", "unavailable") and not inside:
            out.append(f"scope.excluded {check}: {reason} but it is not in scope.effective")
        if not inside and reason == "profile" and check in asked:
            out.append(f"scope.excluded {check}: profile, but it is in the requested checks (gate_level)")
        if not inside and reason == "gate_level" and check not in asked:
            out.append(f"scope.excluded {check}: gate_level, but it is not in the requested checks (profile)")
        if e.get("module") != (mods.module_of(core.Check(e["check"])).id if e.get("check") in CHECKS else None):
            out.append(f"scope.excluded {e.get('check')}: module {e.get('module')!r} is not its module")
    reasons = {e.get("check"): e.get("reason") for e in excluded}
    if scope.get("coverage") != coverage_state(executed, reasons):
        out.append(f"scope.coverage is {scope.get('coverage')!r}, the scope says {coverage_state(executed, reasons)}")
    findings = verification.get("findings", [])
    if stray := sorted({f.get("check") for f in findings} - set(executed)):
        out.append(f"findings of checks that did not run: {stray}")
    counts = {fact.value: 0 for fact in core.Fact}
    provenance = {p.value: 0 for p in core.Provenance}
    for f in findings:
        if f.get("fact") in counts:
            counts[f["fact"]] += 1
        for e in f.get("evidence", []):
            if e.get("provenance") in provenance:
                provenance[e["provenance"]] += 1
    if verification.get("counts") != counts:
        out.append("verification.counts do not match the findings")
    if pred.get("evidence", {}).get("provenance") != provenance:
        out.append("evidence.provenance does not match the findings' evidence")
    decisions = [f.get("decision") for f in findings]
    facts = [f.get("fact") for f in findings]
    want = ("NOT_RUN" if not executed else "EMPTY" if not findings else "FAIL" if "block" in decisions
            else "UNKNOWN" if "unrecognized" in facts else "GAPS" if "flag" in decisions else "PASS")
    if verification.get("outcome") != want:
        out.append(f"verification.outcome is {verification.get('outcome')!r}, the findings say {want}")
    return out
