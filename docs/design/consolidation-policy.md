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

A larger operations vocabulary can reduce the declared instruction-labelled share, but does not measure
how much the model decided inside named operations. This note measures declared provenance, not model influence.

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
| `KEEP_RAW_RESPECTED` | every input event of a `keep_raw` kind has its complete canonical body preserved byte-for-byte in NEW raw blocks; normalized snippets are insufficient | `RAW_TOUCHED`: the event was dropped, merged, or fell to a bare anchor or the inside of a range |
| `COVERED` | every actual old/new changed line is covered by the operation's version-qualified old_lines/new_lines (see clarification) | `UNRECORDED_CHANGE`: the summarizer did more than it logged |
| `BASE_MATCH` | supplied OLD/NEW bytes match the declared layer digests and operation ids | `BASE_MISMATCH` |
| `INPUT_INTACT` | the input anchor holds (history module `EVENT_ANCHOR`) | the anchor's own verdict |

Beside the verdicts, two counts no gate reads: the share of changed lines labelled `instruction` (declared operation attribution, not measured model influence), and the share of new lines the history module leaves unchecked. A proposal with every check `HOLDS` is one
whose declared operations and byte changes satisfy these structural constraints; whether it is a good consolidation is not a question this command answers.

Like the rest of `lineage-v1`, `conformance` is read by no gate. A caller that wants to refuse non-conforming
proposals does so on the document.

## Measuring drift

The formats make the comparisons of an experiment possible without buddie running any of it:

| Comparison | Uses |
|---|---|
| per-agent policies vs one shared policy, same summarizer | `divergence --window` over the agents' logs |
| one policy, one input, two summarizers | `retention` between the two proposals' layers; the declared `instruction` share of each |
| agent X's policy on agent Y's log | `divergence` against both agents |
| distance between policies vs distance between histories | policy digests and operation vectors, `divergence` on the logs |

A trend in these is a measurement, not a cause: the harness around it needs its own controls (no consolidation, a
placebo reorganization of the same size), which are outside buddie.

## Threat model

| Actor | Can | So |
|---|---|---|
| The summarizer (a model) | do more than the policy allows, log less than it did, reword under `instruction` | `ALLOWED` and `COVERED` compare the log of operations with the actual diff; work under `instruction` is counted as instruction-labelled, never as policy-conforming detail |
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


## Mechanical conformance clarification — 2026-10-26

Conformance is structural, not proof that an allowed operation was semantically applied correctly. `merge_duplicates`
does not prove two meanings are equivalent; `archive_below_salience` does not establish salience. If exact structural
semantics cannot be specified, classify the change as `instruction`, not deterministic work. It is allowed only
when policy.instructions is nonempty and is counted as instruction-labelled; HOLDS never judges the instruction followed.

Proposal includes exact OLD and NEW byte digests, policy digest/version, input range and operation records with
`old_lines` / `new_lines`. Line ids are `(layer_digest, 1-based LF line index, exact line digest)`; duplicate lines
remain distinct. Deletions reference OLD, additions NEW, replacements both; moves are accounted for on both sides.
`COVERED` is computed against the actual bounded byte diff, not a caller's declared changed-line list. Missing,
out-of-range, inconsistent or ambiguous references make the proposal invalid. `lines` naming only NEW cannot
cover a deletion and is superseded by these two explicit fields in the proposed v1 contract.

`keep_raw` applies to every selected input event of the declared kinds, not only those OLD happened to quote.
NEW must retain the complete canonical body in a tagged raw block with full event identity/digest. Comparing only a
FOUND_NORMALIZED quotation could retain one word and is not raw preservation. This can be expensive; the caller
may choose a narrower input range/policy, but the checker cannot silently weaken keep_raw. Log retention itself
is the caller's responsibility and not proven by a quote. Confirmed/proposed operation states are explicit;
any op listed in confirm may only be proposed, never marked applied by a summarizer's assertion.

Policy/input/model metadata can all be rewritten by the same OS user. A matching hash proves consistency of the
provided tuple, not historical authority. Apply the external checkpoint contract from history-and-lineage.md to
any historical claim. Accepting a proposal is not user authorization to write a different project's state.
Unknown schema/op/parameter, truncated or unreadable inputs produce invalid/uncheckable results, never partial
success. Add fixtures for deletion-only changes, duplicate/moved lines, altered OLD/NEW digests, normalized snippets
masquerading as keep_raw, and instruction under an empty instructions policy. All are planned tests, not shipped.


All operation event refs must be within the authorized input log/epoch/range and match that immutable snapshot;
a reference to a true event outside the allowed input is not admissible. BASE_MATCH precedes byte-diff coverage.
Instruction-labelled share counts distinct changed old/new line identities in the actual diff once each. Overlap
with any instruction operation makes that identity instruction-labelled; duplicate attribution cannot inflate
the denominator. No changed identities gives share=null with reason=no_changes, not 0 or a claim of no model input.
Even a zero instruction-labelled share does not establish model independence inside named operations.
