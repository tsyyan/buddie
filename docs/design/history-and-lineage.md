# Design: the history module and `buddie lineage`

Status: proposed, not implemented. This note is written before the code, as its contract. The user-facing pages
would be a section of [verification.md](../verification.md) (the module) and a new `lineage.md` (the command).

## The problem

An agent that keeps working across sessions keeps a raw record of what happened (an event log) and, beside it,
derived memory: summaries, consolidated notes, "what I learned", written by the agent itself or by a background
process between sessions. Each consolidation pass rewrites the derived layer. Three things can go wrong, and none
of them is visible in the derived text:

- **unsupported claims**: the derived layer states something the log does not hold ("the user approved X", "the
  test failed twice"), written by a summarizer that guessed or flattered;
- **lost detail**: a pass drops events that mattered, rare ones first, because they did not fit a summary;
- **drift from outside**: when one summarizer serves many agents, its own habits enter every agent's memory, and
  the agents grow more alike for a reason that is not theirs.

buddie already answers the first question for reports and web pages: a quotation against the bytes it cites, with
no model. The history module answers it for derived memory against the event log. The second and third questions
are not claims in a text: they are measurements over versions and over agents, so they go to a separate command,
`buddie lineage`, which no gate reads (as freshness and environment snapshots are kept today).

The roles stay apart: a model proposes the derived layer, buddie checks it. buddie has no model of its own, so it
cannot pull agents towards one.

## Scope

| | In | Out |
|---|---|---|
| history module | event anchors, quotations from events, numbers in quoted events, log integrity of the cited range | whether a paraphrase is a fair summary; whether a consolidation is *good* |
| `buddie lineage` | chain integrity of a whole log, what a new derived version drops, divergence between agents' action logs | judging behaviour, scoring agents, deciding which version to keep |

Nothing here names HAVEN or any agent platform. The log format below is generic; an adapter that writes it is a
caller's business, as with every other module input (architecture.md, "Modules").

## The event log

An input, not something buddie writes. JSON Lines, one event per line, append-only:

```json
{"v": 1, "log": "res-7f3a", "seq": 41, "at": "2026-10-25T18:02:11Z", "kind": "tool_result",
 "body": {...}, "prev": "sha256:9c1e…", "sha256": "sha256:4b0d…"}
```

- `log`: a stable id of the log (one agent's history), `[A-Za-z0-9._-]{1,64}`.
- `seq`: 0, 1, 2, … with no gaps.
- `sha256`: of the canonical JSON of the event without the `sha256` field (`sort_keys`, separators
  `(",", ":")`, `ensure_ascii=False`, UTF-8: the same canonical form `receipts.py` uses).
- `prev`: the `sha256` of event `seq - 1`; `null` for `seq` 0.
- `kind` and `body`: the caller's; buddie reads `body` only as text to quote from (the *visible text* of an event
  is defined per `kind` by a small fixed table, else the JSON string values of `body` in key order).

A log is read through a **log store** (`buddie/history/store.py`), a directory `<store>/logs/<log>.jsonl` with the
same discipline as the snapshot store: never modified by buddie, located by an explicit argument
(`--history DIR`, MCP `history`), never by an environment variable the agent's shell exports and the hook would
not see (stores.py, NEXT §37). A log whose file the agent can write is the agent's statement of its history, not
attestation: see the threat model.

## Module `history`

A new entry in `modules.REGISTRY`:

```python
Module("history", (Check.EVENT_ANCHOR, Check.EVENT_QUOTE), ("history",),
       "derived memory against the event log it cites: ev: anchors and quotations from events")
```

### Anchors

```
⚓ ev:LOG#SEQ                 the event exists
⚓ ev:LOG#SEQ@SHA             … and its sha256 starts with SHA (at least 12 hex)
⚓ ev:LOG#FROM-TO@SHA         a range; SHA is the sha256 of event TO, which by the chain fixes FROM..TO
```

`EVENT_ANCHOR` verdicts, in the checker's own words, translated in `findings.py` by an exhaustive table:

| Verdict | Fact | Reason |
|---|---|---|
| `HOLDS` | SUPPORTED | the event (range) is there, the digest matches, the chain from FROM to TO is unbroken |
| `DIGEST_MISMATCH` | CONTRADICTED | the event is there with other bytes: the log or the anchor was rewritten |
| `NO_SUCH_EVENT` | CONTRADICTED | the log has fewer events, or no such log in the store |
| `CHAIN_BROKEN` | CONTRADICTED | a `prev` inside the range does not match: a gap, a reordering or an edit |
| `LOG_UNAVAILABLE` | UNDETERMINED | no log store given, or the file unreadable |

### Quotations from events

A quotation followed by an event anchor on the same line (the way a web quotation is followed by its link):

```
The person asked to keep the old parser: "keep v1 parsing until the migration lands" ⚓ ev:res-7f3a#41@4b0d1e9a2c77
```

`EVENT_QUOTE` reuses the verbatim engine unchanged: the event's visible text is a `Page`, the same normalization,
the same `FOUND` / `FOUND_NORMALIZED` / `NOT_IN_SOURCE` / `AMBIGUOUS_MISS` reason codes, the same number check on
the quoted sentence (`--numbers gap|fail|off`). Only where the page comes from differs: the log store instead of the
snapshot store, and the digest the finding carries is the event's `sha256`, `core.Provenance`
`AGENT_WRITABLE` when the log store is a place the agent under check can write, else `CALLER_SUPPLIED` (buddie
read the bytes, it does not know who wrote them).

A quotation whose anchor fails is not checked against anything else: `LOG_UNAVAILABLE` gives UNDETERMINED, the other
anchor verdicts make the quotation CONTRADICTED with the anchor's reason.

### What it does not check

Prose without a quotation or an anchor. "The agent usually prefers small commits" is a claim no check detects; the
receipt's `scope.excluded` cannot count it (`detected: null`), and `unanchored_lines` reports such lines as it
does for reports today. The consequence is a requirement on whoever writes the derived layer, not on buddie:
**every claim of derived memory carries a quotation from an event or an event anchor.** Under that convention
almost everything is checkable; the rest is said to be unchecked, never passed.

### Interfaces

- `buddie verify MEMORY.md --history DIR [--modules history]`, the receipt as for any report.
- MCP `verify_report` with `history`; a new read-only tool `event_text` (the visible text of one event, optionally
  around a regex), the counterpart of `source_text`, so that a summarizer copies quotations from bytes, not from
  its own recollection.
- The hook: the module runs when a `buddie.toml` names a log store (`[history] store = "…"`); its gate class is
  `history`, default `warn`, under the protected policy's floors like every class.

## Command `buddie lineage`

A separate document, `lineage-v1`, read by no gate. Three subcommands, each deterministic, each saying what it
could not establish.

### `buddie lineage chain LOG`

The whole log: every `sha256` recomputed, every `prev` followed, `seq` without gaps. Answers `INTACT`, `BROKEN`
(with the first bad `seq` and why) or `UNREADABLE`. `INTACT` means the file is self-consistent, not that nobody
rewrote it from the start: pinning a head digest outside the agent's reach (the protected policy, or a receipt
another party keeps) is what turns it into a statement about history.

### `buddie lineage retention OLD NEW --history DIR`

Two versions of a derived layer. For each: the set of events it cites (anchors and quotations), and the set of
*marked entities* in it (a fixed, declared extraction: anchors, `path`s, URLs, numbers with units, identifiers in
backticks; no named-entity model). The document lists:

- events cited by OLD and by no line of NEW, with each event's `kind` and how often that `kind` occurs in the log
  (the rarer, the earlier it is listed);
- marked entities of OLD absent from NEW;
- lines of NEW that cite nothing (the unchecked share, as a count and a fraction).

It never says the loss is bad: dropping is what consolidation does. It makes the drop visible and reviewable.

### `buddie lineage divergence LOG… --history DIR [--features FILE]`

Several agents' logs. Features are counts the log records without interpretation: distribution of `kind`, of tool
names in tool events, lengths of runs between events of declared kinds. `--features` names which, from a fixed
vocabulary; nothing is evaluated from the file. Output: per log the feature vector, and between logs the
Jensen–Shannon distance per feature and overall, with the number of events each rests on. With `--window N` it
gives the same per window of N events, so a trend over time (agents growing alike after a consolidation regime
starts) is a series, not a single number.

It reports distances, not causes: whether a convergence comes from a summarizer or from the tasks is a question
of the experiment around it, which needs its own controls.

## Threat model

| Actor | Can | So |
|---|---|---|
| The summarizer (a model) | write any derived text, cite events that do not say it, invent anchors | every cited event is read and compared by bytes; a claim it does not anchor is unchecked, never supported |
| The agent, same OS user | rewrite the log file, its own anchors, `buddie.toml` | a self-consistent rewrite passes `chain`; only a head digest pinned outside its reach (protected policy, an external receipt) detects it. buddie reports what the bytes say, not who wrote them |
| An administrator | write the protected policy | can pin log heads and set the `history` gate floor |
| The log itself | be huge, malformed, have hostile text | bounded reads (`MAX_PAGE_BYTES` per event, a line limit per log), strict JSON shapes, a malformed line is `UNREADABLE` at that `seq`, never skipped; regexes only as `patterns.py` bounds them |

## Deliberately not here

- Judging whether a paraphrase is faithful. That needs a model or a classifier; buddie stays without either, so its
  verdict cannot be argued with. A caller that wants a model's opinion records it as a separate, labelled finding.
- Running agents, probe batteries or placebo consolidations. Those belong to the experiment harness; buddie can
  check the reports they produce and give receipts for them.
- Writing or repairing logs. buddie reads evidence; it does not become the system of record.

## Tests

- `tests/test_history.py`: every verdict of both checks, including a quotation that is only in a neighbouring event,
  a range with one edited event, a log store given by environment only (refused).
- `tests/test_modules.py`: the new checks belong to exactly one module; an unselected `history` is GAPS, never PASS.
- `tests/test_adversarial.py`: rows for a forged anchor digest, a reordered log, an oversized event, a quotation
  split across two events.
- `tests/test_lineage.py`: `chain` on intact and broken logs; `retention` on a fixture pair with a dropped rare
  event; `divergence` on identical logs (distance 0) and disjoint ones (distance 1).
