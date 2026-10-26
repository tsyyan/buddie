# BDX-002 GitHub Evidence Efficiency — prepared, NOT RUN

Status 2026-10-26: model-free design/instrumentation only. No model executor, API-key handling or live GitHub
adapter is enabled. A separate user decision must approve model/provider, price basis, run count and USD ceiling
before any paid trial. Subscription CLI usage also counts as paid usage. This document does not grant permission.

## Question and arms

For identical GitHub tasks, compare **A direct GitHub tools** with **B existing Buddie evidence mechanisms**.
Both get the same task, repo/PR/revision, model parameters, response format, GitHub source permission and fixture
snapshot; neither gets evaluator ground truth, local checkout information unavailable to the other, or host state.
Use pairs by scenario/fixture/model and pre-randomize pair/arm order with a recorded seed. Freeze all tool schemas,
instructions, model/runtime versions and Buddie SHA before execution. No pooling across model/version changes.

Baseline B-core = main `0bc048e7439ac283409fdfd05f763a506a95888a`: pr:/ci: anchors, existing receipts, snapshots.
B-citations = optional separate stratum at #55 `a14b15c689e5e35fe6f2e1b2d6ce24a45c04bb51`; it supports pinned
literal file/diff sources. Do not call #55 deployed or pool this stratum with B-core. Unsupported B-core diff
quotations must be recorded as coverage gaps, never filled by a hidden privileged tool. Local repo commit/file
anchors are a separate local-evidence stratum, only if both arms receive the same frozen checkout.

`cases.json` has the model tasks and offered starting locators; `evaluation/expected.json` has evaluator-only
truth and acceptance. Neither harness nor tests call a model or a live service. The current program prepares a
manifest, validates/imports completed runtime usage, and provides in-memory wrappers for later adapters. It does
not pretend that synthetic replay measures GitHub/connector/model latency or actual cost savings.

## Five scenario families

PR/CI exact-head state; immutable commit identity/message; literal diff citation with side/line; a false merge
claim when PR is open; release readiness with green CI but unconfirmed acceptance/publication. Before live trials,
freeze positive/negative/offline/raced-head/private/no-access fixtures for each family. Direct arm must inspect
equivalent underlying evidence; B cannot receive the answer in its instruction. Repository text and PR bodies may
contain hostile instructions and claims; they are evidence data, never agent instructions.

Each family has the same expected **factual** result for A and B, with explicit permitted abstention. Score result
accuracy separately from citation correctness, coverage, unsupported conclusions and task completion. B-core
unsupported diff coverage is an outcome, not a harness failure. A green receipt is not semantic release readiness.

## Instrumentation and units

`instrumentation.py` measures tool-boundary elapsed monotonic time and UTF-8 serialized request/response bytes.
It stores only permitted tool name, boundary, byte lengths, duration and success; no raw arguments, response bodies,
paths, environment values or exception text. Configure the adapter to use actual transport bytes when available;
otherwise explicitly label canonical-JSON application bytes. They are not HTTP/TLS wire bytes.

Count **agent-facing tool calls** and **underlying GitHub requests** separately. Include pagination, retries,
rate limits, source fetches and Buddie's internal GETs. Record model wall-clock from before first dispatch until
accepted final result, tool time, hook time, retries and finalization independently. Overlapping calls cannot be
summed into wall-clock; report critical-path timing and call distributions. Provider latency includes startup
only if the same cold-start rule is used for both arms. Warm/cold store and model-cache conditions are separate,
counterbalanced strata. Preserve cache policy and cache-hit counters; no silent prewarming.

Usage comes from completed **runtime result counters**: uncached input, cache-read input, cache-creation input,
output tokens and reported total USD. The prepared importer supports the observed Claude CLI result shape only;
a different provider needs a reviewed adapter and counter contract. Missing counters/cost are missing, not zero.
Counters are not independently authenticated billing; retain runtime/version/source hash and compare dashboard
billing when accessible. No token estimate, tokenizer guess or byte→token conversion is a usage counter.
Cache counters are disjoint in this source contract; report their separate values and sum for total input only
under that documented convention. Cost uses reported USD; price-based recalculation is a separate sensitivity
analysis with frozen official rate date, not replacement of the observed amount.

## Isolation and hooks

Before persistence, build a fresh workspace/session and a minimal environment allowlist; no inherited repositories,
user settings, other MCP servers, plugins, account text, secrets, host OS/shell/date/cwd or system-reminder blocks.
Credentials belong only to a trusted out-of-band source adapter and must not enter model-visible schemas/data or
stored traces. Use scoped read-only GitHub access; synthetic fixtures must contain no private real-world data.
Instrument and inspect the full actual model envelope and tool list in memory. A correct init tool list alone
does not prove prompt isolation (BDX-001 demonstrated that). Reject before recording if unknown context/settings
or secret-bearing payloads are found; store only a safe reason code. A model asking what context it received is
not an adequate sole isolation test. No raw provider stdout/stderr should be written first and redacted later.

Primary comparison has hooks disabled in both arms. Separate hook ablation crosses A/B with hooks on/off while
keeping evidence access equal: record first answer, hook decisions, correction turns and final accepted answer.
An A+hook combination uses Buddie for enforcement, so label it hybrid and do not pool it with pure direct A.
Hook-triggered API/token/cost/time are included at their own boundary and in end-to-end totals exactly once.
If the runtime cannot isolate host context or hooks, stop the batch as invalid; do not admit a confound by default.

## Evaluation and analysis plan (pre-register before spending)

Freeze scenario variants, task templates, evaluator version, repetition count, seed, stop rules and budget before
running. Calibrate the evaluator on held-out synthetic negatives (conditional claims, changed heads, missing access,
right text/wrong diff side, false merge prose, private bundle replay). Blind manual adjudication to arm where feasible;
keep raw auto labels and overrides separate. Structural claims and semantic review get separate scores.

For each paired task report distributions and paired differences in end-to-end latency, call counts per boundary,
request/response bytes, all four token counters, USD, accuracy/coverage and number/time/cost of corrections.
Report median and tail quantiles with sample sizes; small pilots are descriptive, not significance claims.
Efficiency primary endpoints: resources per **correct completed task** plus success rate; do not report a cheap
wrong/abstained answer as an efficiency win. Show failed/timeout/rate-limited cases and their consumed resources;
do not exclude them from spend. Do not treat zero calls in a leaked-context answer as tool efficiency.
Generalization beyond fixed fixtures requires a separately authorized live phase and refreshed independent truth.

No results, effect size, provider price or empirical token savings are claimed here.

## Model-free commands

From this directory:

```text
python harness.py prepare --out <new-manifest.json>
python -m unittest discover -s tests -v
```

`prepare` refuses overwrite and writes no secrets; `harness.py run` always refuses. Future live execution requires
a separate implementation/review, explicit approval artifact and cost ceiling; removing the refusal is itself a
reviewable change. The current harness is intentionally non-executing preparation.


## Preparation validation and remaining execution gates

14 local model-free tests pass, including safe null/missing usage, malformed runtime import, mismatched fixture
pairs, explicit tool-name allowlist, counted failure spend, secret-free metric records, disabled paid runner and
synthetic direct/Buddie PR/CI/false-merge adapter smoke. These are instrumentation tests, not model trial results.
`replay.py` smoke covers plumbing for PR/CI and false-merge only. The remaining scenario variants, live connector
adapters, actual model-envelope inspection and blinded evaluator calibration are gates before paid execution.
The preflight reviewed flags are assertions supplied by that trusted future adapter, not self-authenticating
proof from a caller-provided dict. Approval references are similarly not machine-verifiable user authorization.

`analysis.py` separates fixture/variant/comparison-manifest/sampling/runtime/cache/hook identities and reports
paired B−A differences without filling missing resources with zero. The manifest SHA must freeze both arms'
tool schemas, instructions and source permissions; per-arm schema hashes naturally differ and belong inside
that shared manifest. Imported usage is bound to a result digest and frozen-manifest digest, labelled caller-
supplied rather than billing-authenticated. Example import after a separately approved existing trial:
`python harness.py import-runtime --result RESULT.json --manifest FROZEN.json --out SAFE_COUNTERS.json`.
The importer never starts a trial or validates an approval reference as authorization to spend.
