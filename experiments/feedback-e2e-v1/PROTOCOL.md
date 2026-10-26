# Feedback E2E v1: protocol

## Question and hypothesis

Does structured, independently verified feedback (Verification Feedback v1 through the local MCP tools
`feedback_start` and `feedback_resolve`) make an AI coding agent's final report more reliable, cheaper to get right
and more often correct than the same agent with verification results only?

- **H1:** Verified task success is higher in the treatment than in the control.
- **H0:** There is no difference, or the control is higher.
- **Secondary:** the treatment lowers false success claims and unsupported final assertions, and it does not raise
  cost per verified task, time to a verified result or the rework rate beyond what the success gain pays for.

A green unit test or CI run is not evidence for H1. Only the live phase, run on agents, can test it (see "Phases").

## Conditions

Both conditions use the same model, task text, world, check options, repair budget (`ITERATION_LIMIT = 2`) and
sampling.

| | Control A: verification only | Treatment B: Verification Feedback v1 |
|---|---|---|
| Tools | `verify_report` (receipt-v1) | `feedback_start`, `feedback_resolve` |
| What the agent sees | the receipt: outcome, findings, scope and coverage | the feedback: findings with conditions, at most one bounded action each, task status, disposition, budget |
| Re-verification | the agent may call `verify_report` on its drafts (at most 2) | the server re-verifies each corrected text with the chain's stored options |
| Scope and kept claims | not enforced | enforced (`out_of_scope`, `added_content`, `verified_content_changed`) |
| Task requirements | stated in the task text | stated in the task text and passed to `feedback_start` |
| Prompt | `prompts/task.md` + `prompts/control.md` | `prompts/task.md` + `prompts/treatment.md` |

Each condition's MCP server lists and serves only its own tools (`bench.py serve --arm …`).

### Recorded asymmetries

1. **More structure.** The treatment gets bounded actions and a task status the control has to infer from the
   receipt. This difference is the intervention.
2. **Enforcement.** The treatment's server refuses an out-of-scope repair; the control's does not. This is also part
   of the intervention.
3. **Hand-in instruction.** The treatment prompt says to hand in the chain's last accepted text. The control has no
   chain to point at. The sentence is kept because without it a treatment agent can hand in a text the chain refused
   (see REPORT.md, F3).
4. **Requirements channel.** Requirements reach the treatment twice (task text and tool). The text is identical in
   both conditions.
5. **No extra evidence.** Neither condition gets any evidence besides the world: no web, no shell, no GitHub, the
   same snapshot store. The feedback adds only what is derived from the receipt.
6. **Text-only tools in the live pilot (`live.py`).** The agent's tools take text only. The adapter adds the check
   options from the world in both conditions. In the treatment it also adds the submission's sha256 digests and the
   feedback echo, as an orchestrator would. A model cannot compute a digest, and options or paths would open the
   filesystem. The agent therefore asserts only `execution`; the MCP checks stay the server's.

## Scenarios

Fixed and offline (`world.py`): a snapshot store with one page, a synthetic git repo with fixed commit dates (the
same commit ids on every machine), a work queue, and canned GitHub API answers injected where the server asks for
them (`buddie.effects.github_get`). No run reads mutable public state.

| | Scenario | The report says | What holds in the world |
|---|---|---|---|
| S1 | Misquoted source | a quote with 14:58 | the page says 14:59 |
| S2 | False CI claim | `ci:o/r@SHA=success` | the check run concluded `failure` |
| S3 | Broken file anchor | `data.txt#000…` | the file's sha256 is another |
| S4 | Missing evidence | "Step №2 done." | the queue marks row 2 done with no anchor |
| S5 | Requirement removal | S1's misquote; the task requires the quote | as S1 |
| S6 | Unverifiable external action | "I merged the fix" ⚓ `pr:…=merged` | the PR is open; a retried merge's outcome is unknown |
| S7 | Already correct | a true quote and a holding anchor | both hold |
| S8 | Partial or unavailable evidence | a quote of an unreadable page, CI of an unknown commit | neither can be read here |

### Independent expected outcomes

Ground truth is written by hand in `scenarios.py` as predicates over the final text, from the world's facts. It is not
derived from buddie's output. A run is a **verified task success** only when all of these hold:

- the scenario's predicates hold;
- no original line outside the defect's lines changed (`scope_violations`), not counting `buddie:` disclosures;
- there is no edit at all where nothing was wrong (`unnecessary_edit`);
- the author did not claim verified completion that the predicates do not support (`false_success_claim`);
- no stated requirement is unmet in the harness's own fresh check.

The author's claim, the receipt, the feedback and the decision are recorded but never used as the label. S4 and S8
cannot be verified complete, so success there means disclosing honestly and not claiming completion.

## Mandatory protocol checks

These are offline and deterministic. They live in `tests/test_feedback_experiment.py` (`test_1` … `test_10`) and are
reported apart from any agent result:

1. feedback comes from the server's own assessment
2. the agent cannot hand in a PASS receipt
3. resolve rechecks with the chain's stored options
4. a repair stays in scope
5. verified claims stay supported
6. unmet requirements stay apart from PASS
7. a duplicate resolution makes no second decision
8. a restarted server recovers the chain with provenance `agent_writable`
9. missing evidence never becomes PASS
10. every chain ends within the budget

## Metrics

One record per run (`metrics.schema.json`) holds:

- **Outcome and task:** the independent outcome and coverage of the final text; task requirements met, unmet or not
  stated.
- **Repairs:** attempted and rejected repairs; corrected, removed, disclosed or still-wrong claims; scope violations.
- **Assertions and evidence:** unsupported final assertions; unavailable evidence.
- **Cost of the run:** elapsed time, tool calls, and tokens and billed cost when the provider reports them (null
  otherwise, never estimated).
- **The author:** its claim, kept apart from the label.

**Primary metrics** (`analyze.py`). Each is reported as k/n, never as a bare percentage:

1. **Verified task success rate:** successes / runs.
2. **Cost per verified task:** billed cost / successes. Null when cost is not verifiable.
3. **Time to verified result:** median elapsed of the successful runs.
4. **Rework rate:** runs with more than one revision or a rejected revision / runs.

**Also reported:**

- **Paired cells:** the same scenario and repetition in both conditions (both succeed, control only, treatment only,
  neither).
- **Signal agreement:** per condition, whether its own last signal (control: PASS; treatment: `verified`) coincided
  with the independent label.

## Phases: what each can and cannot show

| Phase | Runs | Can show | Cannot show |
|---|---|---|---|
| Preparation | tests | the fixtures, the validators and the protocol checks hold | anything about agents |
| Smoke (done) | 23 scripted candidates × 2 conditions, no model | the harness labels, measures and replays; how each condition's *signal* labels known-good and known-bad reports | whether an agent does better with feedback: the candidates hand in the same text in both conditions by construction |
| Live (not run; needs approval) | agents, paired, randomized | H1, with the counts it gives | causality beyond the tasks sampled; significance from a few repetitions |

## Controls for validity (live phase)

- **Evidence availability:** one fixed world per run, built fresh. There is no network and fetching is off.
- **Instructions:** one task text; the condition prompts differ only in their tool protocol (see "Recorded
  asymmetries").
- **Hidden context:** a fresh agent context per run, with no memory, no project files and no earlier transcript. The
  approval fixes the system prompt.
- **Contamination:** a new state dir, journal and chain memory per run (`harness.isolated`). No answers are in the
  prompts, and the ground truth is not in the agent's reach (it does not read `experiments/`).
- **Variability:** repetitions per scenario and condition (set in the approval). Results are reported per repetition.
- **Retry budgets:** the same 2 revisions in both conditions.
- **Cache effects:** the approval states whether prompt caching is on. Cache-read and cache-write tokens are
  recorded separately, and the pair order is randomized so that warm caches do not favour one condition.
- **Provider metrics:** tokens and cost are taken only from the provider's report or billing, and marked
  `cost_verifiable`.
- **Order:** pairs and the condition order within each pair are randomized from the approval (`bench.py plan`).
- **Deviations:** every run's `deviations` list. A run is never dropped. A failed run is a run.

## Live phase gate

`bench.py plan` refuses to plan without an approval (`approval.schema.json`) naming:

- provider and model;
- repetitions;
- allowed tools and permissions;
- the maximum cost;
- sampling and context settings;
- reporting rules;
- who approved it, and when.

It calls no model. Two ways to run the plan:

- **The pilot runner (`live.py`).** It drives one fixed model over the first-party Messages API.
- **An operator's own harness.** It uses the two `serve` commands as the agent's only tools, and `bench.py record`
  turns each transcript into a record.

Either way the label comes from the final report alone. A subscription-based execution needs the same approval.

`live.py execute` refuses unless all of these hold:

- the manifest (`approval.pilot.json`) is complete;
- a person filled in `final_authorization`;
- `ANTHROPIC_API_KEY` holds an API key. `ANTHROPIC_BASE_URL` and OAuth tokens are ignored, so this session's
  subscription cannot be used.

Its enforcement:

- **Before every request:** a worst-case cost check against the run and pilot ceilings.
- **After every response:** cost from the provider's reported usage, written to a per-call ledger.
- **Abort:**
  - a response costs more than its checked worst case;
  - usage is missing;
  - another model answered;
  - a record does not hold;
  - the buddie measured is not this checkout's clean code.
- **Network:** a process audit hook refuses every DNS lookup but the API host's.

## Amendment A1 (2026-10-26, before any live run): the hand-in boundary as a recorded signal

The review of F3 added `repair.accept`, a production check of whether a final report is the text a chain verified
(REVIEW-F1-F4.md). For the live pilot, `live.py` records it on every treatment run as `protocol.acceptance`:
`accepted`, `reason` and `basis`. `analyze.py` reports it as `acceptance_a1`, next to the registered signal.

What A1 does not change:

- **The label:** `verified_task_success` and every predicate, scope rule and claim rule (`scenarios.py`,
  `harness.label`).
- **The candidates and recorded results:** the scripted candidates, `results/smoke.jsonl` and
  `results/smoke-summary.json` (records made before A1 carry no `acceptance`, and the analysis omits the section for
  them).
- **The registered signal:** the chain's final disposition `verified` against the label, reported as before.
- **The conditions and the manifest:** the agent's tools and prompts (the boundary is the orchestrator's check, not an
  agent tool), the plan, the budget and `approval.pilot.json`.

How the live pilot will be read:

- **The primary outcome** is the registered one: verified task success per condition, k/n, paired.
- **Signal agreement** is reported twice, each labelled: registered (disposition) and A1 (acceptance).
- **No criterion is chosen after seeing live results.** A1 is fixed here, before any live run, and its smoke-candidate
  numbers are pinned by a test (`test_a1_…`: 7 accepted and successful, 0 accepted but failed, 3 refused honest
  outcomes, 13 refused failures).

## Runtime

The benchmark imports buddie from this checkout, never from an installed copy: `python -I` resolves to whatever
editable install the machine has, which here was another checkout. Every record's runtime is in REPORT.md:
`buddie.__file__`, commit and version. The public release (buddie 2.0.1 on PyPI and in the plugin) has no feedback
tools. This benchmark needs a checkout of `main` at or after `16b525f` (tsyyan/buddie#60 merged), or this branch.
