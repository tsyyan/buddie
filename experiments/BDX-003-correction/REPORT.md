# BDX-003 report: does buddie's feedback leave fewer false quotations?

Closed 2026-11-02. Protocol, every change and its reason: [PROTOCOL.md](PROTOCOL.md); chunk-by-chunk record:
[main-log.txt](main-log.txt). Judged without a model (`common.in_text` against a SHA-256 snapshot of each source);
the owner's blind audit of 105 judged rows is below.

## In one paragraph

A paragraph from a published research report, with one quotation that is (ERROR) or is not (OK) on the page it
links to, goes to a model that prepares it for a reader. Without any check the false quotation reaches the reader
almost every time (gpt-oss-120b 99 %, Claude Opus 5 100 % through the API, 88 % in Claude Code). buddie's feedback
cuts that sharply: in Claude Code with the released plugin (2.0.7) to 24 %, a paired difference of −0.64 [−0.80,
−0.44], with no unit where buddie made it worse. It costs turns: about 8 instead of 1 in Claude Code. Asked to
check itself, a strong model fixes most quotations alone, and buddie adds a small further gain; a weak one gains
more. Asking a model to check also makes it drop correct quotations; buddie on top adds no such loss.

## Material

251 units from the blind labels of E008 and E011 (ERROR: the quotation is not on its page; OK: it is), refetched;
146 eligible (a stable copy of the page agrees with the label, and the paragraph links its source). Product run: the
first 25 ERROR and 15 OK of them in a seeded order.

## Arms (API, same model, system prompt and paragraph)

| | not asked to check | asked to check (`source_text` tool) |
|---|---|---|
| no buddie | **A** pass-through | **B** self-check |
| buddie's feedback (≤ 2 rounds) | **D** | **C** (**E**: C with 2.0.7's feedback, the page's sentence) |

## Results

### gpt-oss-120b, API, 146 units (complete)

| ERROR units | A | B | C | D | E |
|---|---|---|---|---|---|
| WRONG (false quote left) | 0.99 | 0.28 | **0.11** | 0.54 | 0.20 |
| CORRECT | 0 | 0.40 | 0.47 | 0.43 | 0.50 |
| requests / input tokens | 1.0 / 0.6k | 5.4 / 9.7k | 6.2 / 13.2k | 7.0 / 18.0k | 6.3 / 13.9k |

Paired, ERROR, share WRONG: **C−B −0.145 [−0.241, −0.048]** (n 83; only B bad 16, only C bad 4: the primary
endpoint); D−A −0.452 [−0.548, −0.355]; D−B +0.276 [0.149, 0.402]; E−C +0.08 [0.00, 0.16] (only C bad 3, only E
bad 10). OK units, CORRECT: A 0.94, B 0.92, C 0.94, D 0.96, E 0.89; C−B −0.02 [−0.10, 0.04].

### Claude Opus 5, API, 84 of 146 units (51 ERROR, 33 OK; closed early, see deviations)

| ERROR units | A | B | C | D | E |
|---|---|---|---|---|---|
| WRONG | 1.00 | 0.20 | **0.12** | 0.37 | 0.10 |
| CORRECT | 0 | 0.31 | 0.33 | 0.43 | 0.33 |

Paired, ERROR, WRONG: **D−A −0.63 [−0.77, −0.49]** (32 / 0); **C−B −0.08 [−0.16, −0.02]** (4 / 0); D−B +0.18
[0.04, 0.29]; E−C −0.02 [−0.06, 0.00]. OK units, not CORRECT: B−A **+0.24 [0.09, 0.39]**, C−A +0.24, D−A +0.27
[0.12, 0.42], C−B 0.00, D−B +0.03 [−0.18, 0.24]: asked to check, or given the tool, Opus dropped or paraphrased about
a quarter of the correct quotations; buddie's feedback added nothing to that.

### Claude Code with the plugin, Opus 5 (the product)

Claude Code headless, the paragraph with arm A's words (not asked to check), buddie 2.0.7 from its marketplace, the
hook reading the run's snapshots. Judged from everything the reader saw.

| | without buddie | **with buddie (release)** | skills removed (`hook`) | skills + MCP removed (`hookonly`) | hooks + discovery skill (`hookdisc`) |
|---|---|---|---|---|---|
| ERROR (n 25): WRONG | 0.88 | **0.24** | 0.20 | 0.20 | 0.08 |
| ERROR: CORRECT | 0 | **0.40** | 0.32 | 0.04 | 0 |
| ERROR: FLAGGED / REMOVED | 0 / 0.12 | 0.12 / 0.24 | 0.08 / 0.40 | 0.20 / 0.56 | 0.08 / 0.84 |
| ERROR: a false quote was shown at some point | 0.88 | 0.48 | 0.32 | 0.44 | 0.16 |
| OK (n 14-15): CORRECT | 0.67 | **0.93** | — | 0.36 | 0.33 |
| turns / input tokens (ERROR) | 1 / 11k | 7.8 / 105k | 7.8 / 106k | 7.8 / 74k | 8.6 / 76k |

Paired, ERROR, WRONG: **with−without −0.64 [−0.80, −0.44]** (16 / 0, the product endpoint); hookonly−without −0.68
[−0.84, −0.48]; hookdisc−without −0.80 [−0.92, −0.64]; hookonly−with −0.04 [−0.24, 0.16]; hookdisc−with −0.16
[−0.36, 0.00]. (`hook`, an exploratory variant that kept the MCP server, has no OK units.)

## The owner's audit (105 rows, blind to arm and condition)

| Sheet | Agree | Judge's WRONG | Judge's CORRECT | Judge's REMOVED | Judge's FLAGGED |
|---|---|---|---|---|---|
| API (70) | 63 (0.90) | 20 / 22 hold | 31 / 31 | 12 / 17 | — |
| Claude Code (35) | 31 (0.89) | 5 / 5 | 9 / 10 | 7 / 9 | 7 / 8 |

- **API: the judge never missed a false quotation** in the sample (every row the owner calls WRONG the judge
  called WRONG). Two WRONG were wrong (Opus B and C: only quotation marks and apostrophes differ from the page), so
  WRONG shares are if anything slightly high. Five REMOVED were, for the owner, CORRECT: the model replaced the target
  with a different verbatim excerpt of the source (the judge counts that REMOVED, `replaced_correct`).
- **Claude Code: the judge missed four false quotations** (owner WRONG): a target replaced by another unsupported
  quotation (with: 1, without: 1), bracketed pronoun changes read as allowed (hookonly: 1), a `buddie:` line placed
  before the quote rather than after it (hookonly: 1). Shares of WRONG in Claude Code are therefore somewhat low in
  every condition, with and without buddie alike; the with−without difference does not hinge on them.
- Cells where the judge was wrong in more than 1 row of 7 (PROTOCOL): API claude-opus-5 C (2) and gpt-oss D (2);
  product hookonly (2).

## What it shows

1. **The gate works in the product.** With buddie installed, a false quotation reached the reader in about a quarter
   of the paragraphs instead of nine in ten, and no paragraph came out worse.
2. **buddie's value is largest where nobody asks the model to check**, which is how agents are normally used (D−A:
   −0.45 gpt-oss, −0.63 Opus). When the model is asked to check, buddie still adds a significant but smaller gain
   (C−B: −0.145 gpt-oss, −0.08 Opus).
3. **Asking a model to check costs correct quotations** (Opus: a quarter of correct quotes dropped or paraphrased);
   buddie does not add to that. In Claude Code the released plugin kept more correct quotations than no plugin
   (0.93 against 0.67, n 14-15).
4. **The MCP tools carry the corrections.** Without `source_text` the model cannot copy the page's words, so it
   deletes: fewer false quotes left (hookdisc 0.08), but almost no corrections and two thirds of correct quotes lost.
5. **The cost is the weak point**: about 8 turns and 105k input tokens a paragraph with buddie against 1 turn and
   11k without, almost all of it the model checking before it answers (the hook returned 0.4 times a run). In 48 %
   of the runs a false quotation was on screen before its correction.
6. **2.0.7's feedback (the page's sentence) did not help**: worse for gpt-oss (E−C +0.08), no difference for Opus.

## Deviations and limits

- claude-opus-5 covers 84 of the planned 146 units (the key's balance; the gateway counted about four times the
  tokens the answers reported). The gpt-oss run and the product run are complete.
- Opus was reached through a third-party gateway (`api.tokenn.pro`), not Anthropic's API; prompt caching was not
  available there, which inflates the token counts relative to Claude Code with caching.
- Errors are seeded from real reports (E008, E011), not made by the model in the run; the task is to pass a paragraph
  on, not to write it. Whether buddie lowers the rate of false quotations a model makes on its own is not measured.
- One model per family at a time; one run per unit; the product run is 25 + 15 paragraphs.
- The judge's agreement with the owner is 0.89-0.90, with the error directions above.

## What follows for buddie

- Keep the release's configuration (skills, MCP tools, hooks): it is the one that both corrects and preserves.
- Work on cost and timing: fewer checks before the answer when the hook is installed, or one `verify_report` call
  instead of snap + source_text + verify (BDX-005).
- Make the hook's feedback say plainly "copy the page's words or remove the quotation marks"; measure it with a weak
  model.
- Claims for README and listings, with their n and interval: "In Claude Code with buddie, a false quotation reached
  the reader in 24 % of paragraphs instead of 88 % (Claude Opus 5, 25 paragraphs, −0.64 [−0.80, −0.44])."
