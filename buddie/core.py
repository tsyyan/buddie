"""buddie's internal contract for what a check found: typed findings, kept apart from the modules that make them.

A check (a quote against its page, an anchor against a repo, a claim against the queue) reports a domain verdict in
its own words: FOUND, HOLDS, BROKEN, SOURCE_UNAVAILABLE. This module says what such a verdict means, in three
separate answers that the receipt used to fold into one word:

  Fact         what the check concluded about the claim: SUPPORTED, CONTRADICTED, NO_CLAIM (checked, and the text
               claims nothing there: a title in quotation marks), UNDETERMINED (not checked to the end), or
               UNRECOGNIZED (a verdict this code does not know: never taken for support)
  Sufficiency  whether the evidence was enough to conclude: follows from the Fact, kept as its own answer so that
               code asking "can I rely on this?" does not have to know every Fact
  Decision     what a Policy does with the finding: BLOCK, FLAG (pass it on with the gap said) or ALLOW

The Outcome of a set of findings is FAIL (a finding is blocked), UNKNOWN (a verdict was not recognized, or nothing
was checked), GAPS (something was flagged, or a check was off) or PASS. receipt-v0 keeps its own four words
(FAIL, GAPS, PASS, EMPTY); `v0_outcome` gives them, unchanged, from the same findings.

Evidence names where a finding's bytes came from and how far that is known (Provenance). A digest names the bytes,
not who made them: a snapshot's sha256 says which bytes were judged, never that a publisher served them.

Standard library only; nothing here imports a checker, the hook, the MCP servers or the CLI (tests/test_core.py).
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum


class Check(str, Enum):
    QUOTE = "quote"
    NUMBER = "number"
    FILE_ANCHOR = "file_anchor"        # path#sha256
    COMMIT_ANCHOR = "commit_anchor"    # path@commit
    FACT_ANCHOR = "fact_anchor"        # name=value
    PR_ANCHOR = "pr_anchor"
    CI_ANCHOR = "ci_anchor"
    RUN_ANCHOR = "run_anchor"
    CHOICE_ANCHOR = "choice_anchor"
    WORK_CLAIM = "work_claim"          # step done, verdict, consent, next step, queue at a commit
    OTHER_ANCHOR = "other_anchor"      # text in an anchor's place that is no anchor form


class Fact(str, Enum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    NO_CLAIM = "no_claim"
    UNDETERMINED = "undetermined"
    UNRECOGNIZED = "unrecognized"


class Sufficiency(str, Enum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    UNKNOWN = "unknown"


class Decision(str, Enum):
    BLOCK = "block"
    FLAG = "flag"
    ALLOW = "allow"


class Outcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    GAPS = "GAPS"
    UNKNOWN = "UNKNOWN"


class ReasonCode(str, Enum):
    """Why a finding has its Fact, for code to act on without reading the message."""
    FOUND = "found"                              # the words or the value are on the page
    FOUND_NORMALIZED = "found_normalized"        # ... after normalizing spelling, punctuation, scale or rounding
    NOT_IN_SOURCE = "not_in_source"              # the source was read and the claim is not in it
    AMBIGUOUS_MISS = "ambiguous_miss"            # not in it, but the miss may not be the report's fault (doubts)
    VALUE_WITHOUT_CONTEXT = "value_without_context"  # the value is there, but none of the sentence's words near it
    ONLY_HIDDEN = "only_hidden"                  # only in markup a reader does not see
    ONLY_IN_COPY = "only_in_copy"                # only in bytes that are not the cited page
    SOURCE_UNAVAILABLE = "source_unavailable"    # the cited source could not be read
    NO_SOURCE = "no_source"                      # the claim cites nothing
    NOT_A_CITATION = "not_a_citation"            # the text shows it is not somebody's words
    HOLDS = "holds"                              # an anchor or a work claim checked out
    BROKEN = "broken"                            # ... and contradicts what it names
    UNCHECKABLE = "uncheckable"                  # ... could not be checked here (no repo, offline, refused)
    NOT_COMPUTED = "not_computed"                # fact=: computing it would run the repo's code (never done)
    UNSUPPORTED = "unsupported"                  # a work claim with no evidence given for it
    NOT_AN_ANCHOR = "not_an_anchor"              # text in an anchor's place that matches no anchor form
    UNKNOWN_VERDICT = "unknown_verdict"          # a verdict or status this code does not know


class Provenance(str, Enum):
    """How far the origin of a piece of evidence is known. Only what the check can establish is claimed."""
    CALLER_SUPPLIED = "caller_supplied"          # handed in by whoever runs the check (a transcript path, a config)
    AGENT_WRITABLE = "agent_writable"            # a place the agent under check can write (the repo, its history,
                                                 # buddie's own journal and snapshot store on the same machine)
    COLLECTOR_OBSERVED = "collector_observed"    # fetched by this check from a third party during the call
    UNKNOWN = "unknown"                          # bytes whose origin this check cannot tell


@dataclass(frozen=True)
class EvidenceRef:
    """What a finding was judged on. `digest` is the sha256 of those bytes when the check has it: it identifies
    them, it says nothing of who produced them. `source` repeats the origin a record claims for itself (verbatim's
    publisher / archive / copy / relay), which Provenance does not vouch for."""
    kind: str                     # snapshot, file, git_commit, github_api, transcript, journal, queue
    locator: str                  # a URL, a repo path, an anchor
    provenance: Provenance
    digest: str | None = None
    source: str | None = None
    observed_at: str | None = None


@dataclass(frozen=True)
class Finding:
    check: Check
    subject: str                  # the quote, the number, the anchor, the claim's kind
    verdict: str                  # the domain verdict, as the check gave it
    fact: Fact
    reason: ReasonCode
    evidence: tuple[EvidenceRef, ...] = ()
    line: int | None = None
    message: str | None = None    # for a person; code reads `reason`, never this
    details: tuple[str, ...] = ()  # structured qualifiers the check gave (doubts), as given

    @property
    def sufficiency(self) -> Sufficiency:
        if self.fact in (Fact.SUPPORTED, Fact.CONTRADICTED, Fact.NO_CLAIM):
            return Sufficiency.SUFFICIENT
        if self.fact is Fact.UNDETERMINED:
            return Sufficiency.INSUFFICIENT
        return Sufficiency.UNKNOWN


@dataclass(frozen=True)
class Skip:
    """Something the check did not judge, and why: a capability that was off, or text it set aside."""
    what: str
    reason: str
    count: int | None = None
    capability: bool = True       # True: a whole check was off, so its absence of findings proves nothing


@dataclass(frozen=True)
class Coverage:
    checked: dict[Check, int] = field(default_factory=dict)
    skipped: tuple[Skip, ...] = ()

    @property
    def capabilities_off(self) -> tuple[Skip, ...]:
        return tuple(s for s in self.skipped if s.capability)


@dataclass(frozen=True)
class Policy:
    """What blocks. receipt-v0's rule: a contradicted quote, anchor or work claim blocks; a contradicted number
    blocks only with numbers="fail" (`block_numbers`), and is flagged otherwise; anything undetermined or
    unrecognized is flagged; support and no-claim are allowed."""
    block_numbers: bool = False

    def decide(self, finding: Finding) -> Decision:
        if finding.fact is Fact.CONTRADICTED:
            return Decision.BLOCK if finding.check is not Check.NUMBER or self.block_numbers else Decision.FLAG
        if finding.fact in (Fact.UNDETERMINED, Fact.UNRECOGNIZED):
            return Decision.FLAG
        return Decision.ALLOW


def outcome(findings: Iterable[Finding], coverage: Coverage | None = None, policy: Policy = Policy()) -> Outcome:
    """The Outcome of a whole check. Stricter than receipt-v0: nothing checked, or a verdict nobody recognizes, is
    UNKNOWN; a PASS with a check switched off is GAPS, since the absence of its findings proves nothing."""
    findings = list(findings)
    decisions = [policy.decide(f) for f in findings]
    if Decision.BLOCK in decisions:
        return Outcome.FAIL
    if not findings or any(f.fact is Fact.UNRECOGNIZED for f in findings):
        return Outcome.UNKNOWN
    if Decision.FLAG in decisions or (coverage is not None and coverage.capabilities_off):
        return Outcome.GAPS
    return Outcome.PASS


def v0_outcome(findings: Iterable[Finding], policy: Policy = Policy()) -> str:
    """receipt-v0's word for the same findings, as verify has always given it: EMPTY with nothing to check, FAIL on a
    block, GAPS on any flag (an unrecognized verdict among them), PASS otherwise. A check that was off does not
    show here (v0 never said it); Coverage carries it."""
    findings = list(findings)
    if not findings:
        return "EMPTY"
    decisions = [policy.decide(f) for f in findings]
    if Decision.BLOCK in decisions:
        return "FAIL"
    if Decision.FLAG in decisions:
        return "GAPS"
    return "PASS"
