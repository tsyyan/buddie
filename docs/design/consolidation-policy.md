# Design: per-agent consolidation policies and `buddie lineage conformance`

Status: proposed, not implemented. This note is written before the code, as its contract, and builds on
[history-and-lineage.md](history-and-lineage.md): the history module and `buddie lineage` are assumed. The
user-facing page would be a section of the proposed `lineage.md`.

## The problem

history-and-lineage.md names drift from outside: when one summarizer serves many agents, its own habits enter every
agent's memory. The obvious remedy is to let each agent write its own rules for the summarizer: what to merge, what
to drop, what to keep raw, what needs its confirmation. That moves the drift, it does not remove it:

- **rules are interpreted**: "merge duplicate observations" is decided by the summarizer's model, the same way for
  every agent, so the habits return one level down, in what counts as a duplicate;
- **the summarizer does more than it was told**: it "improves" beyond the rules, and the result looks like the
  agent's own consolidation;
- **the agent's rules can be self-serving**: "keep only what supports the current plan" is a policy too.

None of this is visible in the derived text. This note fixes a policy format with a part that can be checked
without a model, a proposal format that records what was done under which rule, and one deterministic check,
`buddie lineage conformance`: did the proposal do only what the policy allowed.

The roles stay as in history-and-lineage.md: the agent writes the policy, a model proposes the derived layer,
buddie checks the proposal against the policy and the log. buddie does not run the summarizer and holds no policy
of its own.

## Scope

| | In | Out |
|---|---|---|
| policy format | a declared operation vocabulary with parameters, free-text instructions kept apart | which policy is good; who wrote it |
| proposal format | the diff to the derived layer, the operation log, provenance of the run | storing or applying proposals |
| `conformance` | every recorded operation is allowed by the policy; every change is covered by a recorded operation; free-text work is counted, not judged | whether a free-text instruction was followed well |

Nothing here names an agent platform. Both formats are inputs a caller's adapter writes, as with the event log.

## The policy

`consolidation-policy-v1`, a JSON document the agent keeps beside its derived memory and versions like any of it:

```json
{"v": 1, "log": "res-7f3a", "version": 4,
 "operations": [
   {"op": "merge_duplicates", "kinds": ["observation"], "max_group": 5},
   {"op": "summarize_window", "kinds": ["tool_result"], "window": 50},
   {"op": "keep_raw", "kinds": ["decision", "person_message"]},
   {"op": "flag_contradiction"}],
 "instructions": "Prefer keeping failed attempts over successful routine runs.",
 "confirm": ["archive_below_salience"]}
```

- `operations`: drawn from a fixed vocabulary (`merge_duplicates`, `summarize_window`, `link_events`,
  `archive_below_salience`, `flag_contradiction`, `keep_raw`), each with its declared parameters; an unknown
  operation or parameter makes the policy `INVALID`, not partly read. The vocabulary grows by review of this file,
  not at run time.
- `instructions`: free text for what the vocabulary cannot say. buddie never interprets it; it only counts how
  much of a proposal rests on it.
- `confirm`: operations the agent wants to decide itself; a proposal may suggest them, never record them as done.

The more of a policy is in `operations`, the smaller the share a summarizer's model decides. The agent sets that
share; this note only makes it measurable.

## The proposal

`consolidation-proposal-v1`, written by whatever ran the summarizer:

- `policy`: `log`, `version` and the `sha256` of the canonical policy JSON (canonical form as in receipts.py);
- `input`: the event range the run saw, as an `ev:LOG#FROM-TO@SHA` anchor, and the `sha256` of the derived layer it
  started from;
- `runner`: model id and version, sampling parameters, seed; buddie records these as stated, it cannot check them;
- `operations`: one entry per change, `{op, params, events: [ev anchors], lines: [line ids of the new layer]}`,
  with `op` either from the vocabulary or `instruction` (a change made under the free text);
- `diff`: the new derived layer, whose lines carry quotations or anchors as the history module requires.

## Command `buddie lineage conformance POLICY PROPOSAL --history DIR`

Deterministic; reads the policy, the proposal, the two derived versions and the cited log range. Per check a
verdict and, when not `HOLDS`, the operations or lines it rests on:

| Check | `HOLDS` when | Otherwise |
|---|---|---|
| `POLICY_MATCH` | the proposal's policy digest is the policy given | `POLICY_MISMATCH`: checked against another version |
| `ALLOWED` | every recorded `op` is in the policy, with parameters inside the declared ones | `NOT_ALLOWED`, listing each op |
| `CONFIRM_RESPECTED` | no op listed in `confirm` is recorded as done | `DONE_WITHOUT_CONFIRM` |
| `KEEP_RAW_RESPECTED` | no event of a `keep_raw` kind is dropped or merged (by `retention` on the two versions) | `RAW_TOUCHED` |
| `COVERED` | every line added, changed or removed between the versions is in some operation's `lines` | `UNRECORDED_CHANGE`: the summarizer did more than it logged |
| `INPUT_INTACT` | the input anchor holds (history module `EVENT_ANCHOR`) | the anchor's own verdict |

Beside the verdicts, two counts no gate reads: the share of changed lines under `instruction` (the model-decided
share), and the share of new lines the history module leaves unchecked. A proposal with every check `HOLDS` is one
that stayed inside its policy; whether it is a good consolidation is not a question this command answers.

Like the rest of `lineage-v1`, `conformance` is read by no gate. A caller that wants to refuse non-conforming
proposals does so on the document.

## Measuring drift

The formats make the comparisons of an experiment possible without buddie running any of it:

| Comparison | Uses |
|---|---|
| per-agent policies vs one shared policy, same summarizer | `divergence --window` over the agents' logs |
| one policy, one input, two summarizers | `retention` between the two proposals' layers; the `instruction` share of each |
| agent X's policy on agent Y's log | `divergence` against both agents |
| distance between policies vs distance between histories | policy digests and operation vectors, `divergence` on the logs |

A trend in these is a measurement, not a cause: the harness around it needs its own controls (no consolidation, a
placebo reorganization of the same size), which are outside buddie.

## Threat model

| Actor | Can | So |
|---|---|---|
| The summarizer (a model) | do more than the policy allows, log less than it did, reword under `instruction` | `ALLOWED` and `COVERED` compare the log of operations with the actual diff; work under `instruction` is counted as model-decided, never as policy-conforming detail |
| The runner | misstate the model, seed or input | `runner` is recorded as stated; `INPUT_INTACT` checks only the input range, by bytes |
| The agent, same OS user | write a self-serving policy, rewrite the policy after the fact | the policy digest is in the proposal; a policy that drops what it dislikes conforms, and `retention` still shows what was dropped |
| The policy file | be malformed, name unknown operations | strict shapes; unknown means `INVALID`, the whole policy, and `conformance` gives `UNDETERMINED` |

What it does not defend: a summarizer that records an allowed operation and does what it wanted inside it (a
`merge_duplicates` that merges things that are not duplicates). Within an operation, only the history module's
quotation checks and `retention` apply. And it cannot tell whether the agent wrote its policy freely or took its
model's idea of a good consolidation; that is a question for the experiment.

## Deliberately not here

- Interpreting `instructions`, or judging whether an operation was applied well. That needs a model.
- Running summarizers, storing proposals, applying accepted ones, or keeping the branch they sit on.
- Proposals that change the policy itself: a caller keeps those apart from memory proposals; buddie checks only
  that a proposal's policy digest matches.

## Tests

- `tests/test_consolidation_policy.py`: a valid policy; an unknown op and an unknown parameter (both `INVALID`).
- `tests/test_lineage.py`: every `conformance` verdict on a fixture pair, including a change logged under no
  operation, a `keep_raw` event merged, an op from `confirm` recorded as done, and a proposal against an older
  policy version.
- `tests/test_adversarial.py`: rows for a proposal whose operation log omits a deleted line, and one whose input
  anchor points at a rewritten range.
