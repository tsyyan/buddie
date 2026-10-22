# Receipts: v0 and v1

A receipt is buddie's statement of one check of one text. It is an [in-toto Statement](https://in-toto.io/): the
`subject` is the sha256 of the text, the `predicate` holds what buddie found. Two contracts exist:

| Contract | `predicateType` | Default |
|---|---|---|
| receipt-v0 | `https://github.com/tsyyan/buddie#receipt-v0` | yes: `verify()`, the CLI, MCP, the remote server, the hook and the journal |
| receipt-v1 | `https://github.com/tsyyan/buddie#receipt-v1` | only when asked for |

**The version is the `predicateType`, and only that.** There is no second version field to disagree with it. The
buddie version that produced the receipt is a separate field (v0 `predicate.tool`, v1 `predicate.producer`), and
so are the profile, the outcome and the coverage.

**Read this first.** `PASS` does not mean that every statement in the report is true. It means the checks that ran
established no failure and found nothing open. Even when every check runs (coverage `FULL`), buddie finds only claims
written in a form it checks: a quotation with its link, a `⚓` anchor, a work claim against the queue. A claim written
any other way is not detected by any check.

## Why v1

receipt-v0's `outcome` (`PASS`, `FAIL`, `GAPS`, `EMPTY`) describes the checks that ran. After a partial run (a
profile, `--anchors-only`, `numbers=off`) it can say `PASS`, and nothing in the receipt says that quotations or
anchors in the text were never looked at. receipt-v1 keeps five things apart: what was established
(`verification`), what ran and what did not and why (`scope`), how complete that is (`scope.coverage`), and where
the evidence came from (`evidence`).

## Asking for v1

| Surface | How | Default |
|---|---|---|
| Python | `receipts.render(verify.assessment(text, …), "v1")` | `render(a)` and `render(a, "v0")` give receipt-v0; `verify()`, `assess()` and `assess_selected()` are unchanged |
| CLI | `buddie verify report.md --receipt v1 --json out.json` | `--receipt v0`. The summary line becomes the v1 one; the `BLOCK`/`gap`/`note` lines and the exit code (1 on FAIL) stay the same |
| MCP | `verify_report` with `"receipt": "v1"` | `"v0"`. `structuredContent` is the receipt in the contract asked for; its `predicateType` says which |
| Remote MCP | not offered | its argument contract is unchanged; it returns receipt-v0 |
| Hook and journal | not offered | the gate decides on its findings and receipt-v0; the journal is unchanged |

An unknown version (`"v2"`, `"1"`, `"V1"`) is an error: CLI exit 2, an MCP tool error,
`receipts.UnknownReceiptVersion` in Python. It never falls back. The JSON Schema is printed by
`buddie receipt-schema` and checked in as [receipt-v1.schema.json](receipt-v1.schema.json).

**One check, two renderings.** `verify.assessment()` runs the check once. `receipts.render()` only serializes it: it
never runs a check again, changes no finding, and takes no part in which checks run or how evidence is trusted. The
receipt-v0 of an Assessment without a selection is `verify()`'s, byte for byte.

## receipt-v1, field by field

```
_type                         "https://in-toto.io/Statement/v1"
subject[]                     {name, digest: {sha256}}: the text, as in v0
predicateType                 "https://github.com/tsyyan/buddie#receipt-v1"
predicate
  producer                    {buddie, verbatim}: the software versions (verbatim null when no quotation check ran)
  checked_at                  UTC time of the check
  verification
    outcome                   PASS | FAIL | GAPS | UNKNOWN | EMPTY | NOT_RUN (below)
    numbers                   gap | fail | off: the mode a contradicted number was decided under
    counts                    {supported, contradicted, no_claim, undetermined, unrecognized}: findings per fact
    findings[]                one per claim checked, in the receipt's order:
      check, module           a core.Check id and its module id
      line                    the line of the text, or null
      subject                 the claim: the quotation, the number, the anchor, the work claim's kind
      verdict                 the checker's own word (FOUND, NOT_FOUND, HOLDS, BROKEN, UNCHECKABLE, …)
      fact                    supported | contradicted | no_claim | undetermined | unrecognized
      reason                  a core.ReasonCode (found, not_in_source, source_unavailable, broken, …)
      decision                block | flag | allow, under `numbers`
      message                 for a person, or null; code reads `reason`
      evidence[]              {kind, locator, provenance, digest, source, observed_at} (below)
  scope
    requested                 {profile, checks}: what was asked for; null and null when nothing was (everything)
    effective                 the checks selected after the profile, the gate levels and the protected policy's floors
    executed                  the checks whose checker ran
    excluded[]                every other check, once: {check, module, reason, detected}
      reason                  profile | gate_level | call_option | unavailable (below)
      detected                claims of that kind in the text, counted without checking: quotations and anchors
                              (0 when there are none); null for numbers and work claims, which take the check to count
    coverage                  FULL | PARTIAL | UNKNOWN | NONE (below)
    signals                   {name: count}: what no check judges, as in v0 (unanchored_count_lines,
                              prose_work_claims, short_quotes, unlinked_terms)
  evidence
    provenance                {caller_supplied, agent_writable, collector_observed, unknown}: evidence references
                              of each provenance across the findings
```

Every list of checks is in `core.Check` order, each check once, whatever order a caller named them in:
`quote, number, file_anchor, commit_anchor, fact_anchor, pr_anchor, ci_anchor, run_anchor, choice_anchor,
work_claim, other_anchor`. `receipts.dumps()` gives canonical JSON (sorted keys, no spaces): the same receipt is the
same bytes.

### Outcome: what the checks that ran established

| Outcome | Means |
|---|---|
| `FAIL` | a finding the policy blocks: a quotation not on its page, a broken anchor, a contradicted work claim; a number not on its page with `numbers = "fail"` |
| `UNKNOWN` | a verdict buddie does not recognize; never taken for support |
| `GAPS` | something undetermined: a source unreadable, a repo or GitHub out of reach, a number not on its page with `numbers = "gap"` |
| `PASS` | every finding supported, or a claim the text does not make |
| `EMPTY` | checks ran and found nothing of their kinds to judge |
| `NOT_RUN` | no check ran |

The outcome never looks at scope: a `PASS` with coverage `PARTIAL` is a pass of what ran.

### Exclusion reasons

| Reason | The check… |
|---|---|
| `profile` | is not in the requested profile |
| `gate_level` | is in the requested profile, but the effective gate levels turned it off (the hook) |
| `call_option` | was selected, but an option of the call turned it off: `quotes=False` / `--anchors-only`, `numbers="off"`, `mandate=False` |
| `unavailable` | was selected and asked for, but this run had nothing to check it with: work claims without a `buddie.toml` `[mandate]` |

buddie never says a check was "not applicable": whether the text holds claims a check would have found can't be
established without running it. `detected` counts what can be counted without checking.

### Coverage: how much of what buddie has ran

| Coverage | Means |
|---|---|
| `FULL` | every check buddie has ran |
| `PARTIAL` | something was left out on purpose: a `profile`, `gate_level` or `call_option` exclusion |
| `UNKNOWN` | only `unavailable` checks are missing, so whether they would have applied cannot be told. This is the common case for a project without `[mandate]` |
| `NONE` | no check ran |

**`FULL` means full execution coverage of buddie's registered verification checks, not exhaustive factual
coverage of the report.** Every check ran; that says nothing about how many of the report's claims were in a form a
check detects. So:

| Outcome and coverage | Means |
|---|---|
| `PASS` + `FULL` | every check ran and established no failure. The answer is **not** thereby true: a claim not written as a quotation with its link, an anchor or a work claim was not detected by any check |
| `EMPTY` + `FULL` | every check ran and found no claim it can judge |
| `PASS` + `PARTIAL` | the selected checks passed, and others were left out on purpose (`excluded`) |
| `NOT_RUN` + `NONE` | no verification was performed |

There is no percentage. The number of checks is not a denominator of the claims in a text. `excluded[].detected`
gives the counts that can be had.

### Evidence and provenance

Each finding's `evidence` lists what it was judged on, with the provenance it had inside buddie (PR #29,
[policy.md](policy.md#provenance)):
- `collector_observed`: buddie's own collector received it during this check, over TLS, from the endpoint buddie
  chose, with nothing the environment set in between. That says who answered, not that the answer is true.
- `caller_supplied`: handed in by whoever ran the check (a GitHub function of their own, an API the environment
  named, a session transcript).
- `agent_writable`: a place the agent under check can write (the repo, its history, buddie's journal).
- `unknown`: bytes whose origin buddie cannot tell, for example a snapshot already on disk.

A receipt reports provenance, it does not raise it. Rendering a receipt promotes nothing, and nothing in a receipt
authorizes a source. `evidence.provenance` is a count of the references in `findings`, which `receipts.problems()`
checks.

## Examples

**Partial: `--profile research`** on a text with a quotation that holds and a broken `path#sha256` anchor:

```json
"verification": {"outcome": "PASS", "numbers": "gap",
  "counts": {"supported": 1, "contradicted": 0, "no_claim": 0, "undetermined": 0, "unrecognized": 0},
  "findings": [{"check": "quote", "module": "sources", "line": 1, "verdict": "FOUND", "fact": "supported",
    "reason": "found", "decision": "allow", "evidence": [{"kind": "snapshot", "provenance": "unknown", "…": "…"}]}]},
"scope": {"requested": {"profile": "research", "checks": ["quote", "number"]},
  "effective": ["quote", "number"], "executed": ["quote", "number"],
  "excluded": [{"check": "file_anchor", "module": "github", "reason": "profile", "detected": 1},
               {"check": "commit_anchor", "module": "github", "reason": "profile", "detected": 0}, "…"],
  "coverage": "PARTIAL", "signals": {}}
```

receipt-v0 of the same check says `"outcome": "PASS"`, and nothing about the anchor.

**Empty**: a hook profile whose levels turn off every class it feeds (`profile = "research"`, `quotes` and
`numbers` off):

```json
"verification": {"outcome": "NOT_RUN", "findings": [], "…": "…"},
"scope": {"requested": {"profile": "research", "checks": ["quote", "number"]}, "effective": [], "executed": [],
  "excluded": [{"check": "quote", "module": "sources", "reason": "gate_level", "detected": 1}, "…"],
  "coverage": "NONE"}
```

**Full, nothing claimed**: every check ran (a project with `[mandate]`) on a text with no quotation, anchor or work
claim gives `"outcome": "EMPTY"` and `"coverage": "FULL"`. Every check ran and none had anything to judge. That is
not "verified".

**Inconclusive**: a quotation whose page cannot be read gives `"outcome": "GAPS"` and a finding with
`"fact": "undetermined"` and `"reason": "source_unavailable"`. The check ran (it is in `executed`) and lacked
evidence. That's different from a check that never ran, which is in `excluded`.

## v0 and v1 for the same check

| receipt-v0 `outcome` | receipt-v1 `verification.outcome` |
|---|---|
| `FAIL` | `FAIL` |
| `PASS` | `PASS` |
| `GAPS` | `GAPS`, or `UNKNOWN` when a verdict was unrecognized (v0 counts it as a gap) |
| `EMPTY` | `EMPTY` (checks ran, nothing to judge) or `NOT_RUN` (nothing ran) |

Both come from the same findings under the same policy, so they never contradict: v0 `FAIL` is exactly v1 `FAIL`,
and the CLI's exit code is the same for both. v1 adds what v0 never had: the scope.

## Profiles and the protected policy

`scope.requested` is what was asked for. `scope.effective` is what that came to after every level and the policy's
floors. Under a policy with `anchors = "block"`, `profile = "research"` runs the anchor checks too, and `executed`
lists them, not the preset. The receipt describes what ran. It says nothing about whether a policy was in force:
no field claims that, and a reader cannot learn it from a receipt.

## Trust in a receipt

A receipt is made by whoever ran buddie and is not signed. Anyone who can run buddie, or edit a JSON file, can
produce one. `receipts.problems(receipt)` checks a receipt-v1 for internal consistency:
- every check once and in order, `requested.checks` included;
- `requested.profile` and `requested.checks` both given or both null (null: every registered check requested);
- `executed` within `effective`, and no check both executed and excluded;
- `excluded` exactly the rest, with the reason the scope implies: `profile` for a check neither requested nor
  effective, `gate_level` for one requested but not effective, `call_option` or `unavailable` for one effective that
  did not run. A check `effective` holds beyond the request (a protected-policy floor's) ran: it is not an exclusion;
- coverage and outcome as the rest of the receipt implies;
- counts and provenance as the findings say.

A receipt that passes is coherent, not authentic. Trust a receipt as far as you trust the process that produced it.
To be sure, re-run buddie on the text: the `subject` digest names it.

A receipt holds what v0 already held: the claims as written, their URLs and anchors, snapshot digests. It carries no
token, no environment variable, no source page text, and no policy file or path of its own.

## Migrating and consuming

- Nothing changes for an existing consumer: v0 is the default everywhere and is unchanged.
- A consumer that wants scope asks for v1 and dispatches on `predicateType`, rejecting any type it does not know.
- **Accept** a report only on `verification.outcome == "PASS"` and a coverage your use needs (`FULL`, or
  `PARTIAL`/`UNKNOWN` with the `excluded` checks you can do without). Treat `EMPTY` and `NOT_RUN` as "nothing
  verified", and `GAPS` and `UNKNOWN` as "not established".
- Read `excluded[].detected`: a `PARTIAL` with a quotation or an anchor left in the text is a report with unchecked
  claims.

## Limits

- Detection: a claim not written in a checked form is not found by any check, under any coverage.
- `detected` is counted for quotations and anchors only.
- In the hook, selection is by gate class ([profiles.md](profiles.md)). The hook does not produce v1.
- Not signed, and nothing in it proves enforcement.
