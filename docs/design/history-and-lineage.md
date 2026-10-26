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
  is defined per `kind` by a small fixed table, else each JSON string leaf of `body` as a separate segment in JSON-pointer order; see strict contract below).

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
| `NO_SUCH_EVENT` | CONTRADICTED | a completely read, valid admitted log lacks that event (missing/unreadable/partial log is LOG_UNAVAILABLE) |
| `CHAIN_BROKEN` | CONTRADICTED | a `prev` inside the range does not match: a gap, a reordering or an edit |
| `LOG_UNAVAILABLE` | UNDETERMINED | no log store given, or the file unreadable |

The subject of an `EVENT_ANCHOR` finding is the anchor, never the line it stands on: `HOLDS` says the event exists
with those bytes, nothing about what the line says of it. `the user approved X ⚓ ev:res-7f3a#41@…` with event 41 a
routine tool result gets an anchor that `HOLDS` and a claim nobody checked. Such a line is an **anchor-only line**:
the receipt lists it in `anchor_only_lines` beside `unanchored_lines`, the hook counts it as unchecked, and no
summary or count adds it to what was supported. Only a quotation (below) checks what a line says.

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

Prose without a quotation, and what a line with only an anchor says. "The agent usually prefers small commits" is
a claim no check detects; the receipt's `scope.excluded` cannot count it (`detected: null`), and `unanchored_lines`
reports such lines as it does for reports today. A line with an event anchor and no quotation has its anchor
checked and its claim not (`anchor_only_lines`, above). The consequence is a requirement on whoever writes the
derived layer, not on buddie: **every claim of derived memory carries a quotation from an event.** An anchor alone
is a pointer for a reader, not evidence for the claim. Under that convention almost everything is checkable; the
rest is said to be unchecked, never passed.

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

Two versions of a derived layer. For each: the events it cites, each at one of three levels, and the set of
*marked entities* in it (a fixed, declared extraction: anchors, `path`s, URLs, numbers with units, identifiers in
backticks; no named-entity model). The levels, from strongest:

- **quoted**: a quotation from the event that `EVENT_QUOTE` finds;
- **named**: an anchor to that single event (`ev:LOG#SEQ`), no quotation;
- **in range**: the event lies inside a range anchor (`ev:LOG#FROM-TO`) and is cited by neither of the above.

A range is never expanded into its events as if each were cited: `summarize_window` over 50 events cites one range,
and what of event 23 survived in it is not known. The document lists:

- events cited by OLD and by no line of NEW, with each event's `kind` and how often that `kind` occurs in the log
  (the rarer, the earlier it is listed);
- events whose level fell between OLD and NEW (quoted to named or in range, named to in range), in the same order:
  an event that went from its own quotation to the inside of a range is a drop in all but name;
- marked entities of OLD absent from NEW;
- lines of NEW that quote nothing (the unchecked share, as a count and a fraction, anchor-only lines among them
  counted apart).

It never says the loss is bad: dropping is what consolidation does. It makes the drop visible and reviewable.

### `buddie lineage divergence LOG… --history DIR [--features FILE] [--select FILE] [--window N] [--permutations K]`

Several agents' logs. Features are counts the log records without interpretation: distribution of `kind`, of tool
names in tool events, lengths of runs between events of declared kinds. `--features` names which, from a fixed
vocabulary; nothing is evaluated from the file. Output: per log the feature vector, and between logs the
Jensen–Shannon distance per feature and overall (the unweighted mean over the selected features, each listed), with
the number of events each rests on. With `--window N` it gives the same per window of N events, so a trend over
time (agents growing alike after a consolidation regime starts) is a series, not a single number.

A distance between two agents means nothing without the distance of each agent to itself, and the estimate of a
JS distance from counts is biased upwards on few events: two samples of one source come out apart. So every
distance carries two references, computed by the same command:

- **self-distance**: per log, the distance between its two halves (alternate events of the declared kinds, so
  both halves span the same time), and per window with `--window`; a between-agent distance is reported beside
  the larger of the two agents' self-distances, never alone;
- **permutation floor**: the events of the two logs pooled and split at random into two groups of the original
  sizes, `--permutations K` times (default 200, a seed in the output); the document gives the share of splits at
  least as far apart as the real pair. Deterministic for a given seed.

`--select FILE` restricts every log to events carrying a declared tag in `body` (for instance the id of a probe
task), so agents are compared on the same tasks instead of on whatever each happened to be given. The tag's name is
declared in the file; buddie matches its value as a string and evaluates nothing.

It reports distances, not causes: whether a convergence comes from a summarizer or from the tasks is a question
of the experiment around it, which needs its own controls. Self-distance and the permutation reference are descriptive diagnostics, not proof of a chance effect.
Event autocorrelation, task mixture and multiple comparisons violate a naive permutation interpretation;
no significance or causal claim follows without a separately justified experimental design.

## Threat model

| Actor | Can | So |
|---|---|---|
| The summarizer (a model) | write any derived text, cite events that do not say it, invent anchors | every quotation is compared with the bytes of its event; an anchor without a quotation is checked for existence only and its line counted as anchor-only; a claim it does not quote is unchecked, never supported |
| The agent, same OS user | rewrite the log file, its own anchors, `buddie.toml` | a self-consistent rewrite passes `chain`; only a full head digest pinned outside its reach (protected policy, an external receipt) detects it. buddie reports what the bytes say, not who wrote them |
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
  event, and one where a quoted event is only inside a range in NEW (listed as a fall, not as kept); `divergence`
  on identical logs (distance 0) and disjoint ones (distance 1), on two halves of one long log (between-agent
  distance not above the self-distance and the permutation floor), and a fixed seed giving the same floor twice.


## Merge contract / clarification — 2026-10-26

This is a design-only proposal. History, lineage, new gate classes, `anchor_only_lines`, `event_text`, `--history`
and the example Check enums are **not shipped**. Existing receipt-v1 check/module/reason enums are closed. Before
runtime: #54 R0 golden corpus, R1 explicit journal across all callers, R3 fail-closed, R6 Module API and **RX**
receipt extension/versioning decision (R2 transitively precedes R6). New public vocabulary uses a separately
versioned schema/predicateType with explicit opt-in unless RX approves another tested negotiation strategy.
Do not emit new fields/words under the current immutable v1 schema, edit legacy goldens to hide drift, or silently
extend default tools/list. Include old/new reader×writer tests, IDS updates in the feature PR, and explicit
catalog/hook migration review. Existing interfaces/default gating remain unchanged by this docs PR.

### Responsibility boundaries

History checks cited bytes/existence and chain structure, never intent, approval or semantic truth. Lineage is a
separate deterministic measurement document read by no gate. Context Integrity compares scoped current claims
with admitted observations; Projects (#57) manages optional registry/focus/workstream claims inside Buddie.
Neither Projects state nor a saved receipt supplies a trusted log checkpoint by virtue of its name or hash.
#55 literal GitHub evidence is similarly scoped: a quoted PR body saying merged is not current merge evidence.
The resident reflection note is an external caller/application sketch, not a new Buddie runtime, scheduler,
paid model service or Projects implementation. Buddie itself does not invoke a model or mutate raw history.

### Strict event bytes, reading and disclosure

History-store schema v1 has exact required keys `v,log,seq,at,kind,body,prev,sha256`, no duplicate JSON keys,
unknown fields, NaN/Infinity or non-integer/bool sequence numbers. `v` is integer 1; `seq` is nonnegative integer;
`at` is RFC3339 UTC text, recorded as supplied (not proof of time). Hashes are lowercase full 64-hex SHA-256 with
`sha256:` prefix; genesis prev=null only at seq=0. Body permits only JSON objects/arrays/strings/booleans/null and
bounded integers; floats are rejected in v1 to avoid cross-runtime numeric serialization ambiguity. The canonical
form is the documented Python UTF-8 JSON encoding, not a claim of compliance with JCS. Hash excludes only sha256;
all other required fields including log identity/sequence/prev are covered. Reject unsupported schema as a whole.

Proposed read limits: 1 MiB UTF-8 per JSONL record, 100,000 events and 128 MiB per log, 30-second monotonic operation
budget. Limit/read/permission failure is UNREADABLE/LOG_UNAVAILABLE with partial coverage; never prove absence
from a prefix. File missing/inaccessible is LOG_UNAVAILABLE; NO_SUCH_EVENT requires a complete valid selected log.
Use one bounded byte snapshot per check: detect concurrent replacement/appends, report unstable/unavailable rather
than mixing reads. Canonicalize root and log path; reject symlink/root escape; log id cannot contain separators.
No repository-supplied executable, shell, plugin or arbitrary deserializer is evaluated. Regex follows existing
bounded runner rules. Raw event text is untrusted data, including prompt instructions and secrets.

Visible-text segments v1: `person_message`/`agent_message` use body.text; `tool_result` uses body.stdout and
body.stderr as **separate** segments; other kinds expose each string leaf separately with a JSON-pointer locator.
No quote may cross event or field boundaries. No recursive concatenation of leaf values into invented prose.
Report event digest, segment locator, actual match span and normalization. Ordinary quote normalization is inherited
from verbatim and must be disclosed; exact raw preservation/conformance never uses normalized quote matching.
Text matching does not authenticate speaker, authorship, a tool's success or user consent.

Log input and event disclosure need separate grants, explicit store/project/session scope and bounded output.
`event_text` is not exposed on anonymous remote MCP; a known LOG id or digest is not authorization. A caller's
agent-writable log stays AGENT_WRITABLE; other supplied logs stay CALLER_SUPPLIED. A hash-valid external checkpoint
adds an integrity observation and does not relabel all event contents COLLECTOR_OBSERVED.

### External integrity checkpoint

Self-consistency (`chain=INTACT`) and external anchoring are separate results. A checkpoint must bind schema,
canonical log identity plus epoch, seq, **full** head SHA-256, observer identity, observation time and a separately
trusted location/verification method. The agent cannot replace/delete/roll back it. A receipt in the same writable
store is not external. Prefix anchors (12+ hex) are convenient locators only, never cryptographic checkpoints.

To claim anchored inclusion for FROM..TO, recompute every event digest and prev link from the cited range through
the pinned checkpoint; a checkpoint before TO cannot attest to the suffix. Verify log/epoch/seq identity and detect
rollback against the last trusted checkpoint. Valid independent branches at the same seq are a fork/conflict,
not a choice made by the agent. Without access to that trusted checkpoint, state unanchored/unknown explicitly.
The range still proves only inclusion of those bytes; it cannot prove nothing was omitted before collection,
prove real-world time or prove that an event happened outside the log. `ev:` anchor-only prose remains unchecked.

### Additional acceptance fixtures (planned, not executed runtime tests)

Duplicate keys, bool seq, floats, nonfinite JSON, unknown v, oversized and partial lines; symlink escape;
concurrent append/replacement; missing store versus absent event in a complete log; cross-field quote;
self-consistent rewrite without checkpoint; checkpoint rollback/fork/wrong epoch; digest prefix collision;
checkpoint older than cited suffix; checkpoint stored beside agent-writable logs; cross-project event disclosure;
old reader refusing new vocabulary; quote with a false semantic lead-in. Retention/divergence results explicitly
state sample sizes, selection/window/seed, zero-count feature handling and no causal or significance conclusion.


Divergence numeric contract: JS distance is sqrt(JS divergence) with log base 2, common declared feature support,
0·log(0/q)=0; maximum 1 only for nonempty normalized distributions. Empty feature/log/window or too few events to
form the required halves yields unavailable with counts, never distance 0. Fixed seed, PRNG algorithm/version and
permutation/window selection are recorded. Event permutations here are descriptive only; a future inferential
study must predeclare task strata, order-preserving blocks/null and multiple-window comparison treatment.


Epoch v1 binding: epoch belongs to an external trusted store manifest mapping `(authorized store identity, LOG)`
to one immutable epoch and checkpoint sequence. Event-v1/ev: need no extra field: LOG ids are never reused within
that manifest, and the selected manifest supplies epoch. Rotation creates a new LOG id plus explicit trusted
link; a renamed directory or caller-supplied epoch cannot select a different checkpoint. Absence/inaccessibility
of the trusted manifest means unanchored, not implicit epoch 0. This manifest format/authority is an implementation
gate and not part of the agent-writable JSONL or current buddie.toml.
