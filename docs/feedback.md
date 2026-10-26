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
task                       the task requirements the orchestrator stated, and how this receipt meets them:
  status                   not_stated | met | unmet
  requirements[]           {requirement_id, check, subject_prefix, status: met | unsupported | absent}
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
| `verified` | yes | the receipt's outcome is `PASS` and every stated task requirement is met. It is about the checks that ran (see `source_receipt.coverage`), not about the text being true; with `task.status` `not_stated` it says nothing about the task |
| `requirements_unmet` | yes | the outcome is `PASS`, but a stated task requirement has no supported claim: a correct report of an unfinished task, or one whose required claim was removed |
| `nothing_verified` | yes | the outcome is `EMPTY` or `NOT_RUN`: nothing was checked, so nothing passed |
| `not_actionable` | yes | not `PASS`, and nothing the author can correct (only `unavailable` findings) |
| `budget_exhausted` | yes | actionable findings remain and the budget is spent |
| `reconciliation_required` | yes | the agent reported an external action's outcome as unknown and the text still does not verify |

A terminal feedback recommends no action.

### Task requirements

A corrected report is not a finished task. Deleting the claim a task needed ("the PR is merged") removes its failing
finding, and the report can then `PASS`. To keep these apart, the orchestrator (never the agent) can state the task's
requirements when a chain starts:

```python
records, fb = trace.start(assessment, requirements=[{"check": "pr_anchor", "subject_prefix": "pr:o/r#59=merged"}])
```

A requirement is met when a finding of that check whose subject starts with that prefix is supported. Each feedback
reports every requirement as `met`, `unsupported` (claimed, not supported) or `absent` (not claimed), and the task as
`not_stated`, `met` or `unmet`. A `PASS` with the task `unmet` is `requirements_unmet`, never `verified`. Requirements
are fixed for the chain: a submission cannot carry them, and `replay` refuses a chain whose requirements change. From
the CLI: `buddie feedback receipt.json --require pr_anchor=pr:o/r#59=merged`.

## How an external agent consumes feedback

1. Read `disposition`. Act only on `repair_requested`.
2. For each action, rewrite only the lines in `target` (the paragraph for quotes and numbers) and follow its
   `requirements`. Do not add lines: the only lines a correction may add are `buddie:` disclosure lines next to
   them. Leave every `verified` finding's claim where it is.
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

5. The orchestrator runs verify on the corrected text itself, in its own process (`repair.reverify(text, …)`, with
   the original's options or stricter), and passes that `verify.Assessment` to `repair.resolve`. A receipt the
   agent sends, or one read from a file or a tool argument, is never passed: see "Receipt authenticity" below.

## MCP

The local stdio server (`buddie serve`: the Claude Code and Codex plugins, Desktop, `uvx buddie serve`) offers the
loop as two tools. Both refuse any argument outside their input schema (`additionalProperties: false`); neither takes
a receipt, because receipts are unsigned and a tool argument is whatever the agent writes. The server runs every
check itself.

| Tool | Takes | Does | Returns (`structuredContent`) |
|---|---|---|---|
| `feedback_start` | `text` or `path`; `verify_report`'s check options (`repos`, `store`, `fetch`, `access`, `numbers`, `github`, `transcript`, `profile`, `modules`, `checks`); `iteration_limit` (1–3, default 1); `requirements` (at most 32 `{check, subject_prefix}`) | `repair.reverify` of the report, `trace.start`; writes the chain's trace and its check options | `chain`, `feedback` (feedback-v1), `receipt_line`, `state` |
| `feedback_resolve` | `chain`, `feedback` (as returned), `submission` (repair-submission-v1), `original_text`, `corrected_text` | replays the chain, refuses a feedback that is not its open one, re-verifies `corrected_text` with the chain's stored options, `repair.resolve`, appends only the new records | `decision`, `feedback` (the next one), `receipt_line`, `state` |

`state` is `{disposition, task, iteration, terminal}` as `trace.replay` reads the chain; `receipt_line` is
`receipts.line` of the receipt-v1 buddie made (the tool's text starts with it). A refused submission
(`repair.SubmissionError`: `duplicate_submission`, `forged_feedback`, `feedback_mismatch`, `artifact_mismatch`, ...)
is a tool error with its `code`, and nothing is appended. A feedback id is the hash of its content, so a feedback
changed after it was returned is refused.

The chain lives in buddie's state dir, as the hook's (`BUDDIE_STATE`, default `~/.cache/buddie/pending`; with
`BUDDIE_STATE=0` the default place): `feedback/<chain hex>.jsonl` (`trace.dumps` lines, created once and then only
appended to) and `feedback/<chain hex>.options.json` (the check options, absolute paths). The caller cannot pass
weaker options for a correction; an edit of the options file is caught only as far as `resolve` catches a weaker
re-verification (`weaker_verification`). Starting the same check of the same text twice is refused (`chain_exists`).

**Trust.** The chain files are on the agent's machine and the agent can write them, like the journal
(`core.Provenance.AGENT_WRITABLE`). `trace.replay` detects a history that does not hold together, not who wrote it:
a party that can write the files can write a consistent chain. The decisions are buddie's only as far as the chain
file is.

The remote HTTP server (`remote.py`) does not offer these tools: it reads no local files and returns receipt-v0 only.

## Repair budget and what resolve checks

`resolve(records, feedback, submission, original=…, corrected=…, assessment=…)` decides one iteration:

| Check | Rejection |
|---|---|
| the agent's digests are the texts' own | `assertion_mismatch` |
| the text changed | `unchanged_artifact` |
| every replaced or deleted line, and every place something is inserted, is in an action's scope | `out_of_scope` |
| nothing is added: the lines replacing n lines are at most n, inserted lines only `buddie:` disclosures | `added_content` |
| every verified claim (quotation, number, anchor) is still in the lines that took the place of its own | `verified_content_changed` |
| a re-verification is given | `reverification_missing` |
| its receipt-v1 holds together (`receipts.problems`; always so for an Assessment) | `receipt_invalid` |
| its subject is the corrected text | `receipt_mismatch` |
| it ran at least the source's checks, numbers at least as strict | `weaker_verification` |
| the new check finds every verified claim supported, where it was | `verified_content_changed` |

The scope is computed on a line diff (`difflib.SequenceMatcher`). A replace block's new lines are counted against
the lines they replace, so lines slipped in alongside an allowed rewrite are `added_content`, not hidden in the block
(found in review: at 644f753 one allowed line could be replaced by two, the second an unchecked claim).

Every submission that reaches these checks spends one iteration, accepted or rejected, so a chain ends within
`iteration_limit` submissions whatever the agent sends. The default limit is 1: one corrected text, then a terminal
disposition. It can be set from 1 to 3 when the chain starts (`trace.start(receipt, iteration_limit=…)`,
`buddie feedback --limit`). Nothing retries by itself.

A submission that does not belong to the chain raises `repair.SubmissionError` and is not recorded:
`malformed_submission`, `unauthorized_field`, `forged_feedback` (its id is not its bytes'), `feedback_mismatch`
(another chain, an older feedback), `artifact_mismatch` (the original text is not the feedback's), `loop_closed`
(terminal), `duplicate_submission` (the feedback was already answered; the error carries the recorded decision),
`untrusted_receipt` (the re-verification is not a `verify.Assessment`, see below).

An accepted text's next feedback is made from the new receipt; its outcome is the new receipt's. What became of each
actionable finding is recorded: `proved` (the same claim, now supported), `corrected` (a claim of the same check in the
lines that took the place of its own, supported), `removed` (none there), `still_open`. Places come from the line
diff, not line numbers (at 644f753 a deleted line's finding was reported `corrected` when another claim moved up into
its line number). A text whose claims were all removed is `EMPTY`, so `nothing_verified`, never `verified`; a
removed claim the task required is `requirements_unmet`.

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
records, fb = trace.start(repair.reverify(report, **opts))  # FAIL: one quote not in its source
assert fb["disposition"] == "repair_requested"
# ... the agent reads fb["recommended_actions"], corrects the quoted line, and sends:
sub = repair.submission(fb, report, corrected)            # or the agent's own submission-v1
got = repair.resolve(records, fb, sub, original=report, corrected=corrected,
                     assessment=repair.reverify(corrected, **opts))  # this process's own check
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
- **Receipt authenticity.** Receipts are unsigned, and `receipts.problems()` checks consistency, not origin: anyone
  can write a receipt-v1 that holds together and says `PASS` for any text (at 644f753 `resolve` accepted one and
  closed the chain as `verified`). So a chain is started and decided only on a `verify.Assessment` made in the
  caller's own process (`trace.start`, `resolve`); a receipt dict is refused (`TypeError`, `untrusted_receipt`).
  Python objects are not a security boundary inside one process: this keeps a receipt that crossed a process boundary
  (an agent's message, a file, an MCP argument) out of the decision, nothing more. `feedback.from_receipt` and
  `buddie feedback` still read receipt files, as advice about that receipt only: their `verified` means "this
  receipt says PASS", not that buddie made it. Nothing here is signed; ids are content hashes that detect a change,
  not who made a record, and a party that can write a trace's lines can write a consistent history.
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
| current verification status | `trace.replay(records)`: disposition, terminal, iteration, and the task status apart from them |

A project keeps the `trace.dumps` lines of each chain (append-only, keyed by `chain`) and calls `trace.replay` to read
them; it should not store a second status of its own. Persistence, retention and cross-session lookup are left to the
Projects follow-up.

## Compatibility and migration

Nothing existing changes: `verify()`, `assess()`, receipt-v0 and receipt-v1, their outcomes and schemas, the hook, the
journal, the MCP tools and the CLI's commands and exit codes are as before. The additions are three modules, the
`buddie feedback` command and this document; no dependency is added. Before release, the review of PR #59
changed the Python API of the new modules (`trace.start` and `repair.resolve` take a `verify.Assessment`, not a
receipt) and added `task`, `requirements_unmet` and `added_content`; nothing of this was released before. Feedback needs receipt-v1 (receipt-v0 has no
typed findings and is refused rather than guessed at), so a caller that wants feedback asks verify for v1
(`receipts.render(a, "v1")`, `--receipt v1`, `"receipt": "v1"` over MCP). The local MCP server adds two tools,
`feedback_start` and `feedback_resolve` ([MCP](#mcp)); the existing tools are unchanged. The remote MCP server offers
receipt-v0 only and so no feedback.

## Limitations and unsupported cases

- Feedback is only as good as the checks: a claim no check detects (no link, no anchor) gets no finding and no
  feedback; `verified` is the receipt's `PASS`, not truth.
- Scope is by line: a correction is bounded to the finding's line (its paragraph for quotes and numbers). A finding
  with no line is not actionable (`unlocated`). Two findings on one line share its scope: a verified claim there must
  stay in the lines that replaced its own and be supported there by the new check, but the words around it on that
  line are not judged, so a verified claim can be kept while its sentence is reworded (as verify itself never judges
  the sentence around a quotation or an anchor). A work claim's subject is its kind, so only the new check, not its
  words, keeps it in place.
- `buddie:` disclosure lines may be added next to scoped lines; their prose is not checked, like any prose.
- A correction that moves a claim to another paragraph is out of scope; one that rewrites it into another line of
  the same block shows as `corrected` or `removed` by place.
- Task requirements match a check and a subject prefix only: they cannot say "this PR, merged, in this repository"
  more precisely than the anchor's own words, and a task with no stated requirement is `not_stated`, never `met`.
- Evidence for corrected claims is gathered by the re-verification run, under its options: a new source the agent
  cites is read only if that run may read it.
- No hook integration yet: callers use the Python API, `buddie feedback` or the local MCP tools ([MCP](#mcp)).
- The trace is unsigned and, outside the MCP tools, kept by the caller; the MCP server keeps it in its state dir.
- The repair budget is at most 3 by design; a longer loop needs a new chain from a new receipt, which the trace of
  the old chain does not link.
