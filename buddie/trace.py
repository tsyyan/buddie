"""Verification decision trace v1: the history of one feedback chain, as append-only records that replay.

  verify -> feedback -> (submission -> [reverification] -> decision -> feedback)*

Each record is canonical JSON with `seq` (0, 1, 2, ... with no gap), `parent` (the record_id before it, None for
the first), `chain` (the first receipt's id: every record of a chain carries it, so records of another chain or
project do not mix in) and `record_id`, the sha256 of the rest. A list of records is a value: `append` returns a new
tuple and never changes the old one; `replay` rebuilds the chain's state from the records alone and refuses any
that do not follow (a changed byte, a dropped or reordered record, a second chain, a record after a terminal
disposition, a second submission for one feedback).

What a record says is kept apart by `basis`:
  verifier_finding  a receipt-v1 buddie made: its id, subject, outcome, coverage and executed checks
  agent_assertion   what the agent says it did (in a submission's `asserted`): never taken for fact
  observed          what the adapter computed itself (a submission's `observed`: digests, changed lines, scope)
  derived           what follows from the records before it (feedback, a decision): a recorded decision is a
                    decision under these rules, not proof that the text is true

A chain starts only from a verify.Assessment made in this process (`start`), never from a receipt read from a
file, an argument or an agent: a receipt is unsigned, so one that crossed a process boundary can be made to hold
together and say PASS. The trace itself is unsigned too: whoever can write its lines can write a consistent history.

Records hold identifiers, digests, counts and codes, never the text, a quotation, a page or a local path: a trace
can be kept beside a project's history without carrying its evidence. Persist it with `dumps` (one canonical JSON
object per line) wherever the caller keeps such lines; nothing here writes a file.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from buddie import feedback as fb
from buddie import receipts

V1 = "https://github.com/tsyyan/buddie#trace-v1"
KINDS = ("verification", "feedback", "submission", "reverification", "decision")
BASIS = {"verification": "verifier_finding", "reverification": "verifier_finding", "feedback": "derived",
         "decision": "derived", "submission": "agent_assertion+observed"}
# what may follow each kind of record
NEXT = {None: {"verification"}, "verification": {"feedback"}, "feedback": {"submission"},
        "submission": {"reverification", "decision"}, "reverification": {"decision"}, "decision": {"feedback"}}


class TraceError(ValueError):
    """Records that do not replay as one chain."""


def record_id(record: dict) -> str:
    return fb.digest(receipts.dumps({k: v for k, v in record.items() if k != "record_id"}).encode("utf-8"))


def append(records: tuple, kind: str, iteration: int, body: dict) -> tuple:
    """`records` with one more record (a new tuple; the old one is unchanged). The chain is the first record's."""
    if kind not in KINDS:
        raise TraceError(f"unknown record kind {kind!r}")
    last = records[-1] if records else None
    chain = last["chain"] if last else body.get("receipt")
    record = {"schema": V1, "seq": len(records), "parent": last["record_id"] if last else None, "chain": chain,
              "kind": kind, "basis": BASIS[kind], "iteration": iteration, "body": body}
    return (*records, {**record, "record_id": record_id(record)})


def receipt_body(receipt: dict) -> dict:
    """What a trace keeps of a receipt-v1: identity and conclusions, no finding text."""
    pred = receipt["predicate"]
    return {"receipt": fb.receipt_id(receipt), "subject": receipt["subject"][0]["digest"]["sha256"],
            "outcome": pred["verification"]["outcome"], "coverage": pred["scope"]["coverage"],
            "executed": list(pred["scope"]["executed"]), "numbers": pred["verification"]["numbers"],
            "counts": dict(pred["verification"]["counts"]), "producer": pred["producer"]["buddie"]}


def feedback_body(feedback: dict) -> dict:
    return {"feedback_id": feedback["feedback_id"], "parent": feedback["parent"],
            "source_receipt": feedback["source_receipt"]["id"], "iteration": feedback["iteration"],
            "iteration_limit": feedback["iteration_limit"], "disposition": feedback["disposition"],
            "actions": [a["action_id"] for a in feedback["recommended_actions"]],
            "open_findings": [f["finding_id"] for f in feedback["findings"] if f["actionable"]],
            "conditions": {c: sum(f["condition"] == c for f in feedback["findings"]) for c in fb.CONDITIONS},
            "task": {"status": feedback["task"]["status"],
                     "requirements": {r["requirement_id"]: r["status"] for r in feedback["task"]["requirements"]}}}


def assessed(assessment) -> dict:
    """The receipt-v1 of a verify.Assessment made in this process; TypeError for anything else (a receipt dict is
    not evidence that buddie made it)."""
    from buddie import verify
    if not isinstance(assessment, verify.Assessment):
        raise TypeError(f"a chain takes a verify.Assessment run in this process, not {type(assessment).__name__}: "
                        "a receipt from a file, an argument or an agent is unsigned and may be forged")
    return receipts.v1(assessment)


def start(assessment, *, iteration_limit: int = fb.DEFAULT_LIMIT, requirements=None) -> tuple[tuple, dict]:
    """A new chain from a verify.Assessment of the original text (repair.reverify makes one): (records, its first
    feedback). requirements: the task's, stated by the orchestrator (feedback.check_requirements)."""
    receipt = assessed(assessment)
    first = fb.from_receipt(receipt, iteration_limit=iteration_limit, requirements=requirements)
    records = append((), "verification", 0, receipt_body(receipt))
    return append(records, "feedback", 0, feedback_body(first)), first


@dataclass(frozen=True)
class State:
    """A chain as its records say it is."""
    chain: str
    iteration: int
    feedback_id: str               # the newest feedback
    disposition: str               # ... and its disposition
    terminal: bool
    answered: dict = field(default_factory=dict)   # feedback_id -> the submission's digest
    decisions: tuple = ()                          # each decision record's body, in order
    feedbacks: tuple = ()                          # each feedback record's body, in order

    @property
    def task(self) -> str:
        """not_stated, met or unmet: the newest feedback's task status (a verified report is not a done task)."""
        return self.feedbacks[-1]["task"]["status"]


def replay(records) -> State:
    """The State of a chain from its records alone; TraceError when they do not replay."""
    records = tuple(records)
    if not records:
        raise TraceError("no records")
    prev, chain, answered, decisions, feedbacks = None, records[0].get("chain"), {}, [], []
    current = None  # the newest receipt's id
    for i, r in enumerate(records):
        if not isinstance(r, dict) or r.get("schema") != V1:
            raise TraceError(f"record {i}: not a trace-v1 record")
        if r.get("record_id") != record_id(r):
            raise TraceError(f"record {i}: record_id is not its bytes' (changed after it was written)")
        if r.get("seq") != i or r.get("parent") != (prev["record_id"] if prev else None):
            raise TraceError(f"record {i}: out of sequence (dropped, reordered or from elsewhere)")
        if r.get("chain") != chain:
            raise TraceError(f"record {i}: belongs to another chain")
        kind = r.get("kind")
        if kind not in NEXT.get(prev["kind"] if prev else None, set()):
            raise TraceError(f"record {i}: a {kind} cannot follow a {prev['kind'] if prev else 'start'}")
        if r.get("basis") != BASIS.get(kind):
            raise TraceError(f"record {i}: basis {r.get('basis')!r} is not a {kind}'s")
        body = r["body"]
        if kind == "verification" and body.get("receipt") != chain:
            raise TraceError("the chain is not its first receipt's id")
        if kind in ("verification", "reverification"):
            current = body.get("receipt")
        if kind == "feedback":
            if body.get("source_receipt") != current:
                raise TraceError(f"record {i}: feedback is not of the newest receipt in the chain")
            if feedbacks and feedbacks[-1]["disposition"] in fb.TERMINAL:
                raise TraceError(f"record {i}: a feedback after a terminal disposition")
            if feedbacks and body.get("parent") != feedbacks[-1]["feedback_id"]:
                raise TraceError(f"record {i}: feedback does not follow the one before it")
            if body.get("iteration") != r.get("iteration") or body.get("disposition") not in fb.DISPOSITIONS:
                raise TraceError(f"record {i}: feedback iteration or disposition does not hold")
            if feedbacks and body["iteration"] != feedbacks[-1]["iteration"] + 1:
                raise TraceError(f"record {i}: iterations are not consecutive")
            if body["iteration"] > body.get("iteration_limit", 0):
                raise TraceError(f"record {i}: past the repair budget")
            if feedbacks and set(body["task"]["requirements"]) != set(feedbacks[0]["task"]["requirements"]):
                raise TraceError(f"record {i}: the task requirements changed within the chain")
            feedbacks.append(body)
        if kind == "submission":
            if feedbacks[-1]["disposition"] != "repair_requested":
                raise TraceError(f"record {i}: a submission to a feedback that asks for none")
            if body.get("feedback_id") != feedbacks[-1]["feedback_id"]:
                raise TraceError(f"record {i}: a submission to another feedback")
            answered[body["feedback_id"]] = body.get("submission")
        if kind == "decision":
            decisions.append(body)
        prev = r
    if prev["kind"] != "feedback":
        raise TraceError("the chain ends inside an iteration (a submission with no decision)")
    last = feedbacks[-1]
    return State(chain, last["iteration"], last["feedback_id"], last["disposition"],
                 last["disposition"] in fb.TERMINAL, answered, tuple(decisions), tuple(feedbacks))


def dumps(records) -> str:
    """One canonical JSON object per line, in order."""
    return "".join(receipts.dumps(r) + "\n" for r in records)


def loads(text: str) -> tuple:
    return tuple(json.loads(line) for line in text.splitlines() if line.strip())
