# ADR-001: Verification feedback is advice derived from a receipt, judged only by a new receipt

## Status

Proposed (draft pull request `feat/verification-feedback-v1`).

## Date

2026-10-26

## Context

buddie checks a text and states what it found in a receipt (receipt-v0, receipt-v1; [receipts.md](../receipts.md)).
Agents and orchestrators want to act on the findings: correct the quote, refresh the anchor, and try again. Without a
contract, each caller reads the receipt its own way, retries as often as it likes, and may treat its own retry, or
the agent's word that it fixed something, as the result. That would quietly turn buddie's verdicts into suggestions
and its `GAPS` and `EMPTY` into `PASS`.

Constraints that hold before and after this decision:

- buddie checks claims without a model (CONTRIBUTING.md); a verdict is never a model's.
- A receipt is buddie's statement of one check of one text; rendering changes nothing it found.
- receipt-v0 stays the default everywhere; receipt-v1 is asked for.
- buddie has no executor and no scheduler, and the evidence a check reads is chosen and collected under the protected
  policy ([policy.md](../policy.md), [architecture.md](../architecture.md)).

## Decision

1. **Feedback is a new versioned contract derived from receipt-v1 only** (`feedback-v1`, `buddie/feedback.py`). It
   copies each finding's identity, status and evidence references, adds a condition from a closed vocabulary and at
   most one bounded corrective action, and says it is advisory. It runs no check and reads no evidence. receipt-v0 is
   refused: it has no typed findings to derive from.
2. **The verdict authority does not move.** The disposition of a feedback is read from its receipt's outcome; only a
   new receipt of a changed text, produced by an independent verify run with no weaker scope, can reach `verified`.
   The agent's statements (digests, execution outcome, action reference) are recorded as assertions and decide
   nothing.
3. **Repair is bounded by contract, not by convention** (`buddie/repair.py`). One submission per feedback; every
   submission that reaches the content checks spends an iteration; the budget is 1 by default and at most 3; a
   correction may touch only the lines its actions name and must keep every verified claim; a submission carries only
   the fields of `repair-submission-v1`. Nothing retries implicitly.
4. **Ambiguous external effects end in reconciliation, not repetition.** An action about a `pr:`, `ci:` or `run:`
   claim is marked non-idempotent; an unknown execution outcome that still does not verify ends the chain as
   `reconciliation_required` with no action recommended.
5. **Decisions are taken on an in-process check, never on a receipt that was handed in.** Receipts are unsigned;
   a consistent `PASS` can be written for any text. `trace.start` and `repair.resolve` take a `verify.Assessment`
   the caller made itself; a receipt dict is refused. Feedback from a receipt file stays advice about that file. No
   cryptographic authentication is claimed.
6. **A corrected report is not a finished task.** The orchestrator may state task requirements (a check and a
   subject prefix) when a chain starts; a `PASS` that leaves one unmet is `requirements_unmet`, never `verified`.
7. **A repair rewrites; it does not add.** Scoped lines may be rewritten or deleted, never multiplied, except for
   `buddie:` disclosure lines, and a verified claim must stay where it was and still be supported there.
8. **The history is an append-only, hash-chained trace** (`trace-v1`, `buddie/trace.py`) that replays from its records
   alone and separates verifier findings, agent assertions, observed facts and derived decisions. It carries ids,
   digests and codes only. buddie does not persist it; callers keep its lines (a future Projects store among them).

## Consequences

- Callers get a deterministic, machine-readable loop with an explicit end, and the same receipt always yields the same
  feedback bytes.
- No existing interface or semantics change: verify, receipts, the hook, the journal, MCP and the CLI's existing
  commands are as before. One CLI command (`buddie feedback`) and three modules are added; no dependency.
- Feedback inherits the receipt's limits: claims no check detects get no feedback, and ids detect changes but do not
  authenticate (neither receipts nor feedback are signed).
- Line-scoped patches cannot express every correction (a claim moved to another paragraph is out of scope); that is
  accepted in exchange for a scope a reviewer can check.

## Alternatives considered

- **Let the hook loop until PASS.** Rejected: an implicit retry loop with no budget, and the gate would become an
  executor.
- **Put corrective actions into receipt-v1.** Rejected: it would mix what was established with what to do next and
  change a published contract.
- **Accept the agent's corrected text with its own claim of success.** Rejected: the agent is the party under check.
- **Persist the trace in buddie's journal.** Deferred: the journal is the gate's, shared across sessions and kept
  receipt-only by default; a Projects store with its own retention is the better home.

## Prior art

Design ideas were adapted, without copying code, from related projects of the same maintainer: a controlled-repair
protocol (one bounded patch attempt limited to target fields, merged and re-validated as a whole), a verifiable
decision-trace architecture (records prove existence, order and identity, not semantic truth), an attempt and retry
model (no retry method on the executor; an ambiguous effect state is classified, not retried), and a content-addressed
checkpoint store (immutable records linked by parent with contiguous sequence numbers).
