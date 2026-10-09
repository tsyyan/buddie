---
name: buddie
description: Evidence check at the hand-off between agents. Use when you receive an executor's report or hand in your own - quotes with links and ⚓ anchors (repo state, PR, CI, command output) are checked by code (verify_report), and a receipt line goes with the report.
---

# buddie: check a report at the hand-off

An error in an orchestrator chat multiplies as it is restated: executor → orchestrator → human. buddie checks what can
be checked without a model, at both ends of the hand-off, and writes a receipt.

| In the report | Checked by | Bad outcome |
|---|---|---|
| A quotation in quotation marks with a link | `verbatim`: the words are in the bytes of a snapshot of that link | `NOT_FOUND` |
| Anchor `⚓ path#sha256`, `⚓ path@commit`, `⚓ fact=value` | the file, commit or fact in the session's repositories | `BROKEN` |
| Anchor `⚓ pr:OWNER/REPO#N=merged[@SHA]`, `⚓ ci:OWNER/REPO@SHA=success` | PR state and the checks on the commit, via the GitHub API | `BROKEN` |
| Anchor `⚓ run:CMD => OUT` ("I ran it and got this") | a call with CMD and a result containing OUT in the session transcript | `BROKEN` |

Receipt outcome: `FAIL` (any `NOT_FOUND` or `BROKEN`), `GAPS` (something could not be checked: source unavailable,
quote without a link, anchor in another repository), `PASS`, `EMPTY` (nothing to check).

## Executor: before handing in

1. Snapshot sources before reading them: the `snap` tool (or `verbatim snap URL`). Copy quotes from `source_text`
   (or `verbatim text URL --grep …`), not from a summary of the page.
2. Write repo numbers and states with an anchor (`⚓ path@commit` for history, `⚓ path#sha256` for current bytes).
   "Merged", "CI is green", "tests passed" get an anchor too: `⚓ pr:octo/app#54=merged@9653a7c`,
   `⚓ ci:octo/app@dbf390f=success`, `⚓ run:pytest -q => 41 passed`. Copy OUT from the tool output, not from memory.
   A PR that is not merged yet is `⚓ pr:…=open`, not "will be merged". A final answer that claims work in prose with
   no anchor on the line is returned by the hook with ready anchors, and a `buddie:` line does not let it through;
   other messages only count such lines (`prose_work` in the receipt).
3. Before sending, call `verify_report` with the report text. Fix every `FAIL`. What cannot be fixed stays, with a line
   starting with `buddie:` that says what is unconfirmed and why. A broken `pr:`, `ci:` or `run:` anchor, or work claimed
   in prose in a final answer, cannot stay: correct or add the anchor, or remove the claim.
4. Put the receipt's `predicate.line` at the end of the report.

## Orchestrator: when receiving a report

1. Run the executor's report through `verify_report` yourself; do not rely on its receipt line. A check at the
   hand-off is independent of self-checking.
2. `FAIL`: do not pass it to the human as is. Send the `blocking` items back to the executor, or restate the result
   without the unconfirmed part and say so.
3. `GAPS`: pass it on, naming what was not checked (`gaps`).
4. In the summary for the human, put one receipt line next to the result, for example
   `buddie PASS: quotes 12/12 found; anchors 4/4 hold`.

## Orchestrator: the summary when no subagent is left

1. The hook says when (on `Stop`, when no subagent is live and results are not summarized yet). Without the hook:
   when the last subagent has handed in.
2. Call `summary` (buddie MCP, or `run.py summary --text`). Show its `text` as is: the facts in it are collected by
   code; add none of your own.
3. Launch the `auto` steps yourself. If there is a `card`, ask `AskUserQuestion` with that `card`: keep its options
   and `metadata`, labels may be shortened. Where there is no card UI, list the options with numbers.
4. Launch what was picked with the anchor ⚓ `choice:<summary_id>=<step>` in the brief and in the launch report;
   "launched with consent" without such an anchor or a quote is unconfirmed consent.

## The hook (when the plugin is installed)

Before a message leaves the session and when the turn stops, the hook runs the same `verify_report`. On `FAIL` it
returns the items to the model (exit code 2), and the message goes out only fixed or with a `buddie:` line; a `buddie:` line does not cover a broken effect anchor. `GAPS` does
not block. `BUDDIE_FETCH=0` turns off page fetching in the hook; `BUDDIE_REPOS=dir:dir` sets the repositories for
anchors.

## What buddie does not check

Paraphrase without quotation marks, whether a found quote supports the claim around it, times and time zones. Those
need a reader; when it matters, use two independent readers that share no context with the author. A `PASS` receipt
means "the words and anchors are where the report says", not "the conclusion is right".
