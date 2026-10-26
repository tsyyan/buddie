# Review follow-up: findings F1–F4

This follow-up keeps the ground truth (`scenarios.py`), the scripted candidates, the smoke data (`results/`) and the
recorded metrics as they were. Each is checked: `git diff` against `47a044f` shows no change to them, and
`bench.py replay` matches.

| | Finding | Outcome |
|---|---|---|
| F3 | A terminal `verified` chain does not bind the text handed in | **Fixed** in production: `repair.accept` / MCP `feedback_accept`. Regression tests in `tests/test_feedback_accept.py` |
| F2 | Two honest repairs are rejected as `out_of_scope` | **Reproduced and characterized** (`tests/test_feedback_scope_f2.py`). Narrow rules proposed below, **not implemented** |
| F4 | A disclosed gap never reaches a terminal state | **Compatibility analysis** below. No new verdict or state |
| F1 | A source swap is accepted | **Documented** as an evidence-attribution limitation (docs/feedback.md, Limitations). Not implemented |

## F3: the hand-in boundary (fixed)

### Design

A chain already records the text it accepted independently: the `subject` digest of its newest `verification`
(at start) or `reverification` record (an accepted repair). A rejected submission appends a `submission` and a
`decision`, but no `reverification`, so the accepted text does not move.

- **`repair.accept(records, final)`** replays the chain and returns `accepted` only when the disposition is
  `verified` and `sha256(final)` equals that digest. Otherwise it refuses:
  - `not_verified`: any disposition but `verified`;
  - `artifact_mismatch`.

  It returns the disposition, the task status and both digests. `repair.accepted_artifact(records)` gives the digest
  alone.
- **MCP `feedback_accept(chain, final_text)`** loads the chain through `chains.load`, with all its integrity and
  tamper checks, and returns `repair.accept`'s answer with `chain` and `basis`. It is read-only, idempotent and does
  not reach the open world. A refusal is an answer (`isError: false`). An unreadable chain is a tool error with the
  `ChainError` code, as for the other two tools. It accepts no `receipt` or other argument
  (`additionalProperties: false`).

### Compatibility

- **Existing tools:** no change to `feedback_start`, `feedback_resolve`, `verify_report`, receipts or the hook.
- **Records and schemas:** no new trace record kind, so `trace.replay` and stored chains are unchanged. No change to
  feedback-v1, the submission or a disposition.
- **The tool list grows from 7 to 8.** That is additive: MCP clients list tools dynamically. The lists that tests
  compare were updated (`manifest.json`, `scripts/smoke_install.py`, docs/getting-started.md, tests/test_buddie.py).
- **The remote HTTP server does not offer it,** like the other feedback tools.

### Regression tests (`tests/test_feedback_accept.py`, 12)

| Case | Expected | Test |
|---|---|---|
| Verified chain, unchanged final report | accepted, `basis: server` | `test_a_verified_chain_accepts_the_text_it_verified` |
| Verified chain, modified final report (appended claim, reworded, trailing newline, CRLF) | refused `artifact_mismatch` | `test_a_verified_chain_refuses_any_other_text` (4 cases) |
| Refused repair, then the refused text handed in | refused `not_verified` while open, `artifact_mismatch` after a later accepted repair verified the chain | `test_a_refused_repair_handed_in_is_refused` |
| No verified chain (`repair_requested`, `budget_exhausted`, `requirements_unmet`, `not_actionable`, `nothing_verified`) | refused `not_verified`, even for the chain's own text | `test_no_chain_but_a_verified_one_ever_accepts` |
| Restarted server | accepted, but `basis: agent_writable` in the result and the text line; a rewritten history is `state_tampered` while the server knows the chain | `test_after_a_restart_acceptance_says_it_rests_on_agent_writable_files` |
| Correct report, no repair | accepted unchanged; nothing written; the benchmark's S7 needless edit (refused `loop_closed`) handed in anyway is `artifact_mismatch` | `test_a_correct_report_is_accepted_as_it_is_without_a_repair` |
| A `receipt` argument, an unknown chain | `invalid_arguments`, `unknown_chain` | `test_the_boundary_takes_no_receipt_and_no_other_argument` |

On the 23 frozen candidates, recomputed and not written into `results/`
(`tests/test_feedback_experiment.py::test_a1_…`):

| | Label: success | Label: not success |
|---|---|---|
| Accepted | 7 | **0** |
| Refused | 3: S1 `delete`, S8 `disclose` (F2), S4 `disclose` (F4) | 13 |

The registered signal (disposition `verified`) said verified for one failed task (S7 `needless_edit`). The boundary
says it for none.

### Residual risks

- **Byte-exact matching.** A changed line ending or a trailing newline is a mismatch. That is intended, since the
  chain verified those bytes, but an orchestrator must hand in the text unchanged.
- **Agent-writable state.** After a restart, `basis: agent_writable`: a consistent rewrite of the chain files while
  the server was down is not detected (docs/feedback.md, Trust). The boundary reports the basis; it cannot raise it.
- **An orchestrator has to call it.** Nothing forces a client to call `feedback_accept` before acting on a report;
  the hook does not enforce it.
- **Correction to an earlier statement.** In PR #60's description I wrote that two starts of the same text always
  give different chains. In fact, the same check of the same text within the same second is the same chain, and the
  second start is refused with `chain_exists`.

## F2: scope friction (reproduced; rules proposed, not implemented)

Measured with the production scope functions (`repair.scope`, `changes`, `outside`):

| Case | Report | What is rejected |
|---|---|---|
| S1 `delete` | `misquote` / blank / `anchor` | removing line 1 *and* its blank separator line 2. The quote's scope is its paragraph, line 1 only; line 2 is outside |
| S8 `disclose` | `unreadable quote` / blank / `ci (unavailable)` | a `buddie:` line inserted after line 3. The CI finding has no action, so no scope |

**Proposed narrow rules:**

- **R1: one separator goes with a removed paragraph.** When a correction deletes every line of a scoped paragraph,
  it may also delete one blank line next to it: the one after it, or the one before it if the paragraph is last.
  Only blank lines qualify. No non-blank line outside scope may change.
- **R2: disclosures next to non-verified findings.** `buddie:` lines may be inserted directly before or after the line
  of a finding whose condition is `missing_evidence`, `unavailable` or `inconclusive`, even when it has no action.
  Only `buddie:` lines qualify, and nothing on that line may change.

Protections that must hold with or without R1 and R2. The guard tests pass today and are meant to keep passing:
- A separator between two *kept* paragraphs stays protected: merging paragraphs is out of scope.
- Text that is not a disclosure, next to a non-actionable finding, stays protected twice: it is out of scope and it is
  added content.
- Rewording a non-actionable claim stays out of scope.
- A verified claim's paragraph cannot be removed (`out_of_scope`, `verified_content_changed`).

**Why not now:**
- R2 widens where unchecked prose may go. A `buddie:` line is not checked, so "buddie: CI passed" would be allowed
  next to an unavailable CI claim, as it already is next to scoped lines. That calls for a product decision.
- Changing either rule changes `out_of_scope` decisions in stored chains replayed by new code. Replay re-derives
  state from records, not decisions, so it stays valid, but consumers comparing decisions across versions would see
  a difference.

## F4: terminal honest disclosure (compatibility analysis; no change)

After S4's or S8's honest disclosure, the chain stays `repair_requested` while budget remains. A dedicated terminal
state, for example `disclosed`, would touch these consumers:

| Consumer | What it enforces | Effect of a new disposition |
|---|---|---|
| `feedback.DISPOSITIONS`, `TERMINAL` | the closed vocabulary | must grow |
| `feedback.SCHEMA` and `docs/feedback-v1.schema.json` | `disposition` is an `enum` | **breaking** for any validator of feedback-v1: needs a feedback-v2 or a schema bump |
| `feedback.problems` | refuses an unknown disposition | old readers refuse new feedback |
| `trace.replay` | refuses a feedback record with an unknown disposition | **old code cannot replay new chains** |
| `repair.follow`, `resolve` | compute the next disposition | new rule |
| MCP `state.disposition`, benchmark `analyze.SAYS_VERIFIED` | read the value | additive for readers that pass unknown values through |
| feedback derivation | feedback is derived from the receipt alone, and receipt-v1 does not record `buddie:` disclosures | a disclosure-aware state needs either receipt data that does not exist, or feedback that reads the text, which breaks "derived from the receipt and from nothing else" |

**Options:**
- **(a) Keep as is.** The agent may stop after disclosing; `feedback_accept` refuses (`not_verified`), which is
  correct because nothing was verified.
- **(b) Feedback-v2 with a `disclosed` disposition.** This needs receipt-level disclosure data and a version
  negotiation.
- **(c) A non-normative MCP field** (for example `state.open_actions`). Additive, but a second source of truth next
  to the disposition.

**Recommendation:** (a) for now, documented in docs/feedback.md, Limitations. If disclosure must be terminal, (b)
should be designed with receipt-v1 consumers in view, not added to v1.

## F1: evidence attribution (documented limitation)

A quote is checked against the bytes of the page its link names. A sentence that names one source ("the
postmortem says") but links another page containing the same words passes the quote check. A repair swapping an
unreadable source for such a page is accepted (S8 `swap_source_in_scope`). Matching the named source to the linked
one needs semantics buddie does not compute, and no heuristic was added. The limit is stated in docs/feedback.md,
Limitations, and the benchmark keeps its ground-truth predicate `source_not_swapped` to measure it.
