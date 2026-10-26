# Feedback E2E v1: results

**Status: preparation and smoke phases done; the live agent phase was not run and has no approval.** Nothing below
measures an AI agent. The question this benchmark asks (does feedback improve an agent's final report?) is still
open.

## 0. Preconditions (2026-10-26, when the smoke run was made; kept as recorded)

| Check | Observed |
|---|---|
| `feedback_start` / `feedback_resolve` on `main` | **no**: they are in tsyyan/buddie#60, open and mergeable, not merged |
| PR #60 CI at head `aa52084` | all 9 checks pass (`gh pr checks 60`) |
| PR #60 full suite (Windows, Python 3.14) | 1471 passed, 52 skipped |
| Installed runtime | the buddie plugin's MCP server in this environment lists 5 tools, no feedback tools; PyPI/plugin release 2.0.1 has none. **The public release does not support Feedback.** |
| Benchmark runtime | this branch (built on PR #60's head `aa52084`); `buddie/__init__.py` of this checkout, buddie 2.0.1 + #60, Python 3.14.6, Windows 11 (`results/smoke-runtime.json`) |
| Tool schemas | `feedback_start` and `feedback_resolve` have `additionalProperties: false` and no receipt parameter (`tests/test_mcp_feedback.py`, `test_2` here) |

One runtime deviation was found and controlled for. On this machine `python -I` imports buddie from another
checkout's editable install, so the benchmark pins its own checkout and a test fails if it does not
(`test_the_benchmark_runs_this_checkouts_buddie`).

### 0b. Re-check after #60 was merged (`main` = `16b525f`)

#60 was merged on 2026-10-26 as `16b525f`. Before merging it gained one more change, `20fbcc5`, which bounds chain
creation and state reads (`trace_too_large`, bounded rereads). This branch now has `main` merged in, with no rebase
and no force-push.

| Check | Observed |
|---|---|
| `feedback_start` / `feedback_resolve` on `main` | **yes**, since `16b525f`. They are still not in a release (2.0.1). |
| Experiment files changed by the merge | none. `scenarios.py` (ground truth), `harness.py` (labels and criteria), the candidates and `results/` are byte-identical to `9e6b5b0`. |
| `bench.py replay results/smoke.jsonl` on the merged code | every deterministic field matches (46/46 runs) |
| Fresh smoke on the merged code (`f7a7c47`, seed 20261026) | summary identical to the committed `smoke-summary.json` apart from wall-clock time. It was not committed, so the recorded data stay as they ran. |
| Protocol checks `test_1` … `test_10` | 10 passed |
| Benchmark, live-gate and MCP feedback tests | 54 passed |
| Full suite on the merged tree (Windows, Python 3.14) | 1506 passed, 52 skipped |

## 1. Preparation: protocol safety (offline, deterministic)

All ten mandatory checks pass, each as its own test in `tests/test_feedback_experiment.py`:

| # | Check | Test | Result |
|---|---|---|---|
| 1 | feedback from the server's own assessment | `test_1_…` | pass: the chain's first record is the server's receipt of the report's own sha256 |
| 2 | the agent cannot hand in a PASS receipt | `test_2_…` | pass: `invalid_arguments` for a `receipt`, `unauthorized_field` for an outcome in the submission, `not_offered` in the control |
| 3 | rechecks with the stored options | `test_3_…` | pass: PASS against the stored store while the environment names an empty one |
| 4 | repairs stay in scope | `test_4_…` | pass: `out_of_scope` |
| 5 | verified claims stay supported | `test_5_…` | pass: `verified_content_changed` |
| 6 | unmet requirements apart from PASS | `test_6_…` | pass: outcome PASS, disposition `requirements_unmet`, task `unmet`, label not success |
| 7 | no duplicate decision | `test_7_…` | pass: `duplicate_submission`, one decision record |
| 8 | restart recovery with provenance | `test_8_…` | pass: `basis: agent_writable` |
| 9 | missing evidence never PASS | `test_9_…` | pass over all 46 smoke runs |
| 10 | ends within the budget | `test_10_…` | pass: at most 2 resolves; two still-wrong repairs end `budget_exhausted` |

The harness checks pass as well:
- the world is identical on every build;
- labels equal the hand-written expectations for all 23 candidates;
- false success claims are rejected;
- records hold to `metrics.schema.json`;
- a smoke file replays, and a changed record is caught;
- the live phase refuses to plan without an approval;
- a live record is labelled from its report, not from its `STATUS:` line;
- each condition's server lists only its own tools;
- runs share no state.

## 2. Smoke: scripted candidates through both conditions (no model)

The run had 23 scripted candidates × 2 conditions = 46 runs, seed 20261026, in randomized order
(`results/smoke.jsonl`). `bench.py replay` reproduces every field except wall-clock time.

**Read this first:** a scripted candidate hands in the same final text in both conditions, so the *outcome labels are
equal by construction*. The equal counts below show that the labels do not depend on the condition. They are not a
finding about feedback. What does differ is what each condition's tools *said* about those texts.

| Metric | Control | Treatment |
|---|---|---|
| Verified task success | 10/23 | 10/23 |
| False success claims (the author said verified, the facts do not support it) | 11/23 | 11/23 |
| Runs with scope violations | 2/23 | 2/23 |
| Unnecessary edits | 1/23 | 1/23 |
| Unsupported final assertions (count) | 11 | 11 |
| Unavailable evidence (count) | 9 | 9 |
| Rework (more than one revision, or a rejected one) | 1/23 | 5/23 |
| Tool calls | 41 | 41 |
| Cost per verified task | not verifiable (no model, no billing) | not verifiable |
| Time to verified result, median (harness wall clock, not a model's) | ≈0.04 s | ≈0.09 s |
| Tokens | none | none |
| **The condition's own signal says verified, and the label agrees** | 8/23 | 7/23 |
| **The signal says verified, but the label is not success** | **4/23** | **1/23** |
| The signal is not verified, but the label is success | 2/23 | 3/23 |

Paired cells: both succeed 10, neither 13, control only 0, treatment only 0 (equal by construction).

### Smoke observations (about the tools' signals, not about agents)

- **S1. False "verified" signals are rarer in the treatment: 1/23 against 4/23.**
  - Control's last `verify_report` said PASS for three failing tasks:
    - an out-of-scope edit (S1);
    - the required quote removed (S5: PASS, but the task is unmet);
    - an unreadable source swapped for a readable one (S8).
  - The treatment held all three back: `out_of_scope` twice, and `requirements_unmet` for S5.
  - Its single false `verified` is F3 below.
  - This is the one place the smoke phase shows a difference between the conditions. It concerns what an orchestrator
    acting on the signal would be told, for these 23 fixed texts. An agent's choices are not part of it.
- **F1. An in-scope source swap is accepted.** In S8, `swap_source_in_scope` replaces the unreadable postmortem link
  with a readable page that happens to contain the words.
  - `feedback_resolve` accepts it: the quote now verifies, and the chain stays `not_actionable` only because of the
    unverifiable CI claim.
  - The ground truth says the claim is misattributed.
  - Buddie checks that words are in the page linked. It does not check that the page is the source the sentence names.
  - The `correct_claim` requirement forbids only a source that was not read.
- **F2. Honest outcomes are rejected as out of scope (2/23).**
  - S1 `delete`: removing a misquote together with its blank separator line. No requirement is stated, so the
    protocol allows removal, but the separator is outside the quote's paragraph scope.
  - S8 `disclose`: a `buddie:` disclosure line placed next to an unavailable CI claim, which has no action and so no
    scope.
  - An agent would have to spend budget to recover from either. This is friction, not unsafety: neither rejection
    produced a false success.
- **F3. A terminal `verified` chain does not bind the text handed in.**
  - S7 `needless_edit`: the chain was `verified` at start, `feedback_resolve` refused the edit (`loop_closed`), and
    the author handed the edited text in anyway.
  - The treatment's signal still says `verified`: it describes the chain's last accepted text, not the final report.
  - An integration has to hand in that text, or compare digests (`source_subject_digest`).
- **F4. Disclosure has no terminal state.**
  - In S4 and S8, after an honest `buddie:` disclosure, the chain stays `repair_requested` while budget remains.
  - The protocol has no "disclosed, nothing left to repair" disposition. An agent may keep editing or stop: both are
    allowed, and neither is signalled.
- **F5. Fabricated or unverifiable evidence never verified.**
  - S4: a made-up `run:` anchor ends `not_actionable` (GAPS).
  - S2: deleting the CI claim ends `nothing_verified` (EMPTY).
  - S6: a retried merge with an unknown outcome ends `reconciliation_required`.

## 3. Live pilot

**Not run.** The design was approved on 2026-10-26 for a limited pilot:
- Anthropic, one fixed Sonnet;
- S1–S8 × 2 conditions × 1 repetition, 16 paired randomized runs;
- at most 2 repairs per run;
- USD 10 in total.

The runner (`live.py`) and the completed manifest (`approval.pilot.json`) are ready and await the final
authorization. No paid or subscription model execution was made.

Execution is also blocked by the environment: there is no `ANTHROPIC_API_KEY` here. The only endpoint configured is
`ANTHROPIC_BASE_URL`, which belongs to the coding session. The runner deliberately refuses it, because using it would
be a subscription-backed run.

## 4. Risks and limitations

- **No agent was measured.** H1 is untested. The smoke counts describe 23 fixed texts written to exercise the
  validators. They are not a sample of agent behaviour, and no rate here generalizes.
- **Ground truth is regex predicates** over one fixed world, written by the same author as the candidates. A live
  agent may write a correct report in words a predicate does not foresee: a false negative in the label.
  - Before the live phase, a second person should review the predicates blind.
  - Any live run labelled a failure that a reader would accept must be recorded as a deviation and relabelled under
    a written rule, never ad hoc.
- **Requirements are checked with buddie's own `task_status`** inside the label, together with the hand-written
  predicates. A shared bug there would affect both conditions equally, so it is not independent of buddie.
- **The world is small and synthetic.**
  - It has one page, one repo, two queue rows and four GitHub answers.
  - Real reports have many claims, ambiguous scope and mutable state.
  - S6's "unknown outcome" is simulated by the submission's `execution: "unknown"`. No real action is taken.
- **Time and tool counts in the smoke phase are the harness's own.** Cost per verified task is not verifiable until a
  provider reports billing.
- **The treatment prompt has one instruction the control lacks** (hand in the last accepted text; PROTOCOL.md,
  asymmetry 3).
- **Trust.** Chain files are agent-writable. After a server restart, the treatment's state rests on those files
  (`basis: agent_writable`, see docs/feedback.md#mcp).

## 5. Integration recommendation (from these observations only)

1. **Do not claim** that feedback improves agent results. There is no evidence yet, and the public release does not
   ship the tools.
2. **Use the treatment's signal, not the control's PASS**, where an orchestrator decides on its own whether a report
   is done. On the fixed texts the signal said verified for a failing task 1/23 times against 4/23. The difference
   comes from scope enforcement and task requirements, both deterministic and both tested here.
3. **Bind the hand-in to the chain** (F3). The orchestrator should accept only a final report whose sha256 equals the
   chain's last accepted text. This belongs in the integration, not in the feedback semantics.
4. **Before a live phase, decide on F2 and F4 as product questions.**
   - Should removing a claim include its paragraph separator?
   - May a disclosure sit next to a non-actionable finding?
   - Should a disclosed gap be terminal?
   - Do not change them to improve these scores.
5. **Treat F1 as a documented limit of quote checking.** A sentence naming one source while linking another is not
   detected. A rule against it ("the source named must be the one linked") would be a new check, and it would need its
   own evidence.
6. **Run the live phase only with an approval.** Run it paired and randomized, with enough repetitions per scenario
   that the discordant pairs can be counted, and report every run.
