"""Bounded repair: one corrected text per feedback, kept within the feedback's scope, judged only by a new check.

An external agent reads a feedback-v1 (feedback.py), decides for itself whether and how to act, and hands back a
corrected text with a submission-v1:

  schema_version   SUBMISSION_V1
  feedback_id      the feedback it answers (the chain's newest, still repair_requested)
  iteration        that feedback's iteration
  artifact_before  sha256 (hex) of the text the feedback was made for, as the agent read it
  artifact_after   sha256 (hex) of the corrected text, as the agent sent it
  execution        what the agent says happened to any action outside the text: none, succeeded, failed, unknown
  action_ref       optional: the agent's own reference for what it did (a commit, a tool call id), at most 200
                   characters; recorded as its assertion, never resolved or trusted

No other field is accepted: a submission cannot set a disposition, an outcome, a finding, a budget or a task
requirement.

`resolve` takes the trace, the feedback, the submission, the original and corrected texts, and the verify.Assessment
of the corrected text from a verify run the caller made itself in this process (`reverify` makes one). It never
takes a receipt dict: receipts are unsigned, and one handed in by an agent, a file or a tool argument can be made to
hold together and say PASS (receipts.problems checks consistency, not origin). It decides:

  - the agent's digests are compared with the texts' own (a false one is its assertion, recorded and rejected)
  - an unchanged text is no repair
  - every original line the correction replaces or deletes, and every place it inserts at, must be in the scope of
    an action: the finding's line (its paragraph for quotes and numbers)
  - a correction rewrites; it does not add: within the scope, the lines that replace n lines may be at most n, plus
    `buddie:` disclosure lines, and only `buddie:` lines may be inserted. New claims, checked or not, cannot ride in
    on a repair
  - each verified claim (quotation, number, anchor) stays where it was: its subject must be in the lines that took
    the place of its own, and the new check must find it there, supported
  - the assessment must be of the corrected text (its subject), with at least the checks the source ran and a
    numbers mode at least as strict: no weaker verifier is accepted
  - the outcome is the new check's, never the agent's. What became of each finding is recorded as proved (the same
    claim, checked again and supported), corrected (a claim of the same check in the lines that took its place,
    supported), removed (none there) or still_open. None of these says the text is true, nor that the task is done:
    that is the feedback's task status, against requirements the orchestrator stated

Every submission that reaches these checks spends one iteration, accepted or not, so the loop ends within
`iteration_limit` submissions whatever the agent sends. A submission that does not belong to the chain (malformed,
an unknown field, a changed or foreign feedback, a feedback already answered, a closed chain) or a re-verification
that is not an Assessment raises SubmissionError and is not recorded: it spends nothing and changes nothing. The
same submission sent twice is refused the second time with the decision already recorded.

execution = "unknown" with an action whose claim is an effect in the world (pr:, ci:, run:) means the agent does not
know whether it acted: if the new check is not PASS, the disposition is reconciliation_required and no action is
recommended, since repeating one (a merge, a re-run) may not be idempotent. "succeeded" and "failed" are recorded
as said and change nothing: only the check decides.

`accept(records, final)` is the hand-in boundary: a chain's `verified` disposition covers the chain's last accepted
text and nothing else, so an orchestrator accepts a final report only if `accept` says so (the disposition is
`verified` and the report is byte for byte that text).

Nothing here calls a model, runs a check by itself (`reverify` is the caller's), or acts outside the values it
returns.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from buddie import feedback as fb
from buddie import receipts
from buddie import trace as tr

SUBMISSION_V1 = "https://github.com/tsyyan/buddie#repair-submission-v1"
EXECUTION = ("none", "succeeded", "failed", "unknown")
REQUIRED = frozenset({"schema_version", "feedback_id", "iteration", "artifact_before", "artifact_after", "execution"})
OPTIONAL = frozenset({"action_ref"})
ERRORS = ("malformed_submission", "unauthorized_field", "forged_feedback", "feedback_mismatch", "artifact_mismatch",
          "loop_closed", "duplicate_submission", "untrusted_receipt")
REJECTIONS = ("assertion_mismatch", "unchanged_artifact", "out_of_scope", "added_content",
              "verified_content_changed", "reverification_missing", "receipt_invalid", "receipt_mismatch",
              "weaker_verification")
HEX = re.compile(r"^[0-9a-f]{64}$")
DISCLOSURE = re.compile(r"^\s*buddie\s*:", re.I)  # the gate's own disclosure line (journal.DISCLOSED)


class SubmissionError(ValueError):
    """A submission refused before it touches the chain; `code` is one of ERRORS."""

    def __init__(self, code: str, message: str, decision: dict | None = None):
        super().__init__(f"{code}: {message}")
        self.code, self.decision = code, decision


@dataclass(frozen=True)
class Result:
    records: tuple       # the trace with this iteration appended
    feedback: dict       # the next feedback (terminal unless repair_requested)
    decision: dict       # the decision record's body


def submission(feedback: dict, original: str, corrected: str, *, execution: str = "none",
               action_ref: str | None = None) -> dict:
    """A submission-v1 for `corrected`, as an honest agent would make it (tests and simple callers)."""
    out = {"schema_version": SUBMISSION_V1, "feedback_id": feedback["feedback_id"],
           "iteration": feedback["iteration"], "artifact_before": fb.text_digest(original),
           "artifact_after": fb.text_digest(corrected), "execution": execution}
    return {**out, "action_ref": action_ref} if action_ref is not None else out


def check_submission(sub, feedback: dict) -> None:
    if not isinstance(sub, dict):
        raise SubmissionError("malformed_submission", "a submission is a JSON object")
    if extra := sorted(set(sub) - REQUIRED - OPTIONAL):
        raise SubmissionError("unauthorized_field", f"fields outside the submission contract: {extra}")
    if missing := sorted(REQUIRED - set(sub)):
        raise SubmissionError("malformed_submission", f"missing {missing}")
    if sub["schema_version"] != SUBMISSION_V1:
        raise SubmissionError("malformed_submission", f"schema_version is not {SUBMISSION_V1}")
    if sub["execution"] not in EXECUTION:
        raise SubmissionError("malformed_submission", f"execution is one of {EXECUTION}")
    if not all(isinstance(sub[k], str) and HEX.match(sub[k]) for k in ("artifact_before", "artifact_after")):
        raise SubmissionError("malformed_submission", "artifact digests are sha256 hex")
    ref = sub.get("action_ref")
    if ref is not None and (not isinstance(ref, str) or len(ref) > 200):
        raise SubmissionError("malformed_submission", "action_ref is a string of at most 200 characters")
    if sub["feedback_id"] != feedback["feedback_id"] or sub["iteration"] != feedback["iteration"]:
        raise SubmissionError("feedback_mismatch", "the submission answers another feedback or iteration")


def extent(lines: list[str], line: int, paragraph: bool) -> list[int]:
    """The lines (1-based) a finding at `line` stands on: the line, or its paragraph from it to the next blank."""
    if not 1 <= line <= len(lines):
        return []
    out = [line]
    while paragraph and out[-1] < len(lines) and lines[out[-1]].strip():  # lines[n] is line n + 1
        out.append(out[-1] + 1)
    return out


def scope(feedback: dict, original: str) -> set[int]:
    """The lines of `original` (1-based) the feedback's actions allow a correction to touch."""
    lines = original.split("\n")
    return {n for a in feedback["recommended_actions"]
            for n in extent(lines, a["target"]["line"], a["target"]["extent"] == "paragraph")}


def _opcodes(original: str, corrected: str):
    a, b = original.split("\n"), corrected.split("\n")
    return a, b, difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()


def changes(original: str, corrected: str) -> tuple[list[int], list[int]]:
    """(lines of `original` replaced or deleted, positions inserted after: 0 is before the first line)."""
    changed, inserted = [], []
    for op, i1, i2, _, _ in _opcodes(original, corrected)[2]:
        if op in ("replace", "delete"):
            changed += range(i1 + 1, i2 + 1)
        elif op == "insert":
            inserted.append(i1)
    return changed, inserted


def outside(allowed: set[int], changed: list[int], inserted: list[int]) -> list[int]:
    """Lines a correction touched outside `allowed` (an insertion is allowed next to an allowed line)."""
    out = [n for n in changed if n not in allowed]
    out += [n for n in inserted if n not in allowed and n + 1 not in allowed]
    return sorted(set(out))


def added(original: str, corrected: str) -> list[int]:
    """Lines of `corrected` (1-based) that add to the text rather than rewrite it: past as many lines as a block
    replaces, or inserted, and not a `buddie:` disclosure. A replace block's new lines are counted too, so lines
    slipped in alongside an allowed rewrite are not missed."""
    _, b, ops = _opcodes(original, corrected)
    out = []
    for op, i1, i2, j1, j2 in ops:
        if op not in ("replace", "insert"):
            continue
        content = [j for j in range(j1, j2) if not DISCLOSURE.match(b[j])]
        out += [j + 1 for j in content[i2 - i1:]]  # the first i2 - i1 rewrite the lines they replace
    return out


def mapping(original: str, corrected: str) -> dict[int, list[int]]:
    """Each line of `original` (1-based) -> the lines of `corrected` that took its place: itself when unchanged, the
    whole block that replaced it, none when deleted."""
    out: dict[int, list[int]] = {}
    for op, i1, i2, j1, j2 in _opcodes(original, corrected)[2]:
        for i in range(i1, i2):
            out[i + 1] = ([j1 + (i - i1) + 1] if op == "equal" else
                          list(range(j1 + 1, j2 + 1)) if op == "replace" else [])
    return out


def _paragraph_starts(lines: list[str], at) -> set[int]:
    out = set()
    for n in at:
        while n > 1 and lines[n - 2].strip():
            n -= 1
        out.add(n)
    return out


def _places(feedback_finding: dict, original: str, corrected: str, moved: dict) -> set[int] | None:
    """The lines of `corrected` where a finding of `original` now is (None: it has no line, so anywhere)."""
    if feedback_finding["line"] is None:
        return None
    lines = original.split("\n")
    old = extent(lines, feedback_finding["line"], feedback_finding["check"] in fb.PARAGRAPH)
    new = sorted({j for n in old for j in moved.get(n, [])})
    return set(new) | _paragraph_starts(corrected.split("\n"), new)  # a quote's line is its paragraph's first


def lost_verified(feedback: dict, original: str, corrected: str, receipt: dict | None = None) -> list[str]:
    """Verified findings that did not stay where they were: the claim (a quotation, a number, an anchor) is not in
    the lines that took the place of its own; with `receipt` (the corrected text's), no finding of the same check
    and subject is supported there. Moving a verified claim into another sentence or paragraph, or keeping a copy
    elsewhere while its place changes, is caught; the words around it on its own line are not judged."""
    moved, new_lines, out = mapping(original, corrected), corrected.split("\n"), []
    found = receipt["predicate"]["verification"]["findings"] if receipt else None
    for f in feedback["findings"]:
        if f["condition"] != "verified":
            continue
        places = _places(f, original, corrected, moved)
        if f["check"] != "work_claim":  # a work claim's subject is its kind, not its words
            region = new_lines if places is None else [new_lines[j - 1] for j in sorted(places)]
            if " ".join(f["subject"].split()) not in " ".join(" ".join(region).split()):
                out.append(f["finding_id"])
                continue
        if found is not None and not any(
                g["check"] == f["check"] and g["subject"] == f["subject"] and g["fact"] == "supported"
                and (places is None or g["line"] in places) for g in found):
            out.append(f["finding_id"])
    return out


def receipt_rejection(receipt, feedback: dict, after: str) -> str | None:
    if receipt is None:
        return "reverification_missing"
    try:
        fb.check_receipt(receipt)
    except fb.InvalidReceipt:
        return "receipt_invalid"
    if receipt["subject"][0]["digest"]["sha256"] != after:
        return "receipt_mismatch"
    want = feedback["verification_requirements"]
    pred = receipt["predicate"]
    if (not set(want["executed_at_least"]) <= set(pred["scope"]["executed"])
            or fb.NUMBERS_RANK[pred["verification"]["numbers"]] < fb.NUMBERS_RANK[want["numbers_at_least"]]):
        return "weaker_verification"
    return None


def _requirements(feedback: dict) -> list[dict]:
    return [{"check": r["check"], "subject_prefix": r["subject_prefix"]} for r in feedback["task"]["requirements"]]


def follow(previous: dict, *, reconcile: bool = False) -> dict:
    """The next feedback when a submission was rejected: the same findings, one iteration later, so the budget is
    spent (equal to feedback.from_receipt of the same receipt at the next iteration)."""
    body = {k: v for k, v in previous.items() if k != "feedback_id"}
    iteration = previous["iteration"] + 1
    disposition = ("reconciliation_required" if reconcile else
                   "budget_exhausted" if iteration >= previous["iteration_limit"] else "repair_requested")
    findings = [dict(f) for f in previous["findings"]]
    actions = previous["recommended_actions"]
    if disposition != "repair_requested":
        actions = []
        for f in findings:
            f["action_id"] = None
    body.update(parent=previous["feedback_id"], iteration=iteration, disposition=disposition, findings=findings,
                recommended_actions=list(actions))
    return {"feedback_id": fb.feedback_id(body), **body}


def _resolved(feedback: dict, receipt: dict | None, original: str, corrected: str) -> dict:
    new = receipt["predicate"]["verification"]["findings"] if receipt else None
    moved, out = mapping(original, corrected), {}
    for f in feedback["findings"]:
        if not f["action_id"]:
            continue
        if new is None:
            out[f["finding_id"]] = "still_open"
            continue
        places = _places(f, original, corrected, moved)
        nearby = [g for g in new if g["check"] == f["check"] and (places is None or g["line"] in places)]
        same = [g for g in nearby if g["subject"] == f["subject"]]
        if same:
            out[f["finding_id"]] = "proved" if all(g["fact"] == "supported" for g in same) else "still_open"
        elif nearby:
            out[f["finding_id"]] = "corrected" if all(g["fact"] == "supported" for g in nearby) else "still_open"
        else:
            out[f["finding_id"]] = "removed"
    return out


def admit(state, feedback: dict, sub, *, original: str) -> None:
    """The refusals `resolve` makes before it looks at a re-verification (SubmissionError), for a caller that would
    rather not run one for a submission the chain `state` (trace.replay) refuses anyway (mcp.feedback_resolve)."""
    if fb.problems(feedback):
        raise SubmissionError("forged_feedback", "; ".join(fb.problems(feedback)))
    if feedback["chain"] != state.chain:
        raise SubmissionError("feedback_mismatch", "the feedback belongs to another chain")
    if feedback["feedback_id"] in state.answered:
        done = next((d for d in state.decisions if d["feedback_id"] == feedback["feedback_id"]), None)
        raise SubmissionError("duplicate_submission", "this feedback was already answered", done)
    if state.terminal:
        raise SubmissionError("loop_closed", f"the chain is {state.disposition}: no repair is taken")
    if feedback["feedback_id"] != state.feedback_id:
        raise SubmissionError("feedback_mismatch", "not the chain's open feedback")
    check_submission(sub, feedback)
    if fb.text_digest(original) != feedback["source_subject_digest"]:
        raise SubmissionError("artifact_mismatch", "the original text is not the one the feedback was made for")


def resolve(records, feedback: dict, sub: dict, *, original: str, corrected: str, assessment=None) -> Result:
    """One iteration of the chain `records` (see the module's docstring). assessment: the verify.Assessment of
    `corrected`, from a verify run made in this process. Returns the new records, the next feedback and the
    decision; raises SubmissionError for a submission or re-verification that does not belong to the chain."""
    admit(tr.replay(records), feedback, sub, original=original)
    before = feedback["source_subject_digest"]
    try:
        receipt = tr.assessed(assessment) if assessment is not None else None
    except TypeError as error:
        raise SubmissionError("untrusted_receipt", str(error)) from None

    after = fb.text_digest(corrected)
    changed, inserted = changes(original, corrected)
    stray = outside(scope(feedback, original), changed, inserted)
    grown = added(original, corrected)
    rejection = None
    if sub["artifact_before"] != before or sub["artifact_after"] != after:
        rejection = "assertion_mismatch"
    elif after == before:
        rejection = "unchanged_artifact"
    elif stray:
        rejection = "out_of_scope"
    elif grown:
        rejection = "added_content"
    elif lost_verified(feedback, original, corrected):
        rejection = "verified_content_changed"
    else:
        rejection = receipt_rejection(receipt, feedback, after)
        if rejection is None and lost_verified(feedback, original, corrected, receipt):
            rejection = "verified_content_changed"
    accepted = rejection is None
    reconcile = sub["execution"] == "unknown" and any(not a["idempotent"] for a in feedback["recommended_actions"])

    iteration = feedback["iteration"]
    records = tr.append(tuple(records), "submission", iteration, {
        "feedback_id": feedback["feedback_id"],
        "submission": fb.digest(receipts.dumps(sub).encode("utf-8")),
        "asserted": {"artifact_before": sub["artifact_before"], "artifact_after": sub["artifact_after"],
                     "execution": sub["execution"], "action_ref": sub.get("action_ref")},
        "observed": {"artifact_before": before, "artifact_after": after, "changed_lines": changed,
                     "inserted_after": inserted, "out_of_scope": stray, "added_lines": grown,
                     "receipt": fb.receipt_id(receipt) if receipt is not None else None,
                     "status": "accepted" if accepted else "rejected", "rejection": rejection}})
    if accepted:
        records = tr.append(records, "reverification", iteration, tr.receipt_body(receipt))
        following = fb.from_receipt(receipt, iteration=iteration + 1, iteration_limit=feedback["iteration_limit"],
                                    parent=feedback["feedback_id"], chain=feedback["chain"], reconcile=reconcile,
                                    requirements=_requirements(feedback))
    else:
        following = follow(feedback, reconcile=reconcile)
    decision = {"feedback_id": feedback["feedback_id"], "status": "accepted" if accepted else "rejected",
                "rejection": rejection, "receipt": fb.receipt_id(receipt) if accepted else None,
                "outcome": receipt["predicate"]["verification"]["outcome"] if accepted else None,
                "resolved": _resolved(feedback, receipt if accepted else None, original, corrected),
                "task": following["task"]["status"],
                "disposition": following["disposition"], "terminal": following["disposition"] in fb.TERMINAL,
                "next_feedback": following["feedback_id"]}
    records = tr.append(records, "decision", iteration, decision)
    records = tr.append(records, "feedback", iteration + 1, tr.feedback_body(following))
    return Result(records, following, decision)


ACCEPT_REFUSALS = ("not_verified", "artifact_mismatch")


def accepted_artifact(records) -> str:
    """The sha256 (hex) of the chain's last independently accepted text: the subject of its newest verification or
    re-verification record. A rejected submission records no re-verification, so it never moves this."""
    tr.replay(records)
    return next(r["body"]["subject"] for r in reversed(tuple(records))
                if r["kind"] in ("verification", "reverification"))


def accept(records, final: str) -> dict:
    """Whether `final`, the report an agent hands in, is the text the chain verified: the disposition is `verified`
    and `final` is byte for byte the chain's last accepted text. A chain's `verified` is about that text only; a
    different one (edited after the chain closed, a refused repair handed in anyway) is refused here, and so is any
    text of a chain that is not `verified`. Reads the records and decides; records nothing, runs no check.
    reason: None when accepted, else one of ACCEPT_REFUSALS."""
    state = tr.replay(records)
    want, got = accepted_artifact(records), fb.text_digest(final)
    reason = ("not_verified" if state.disposition != "verified" else
              "artifact_mismatch" if got != want else None)
    return {"accepted": reason is None, "reason": reason, "disposition": state.disposition, "task": state.task,
            "artifact_sha256": want, "final_sha256": got}


def reverify(text: str, **kw):
    """A fresh verify.Assessment of `text` (verify.assessment's arguments), run in this process: what trace.start
    and `resolve` take. Give the corrected text the options the original was checked with, or a stricter set."""
    from buddie import verify
    return verify.assessment(text, **kw)
