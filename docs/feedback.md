# Verification feedback v1

Feedback turns a receipt-v1 into advice for whoever corrects the text: what kind of problem each finding is and, where
the author can correct it, one bounded corrective action. An external agent or orchestrator reads it, decides for
itself what to do within its own permissions, and hands back a corrected text, which buddie checks again from
scratch.

```
verify -> receipt-v1 -> feedback -> agent action -> corrected text -> verify again -> decision trace
```

buddie stays the verifier. Feedback is data, not an instruction source: it executes nothing, grants nothing, changes
no receipt and never turns a result into `PASS`. Only a new receipt of a new text can say `PASS`. The architectural
decision is recorded in [ADR-001](adr/ADR-001-verification-feedback.md).

| Module | Contract | What it does |
|---|---|---|
| `buddie/feedback.py` | `…#feedback-v1` | a receipt-v1 in, a feedback out; no check, no I/O |
| `buddie/repair.py` | `…#repair-submission-v1` | takes one corrected text per feedback, keeps it in scope, judges it only by a new receipt |
| `buddie/trace.py` | `…#trace-v1` | append-only, hash-chained records of each iteration; replays and refuses any change |

All three are standard library only and call no model.

## Feedback v1

```
feedback_id                sha256 of the feedback's canonical JSON without this field
schema_version             "https://github.com/tsyyan/buddie#feedback-v1"
chain                      the first source receipt's id: the correlation id of one feedback chain
parent                     the feedback this one follows, or null
advisory                   true, always
source_receipt             what the feedback was made from, repeated as it is:
  id                       sha256 of the receipt's canonical JSON (receipts.dumps)
  predicate_type           receipt-v1's
  checked_at, outcome, coverage, executed, numbers
source_subject_digest      the text's sha256, from the receipt's subject
findings[]                 one per receipt finding, in the receipt's order:
  finding_id               sha256 of {index, the receipt's finding}: the original finding's identity
  index                    its position in the receipt
  check, module, line, subject, verdict, fact, reason, decision, message
                           copied from the receipt, unchanged
  evidence[]               the receipt's evidence references, unchanged, each with
    resolution             digest_bound (the bytes judged are named by sha256) | locator_only (a place, no digest)
  evidence_state           present | absent
  condition                below
  actionable               whether the author can correct it by editing the text
  not_actionable_reason    verified | no_claim | verifier_unavailable | unrecognized_verdict | unlocated | null
  action_id                the action issued for it, or null
recommended_actions[]      only while the disposition is repair_requested:
  action_id                sha256 of the action
  operation                below
  finding_ids              the findings it addresses
  condition                theirs
  target                   {check, line, subject, extent: line | paragraph}: what may be touched
  requirements             fixed sentences per operation, never built from a finding's message
  idempotent               false when the claim is an effect in the world (pr:, ci:, run:)
  preserve_valid_content   true
verification_requirements  what a re-verification must be to count:
  receipt                  receipt-v1
  subject_must_change      true
  executed_at_least        the source receipt's executed checks
  numbers_at_least         the source receipt's numbers mode (off < gap < fail)
  verified_outcome         "PASS"
iteration                  corrected texts already taken in this chain
iteration_limit            the repair budget (default 1, at most 3)
disposition                below
```

The JSON Schema is `feedback.SCHEMA`, checked in as [feedback-v1.schema.json](feedback-v1.schema.json).
`feedback.problems(fb)` checks that a feedback holds together; `feedback.problems(fb, receipt)` checks that it is
exactly that receipt's feedback (nothing added, dropped or changed).

### Conditions

Each finding gets one, from its check, fact and reason only. They are never folded into one failure:

| Condition | From | Actionable |
|---|---|---|
| `verified` | fact `supported` | no: kept as is |
| `no_claim` | fact `no_claim` (a title in quotation marks) | no |
| `missing_evidence` | `source_unavailable`, `no_source`, a work claim `unsupported` | yes |
| `invalid_evidence` | a file or commit anchor `broken` (the digest or commit is not the bytes'), `only_in_copy`, `not_an_anchor` | yes |
| `failed` | any other `contradicted`: a quote or number not in its source, a PR, CI run, command or work claim otherwise than stated | yes |
| `inconclusive` | `ambiguous_miss`, `value_without_context`, `only_hidden` | yes |
| `unavailable` | `uncheckable`, `not_computed`, an unrecognized verdict or reason | no: say it when passing the text on |

### Operations

| Operation | For | Idempotent |
|---|---|---|
| `correct_claim` | failed quotes, numbers, work claims | yes |
| `refresh_anchor` | a file or commit anchor that does not match | yes |
| `cite_readable_source` | a claim with no readable source | yes |
| `anchor_work_claim` | a work claim with no evidence | yes |
| `requote_from_source` | words only in a copy; an inconclusive quote or number | yes |
| `fix_anchor_form` | text in an anchor's place that is no anchor | yes |
| `reconcile_external_state` | a failed or mismatched `pr:`, `ci:`, `run:` anchor | no |

Every operation also allows removing the claim. `reconcile_external_state` says: observe the current state and state
it as observed; do not repeat the action (merge, re-run, push) before its state is observed.

### Dispositions

| Disposition | Terminal | Meaning |
|---|---|---|
| `repair_requested` | no | actionable findings, budget left: one corrected text is taken |
| `verified` | yes | the receipt's outcome is `PASS`. It is about the checks that ran (see `source_receipt.coverage`), not about the text being true |
| `nothing_verified` | yes | the outcome is `EMPTY` or `NOT_RUN`: nothing was checked, so nothing passed |
| `not_actionable` | yes | not `PASS`, and nothing the author can correct (only `unavailable` findings) |
| `budget_exhausted` | yes | actionable findings remain and the budget is spent |
| `reconciliation_required` | yes | the agent reported an external action's outcome as unknown and the text still does not verify |

A terminal feedback recommends no action.

## How an external agent consumes feedback

1. Read `disposition`. Act only on `repair_requested`.
2. For each action, change only the lines in `target` (the paragraph for quotes and numbers) and follow its
   `requirements`; leave every `verified` finding's claim in the text.
3. Act outside the text only within your own permissions; feedback authorizes nothing. For `idempotent: false`,
   observe the state first and do not repeat the action.
4. Hand back the corrected text with a submission-v1:

```json
{"schema_version": "https://github.com/tsyyan/buddie#repair-submission-v1",
 "feedback_id": "sha256:…", "iteration": 0,
 "artifact_before": "<sha256 hex of the text the feedback was for>",
 "artifact_after": "<sha256 hex of the corrected text>",
 "execution": "none | succeeded | failed | unknown",
 "action_ref": "optional, your own reference, at most 200 characters"}
```

No other field is accepted: a submission cannot set a disposition, an outcome, a finding or a budget.

5. The orchestrator runs verify on the corrected text independently (`repair.reverify(text, …)`, with the source
   receipt's options or stricter) and calls `repair.resolve`.

## Repair budget and what resolve checks

`resolve(records, feedback, submission, original=…, corrected=…, receipt=…)` decides one iteration:

| Check | Rejection |
|---|---|
| the agent's digests are the texts' own | `assertion_mismatch` |
| the text changed | `unchanged_artifact` |
| every changed, deleted or inserted-next-to line is in an action's scope | `out_of_scope` |
| every verified claim (quotation, number, anchor) is still in the text | `verified_content_changed` |
| a re-verification receipt is given | `reverification_missing` |
| it is a receipt-v1 that holds together (`receipts.problems`) | `receipt_invalid` |
| its subject is the corrected text | `receipt_mismatch` |
| it ran at least the source's checks, numbers at least as strict | `weaker_verification` |

Every submission that reaches these checks spends one iteration, accepted or rejected, so a chain ends within
`iteration_limit` submissions whatever the agent sends. The default limit is 1: one corrected text, then a terminal
disposition. It can be set from 1 to 3 when the chain starts (`trace.start(receipt, iteration_limit=…)`,
`buddie feedback --limit`). Nothing retries by itself.

A submission that does not belong to the chain raises `repair.SubmissionError` and is not recorded:
`malformed_submission`, `unauthorized_field`, `forged_feedback` (its id is not its bytes'), `feedback_mismatch`
(another chain, an older feedback), `artifact_mismatch` (the original text is not the feedback's), `loop_closed`
(terminal), `duplicate_submission` (the feedback was already answered; the error carries the recorded decision).

An accepted text's next feedback is made from the new receipt; its outcome is the new receipt's. What became of each
actionable finding is recorded: `proved` (the same claim, now supported), `corrected` (a claim of the same check on
the same line, supported), `removed` (no claim of that check on that line), `still_open`. A text whose claims were
all removed is `EMPTY`, so `nothing_verified`, never `verified`.

### Unknown execution outcomes

`execution` is the agent's statement and is recorded as such. `succeeded` and `failed` change nothing: only the
receipt decides. `unknown` with an `idempotent: false` action means the agent does not know whether it acted: if the
new receipt is not `PASS`, the chain ends `reconciliation_required` with no action recommended. A receipt that holds
(the anchor now states the observed state) is reconciliation by observation and ends `verified`.

## Decision trace v1

```
verification -> feedback -> (submission -> [reverification] -> decision -> feedback)*
```

Each record: `{schema, seq, parent, chain, kind, basis, iteration, body, record_id}`. `seq` counts from 0 without a
gap, `parent` is the previous `record_id`, `chain` is the first receipt's id, `record_id` the sha256 of the rest.

| Kind | Basis | Body |
|---|---|---|
| `verification`, `reverification` | `verifier_finding` | receipt id, subject digest, outcome, coverage, executed, numbers, counts, producer |
| `feedback` | `derived` | feedback id, parent, source receipt, iteration, limit, disposition, action and open finding ids, counts per condition |
| `submission` | `agent_assertion+observed` | `asserted`: the agent's digests, execution, action_ref; `observed`: the texts' digests, changed lines, out-of-scope lines, receipt id given, accepted or rejected and why |
| `decision` | `derived` | accepted or rejected, the rejection, the new receipt and outcome, what became of each finding, the next disposition and feedback |

`trace.replay(records)` rebuilds the chain's state from the records alone and raises `TraceError` for a changed
byte, a dropped, reordered or foreign record, a record after a terminal disposition, a submission to a feedback that
asks for none, a skipped iteration or one past the budget. `trace.dumps` writes one canonical JSON object per line;
`trace.loads` reads it back. Nothing in the trace writes a file: persist the lines where the caller keeps such
history.

A recorded decision is a decision under these rules, not proof that the text is true. The trace holds identifiers,
digests, counts and codes only: no text, quotation, page, URL or local path.

## Example cycle

```python
from buddie import repair, trace

opts = {"store": "sources", "fetch": False}
receipt = repair.reverify(report, **opts)                 # an independent verify run, as receipt-v1
records, fb = trace.start(receipt)                        # FAIL: one quote not in its source
assert fb["disposition"] == "repair_requested"
# ... the agent reads fb["recommended_actions"], corrects the quoted line, and sends:
sub = repair.submission(fb, report, corrected)            # or the agent's own submission-v1
got = repair.resolve(records, fb, sub, original=report, corrected=corrected,
                     receipt=repair.reverify(corrected, **opts))
got.feedback["disposition"]                               # "verified", or "budget_exhausted"
trace.replay(got.records)                                 # the history, rebuilt and checked
```

The first feedback, abbreviated:

```json
{"disposition": "repair_requested", "iteration": 0, "iteration_limit": 1,
 "source_receipt": {"outcome": "FAIL", "coverage": "UNKNOWN", "executed": ["quote", "number", "file_anchor", "…"]},
 "findings": [{"check": "quote", "line": 1, "verdict": "NOT_FOUND", "fact": "contradicted",
               "condition": "failed", "actionable": true, "evidence": [{"kind": "snapshot",
               "provenance": "unknown", "digest": "3a06…", "resolution": "digest_bound", "…": "…"}]}],
 "recommended_actions": [{"operation": "correct_claim", "target": {"check": "quote", "line": 1,
                          "extent": "paragraph", "subject": "…"}, "idempotent": true}]}
```

From the CLI: `buddie verify report.md --receipt v1 --json receipt.json`, then `buddie feedback receipt.json`
(feedback-v1 on stdout, or `--json FILE`; exit 2 when the file is not a consistent receipt-v1).

## Trust and authority boundaries

- **Advisory only.** Feedback and decisions grant no permission and run no tool. An agent acts under its own
  authorization; buddie has no executor and schedules nothing.
- **No new verdicts.** Conditions and dispositions are read from a receipt; `source_receipt` repeats its outcome as
  it is. `GAPS`, `EMPTY`, `FAIL` and `UNKNOWN` become `PASS` only through a new receipt of a changed text.
- **No fabricated evidence.** Every evidence reference is the receipt's, unchanged; a digest that is not a sha256 is
  refused as a corrupted reference. A snapshot whose bytes do not match its digest makes verify itself refuse to
  judge (as before this change).
- **No trust in agent claims.** Digests, `execution` and `action_ref` are recorded as the agent's assertions; the
  adapter computes its own and decides only from the receipt.
- **No weaker verifier.** A re-verification must run at least the checks the source ran, numbers at least as strict.
- **Unsigned, like receipts.** Ids are content hashes: they detect a change, not who made a record. A party that can
  write the receipt can write its feedback. `problems()` and `replay()` check consistency, not authenticity.
- **Evidence boundary.** Feedback and resolve read no evidence (no fetch, no store, no repo); they can show only what
  the receipt already shows, so nothing private reaches an agent that the receipt did not. The trace carries none of
  it. Chains do not mix: every record carries its chain, and a feedback of another chain is refused.
- **Bounded context.** A feedback holds one receipt's findings, never earlier iterations; the trace holds ids and
  codes.

## Projects integration boundary

Feedback works without Buddie Projects: nothing here reads or writes a project. `main` has no stable Projects
persistence contract yet (the module is at the design stage), so this change defines only the boundary a Projects
store can keep:

| Projects needs | Taken from |
|---|---|
| verification history | the `verification` and `reverification` records |
| feedback iterations | the `feedback` and `decision` records |
| unresolved findings | the newest `feedback` record's `open_findings`, or the newest feedback's findings |
| references to corrected artifacts | each `submission`'s `observed.artifact_after` and the `reverification` receipt id |
| current verification status | `trace.replay(records)`: disposition, terminal, iteration |

A project keeps the `trace.dumps` lines of each chain (append-only, keyed by `chain`) and calls `trace.replay` to read
them; it should not store a second status of its own. Persistence, retention and cross-session lookup are left to the
Projects follow-up.

## Compatibility and migration

Nothing existing changes: `verify()`, `assess()`, receipt-v0 and receipt-v1, their outcomes and schemas, the hook, the
journal, the MCP tools and the CLI's commands and exit codes are as before. The additions are three modules, the
`buddie feedback` command and this document; no dependency is added. Feedback needs receipt-v1 (receipt-v0 has no
typed findings and is refused rather than guessed at), so a caller that wants feedback asks verify for v1
(`receipts.render(a, "v1")`, `--receipt v1`, `"receipt": "v1"` over MCP). The remote MCP server offers receipt-v0
only and so no feedback.

## Limitations and unsupported cases

- Feedback is only as good as the checks: a claim no check detects (no link, no anchor) gets no finding and no
  feedback; `verified` is the receipt's `PASS`, not truth.
- Scope is by line: a correction is bounded to the finding's line (its paragraph for quotes and numbers). A finding
  with no line is not actionable (`unlocated`). Two findings on one line share its scope; the verified one is
  protected by requiring its claim to stay in the text, which a work claim's subject (its kind) cannot express.
- `corrected` matches by check and line; a correction that moves a claim to another line shows as `removed`.
- Evidence for corrected claims is gathered by the re-verification run, under its options: a new source the agent
  cites is read only if that run may read it.
- No MCP tool and no hook integration yet: callers use the Python API or `buddie feedback`.
- The trace is unsigned and kept by the caller; buddie does not persist it.
- The repair budget is at most 3 by design; a longer loop needs a new chain from a new receipt, which the trace of
  the old chain does not link.
