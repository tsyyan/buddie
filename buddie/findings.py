"""The rows verify gathers (quotes, numbers, anchors, work claims) as core Findings, and what was left unchecked as
core Coverage. This is the one place that knows both the checkers' verdict words and the core types: core.py knows
no checker, and the checkers know no core type.

Every table here is exhaustive over the verdicts its checker returns (tests/test_outcome.py and tests/test_core.py
hold them equal); a word missing from a table becomes Fact.UNRECOGNIZED, which is never support.
"""
from __future__ import annotations

from buddie import anchors as anc
from buddie import effects as eff
from buddie.core import Check, Coverage, EvidenceRef, Fact, Finding, Provenance, ReasonCode, Skip

S, C, N, U = Fact.SUPPORTED, Fact.CONTRADICTED, Fact.NO_CLAIM, Fact.UNDETERMINED
QUOTE_FACTS = {"FOUND": S, "FOUND_NORMALIZED": S, "NOT_A_QUOTE": N, "HIDDEN_ONLY": U, "FOUND_IN_COPY": U,
               "UNCERTAIN": U, "SOURCE_UNAVAILABLE": U, "NO_SOURCE": U, "NOT_FOUND": C}
NUMBER_FACTS = {"FOUND": S, "FOUND_NORMALIZED": S, "FOUND_ROUNDED": S, "NO_CONTEXT": U, "UNCERTAIN": U,
                "SOURCE_UNAVAILABLE": U, "NOT_FOUND": C}
STATUS_FACTS = {"HOLDS": S, "BROKEN": C, "UNCHECKABLE": U, "UNSUPPORTED": U}  # anchors and work claims

REASONS = {
    "FOUND": ReasonCode.FOUND, "FOUND_NORMALIZED": ReasonCode.FOUND_NORMALIZED,
    "FOUND_ROUNDED": ReasonCode.FOUND_NORMALIZED, "NOT_FOUND": ReasonCode.NOT_IN_SOURCE,
    "UNCERTAIN": ReasonCode.AMBIGUOUS_MISS, "NO_CONTEXT": ReasonCode.VALUE_WITHOUT_CONTEXT,
    "HIDDEN_ONLY": ReasonCode.ONLY_HIDDEN, "FOUND_IN_COPY": ReasonCode.ONLY_IN_COPY,
    "SOURCE_UNAVAILABLE": ReasonCode.SOURCE_UNAVAILABLE, "NO_SOURCE": ReasonCode.NO_SOURCE,
    "NOT_A_QUOTE": ReasonCode.NOT_A_CITATION, "HOLDS": ReasonCode.HOLDS, "BROKEN": ReasonCode.BROKEN,
    "UNCHECKABLE": ReasonCode.UNCHECKABLE, "UNSUPPORTED": ReasonCode.UNSUPPORTED,
}


def quote_fact(verdict: str) -> Fact:
    return QUOTE_FACTS.get(verdict, Fact.UNRECOGNIZED)


def number_fact(verdict: str) -> Fact:
    return NUMBER_FACTS.get(verdict, Fact.UNRECOGNIZED)


def status_fact(status: str) -> Fact:
    return STATUS_FACTS.get(status, Fact.UNRECOGNIZED)


def _reason(word: str, fact: Fact) -> ReasonCode:
    return ReasonCode.UNKNOWN_VERDICT if fact is Fact.UNRECOGNIZED else REASONS[word]


def _snapshot(row: dict) -> tuple[EvidenceRef, ...]:
    """The snapshot a quote or a number was judged on. Its origin is UNKNOWN: the store is a directory that a
    fetch in this call, an earlier `snap`, or anyone with write access may have filled."""
    if not row.get("sha256"):
        return ()
    return (EvidenceRef("snapshot", row.get("url") or "", Provenance.UNKNOWN, digest=row["sha256"],
                        source=row.get("provenance"), observed_at=row.get("fetched_at")),)


def quote(row: dict) -> Finding:
    fact = quote_fact(row["verdict"])
    return Finding(Check.QUOTE, row.get("quote", ""), row["verdict"], fact, _reason(row["verdict"], fact),
                   _snapshot(row), row.get("line"), row.get("error"), tuple(row.get("doubts") or ()))


def number(row: dict) -> Finding:
    fact = number_fact(row["verdict"])
    return Finding(Check.NUMBER, row.get("text", ""), row["verdict"], fact, _reason(row["verdict"], fact),
                   _snapshot(row), row.get("line"), None, tuple(row.get("doubts") or ()))


def anchor_check(anchor: str) -> Check:
    """Which check an anchor is, by its form alone (the claim's syntax, not the checker's message)."""
    if eff.PR.match(anchor):
        return Check.PR_ANCHOR
    if eff.CI.match(anchor):
        return Check.CI_ANCHOR
    if eff.RUN.match(anchor):
        return Check.RUN_ANCHOR
    if anchor.startswith("choice:"):
        return Check.CHOICE_ANCHOR
    if anc.FILE_SHA.match(anchor):
        return Check.FILE_ANCHOR
    if anc.FILE_AT.match(anchor):
        return Check.COMMIT_ANCHOR
    if anc.FACT.match(anchor):
        return Check.FACT_ANCHOR
    return Check.OTHER_ANCHOR


# where an anchor's evidence lives, and how far its origin is known, when the check reached it
ANCHOR_EVIDENCE = {
    Check.FILE_ANCHOR: ("file", Provenance.AGENT_WRITABLE),        # the working tree
    Check.COMMIT_ANCHOR: ("git_commit", Provenance.AGENT_WRITABLE),  # local history: the agent can commit
    Check.PR_ANCHOR: ("github_api", Provenance.COLLECTOR_OBSERVED),  # asked of GitHub during this check
    Check.CI_ANCHOR: ("github_api", Provenance.COLLECTOR_OBSERVED),
    Check.RUN_ANCHOR: ("transcript", Provenance.CALLER_SUPPLIED),   # the session log the caller pointed to
    Check.CHOICE_ANCHOR: ("journal", Provenance.AGENT_WRITABLE),    # buddie's journal, a file on the same machine
}


def anchor(row: dict) -> Finding:
    check, status = anchor_check(row["anchor"]), row["status"]
    fact = status_fact(status)
    if fact is Fact.UNRECOGNIZED:
        reason = ReasonCode.UNKNOWN_VERDICT
    elif check is Check.OTHER_ANCHOR:
        reason = ReasonCode.NOT_AN_ANCHOR
    elif check is Check.FACT_ANCHOR:
        reason = ReasonCode.NOT_COMPUTED
    else:
        reason = REASONS[status]
    evidence = ()
    if fact in (Fact.SUPPORTED, Fact.CONTRADICTED) and check in ANCHOR_EVIDENCE:
        kind, provenance = ANCHOR_EVIDENCE[check]
        where = f"{row['repo']}:{row['anchor']}" if row.get("repo") else row["anchor"]
        evidence = (EvidenceRef(kind, where, provenance, observed_at=row.get("at")),)
    return Finding(check, row["anchor"], status, fact, reason, evidence, row.get("line"), row.get("why"))


def work_claim(row: dict) -> Finding:
    status = row["status"]
    fact = status_fact(status)
    evidence = ()
    if fact in (Fact.SUPPORTED, Fact.CONTRADICTED):  # judged against the queue and messages files in the repo
        evidence = (EvidenceRef("queue", row.get("anchor") or row["kind"], Provenance.AGENT_WRITABLE),)
    return Finding(Check.WORK_CLAIM, row["kind"], status, fact, _reason(status, fact), evidence, row.get("line"),
                   row.get("why"))


def from_rows(quotes=(), anchors=(), claims=(), numbers=()) -> list[Finding]:
    return ([quote(r) for r in quotes] + [number(r) for r in numbers] + [anchor(r) for r in anchors]
            + [work_claim(c) for c in claims])


def coverage(findings: list[Finding], *, quotes: bool, numbers: str, mandate_off: bool, mandate_config: bool,
             short_quotes: int = 0, unlinked_terms: int = 0, unanchored_lines: int = 0,
             prose_claims: int = 0) -> Coverage:
    checked: dict[Check, int] = {}
    for f in findings:
        checked[f.check] = checked.get(f.check, 0) + 1
    skipped = []
    if not quotes:
        skipped.append(Skip("quotes", "off: anchors only"))
    if not quotes or numbers == "off":
        skipped.append(Skip("numbers", "off"))
    if mandate_off:
        skipped.append(Skip("work_claims", "off"))
    elif not mandate_config:
        skipped.append(Skip("work_claims", "no buddie.toml [mandate] in the repos", capability=False))
    for what, why, n in (("short_quotes", "under the minimum length", short_quotes),
                         ("unlinked_terms", "words in quotation marks with no link and no speaker", unlinked_terms),
                         ("unanchored_count_lines", "a count with no anchor", unanchored_lines),
                         ("prose_work_claims", "a work claim with no pr:/ci:/run: anchor", prose_claims)):
        if n:
            skipped.append(Skip(what, why, n, capability=False))
    return Coverage(checked, tuple(skipped))
