# BDX-004 report: does the environment snapshot make commands fit the machine?

Status, 2026-11-03: **arms A, B, C and D complete on `openai/gpt-oss-120b`; the owner's blind audit of the judge is
still to come**, so every number below rests on the model-free judge as validated by the pilots (PROTOCOL.md) and is
provisional until that audit.

Runs: [41366094586](https://github.com/tsyyan/buddie/actions/runs/41366094586) and
[41397458465](https://github.com/tsyyan/buddie/actions/runs/41397458465) (the experiment),
[41428935062](https://github.com/tsyyan/buddie/actions/runs/41428935062) (the one rerun of units that failed,
"Changes after data"); arm D: [41491361431](https://github.com/tsyyan/buddie/actions/runs/41491361431) (attempt 2) and
its rerun [41544960710](https://github.com/tsyyan/buddie/actions/runs/41544960710). The answers, verdicts and audit
sheet are each run's artifact.

**The failed rows were the harness's, not the provider's** (found 2026-11-03, "Changes after data"): every one of
them is `TypeError: Object of type bytes is not JSON serializable`. When a provider answered 429 with a short
`Retry-After`, `client.py` stored the error's body in the variable holding the request and then sent that again, so
the retry crashed instead of waiting. No model answer was lost: the request was never re-sent. Which units failed
depends on request timing and the provider's per-minute token pace, not on what the model would have answered;
arms with more tokens per request (C's snapshot in the prompt, D's feedback rounds) hit it more often. Fixed, with a
test (`tests/test_client.py`).

## In one paragraph

Given buddie's `environment_snapshot` tool (arm B), gpt-oss gives commands that will not run on the person's machine
in **25 %** of answers instead of **38 %** without it (A): about a third fewer, an interval that excludes zero. It does
not, however, give more answers whose every command is shown to fit (OK), the registered primary endpoint: +3.7 points,
interval across zero. Most of the gap is not the model's: a third of all commands stay UNKNOWN because the machine
profile does not say what they need (a *data gap*). Given the snapshot in the prompt instead (C), the model gives more
OK answers (+12.6 points) but also many more commands (9.0 against 3.6 per answer), and no fewer broken ones.
Returning the judge's objections to the model (D) cuts broken answers by another 9 points against B (15 %), but not
by fixing commands: OK stays where it is, and the model asks about the machine or drops the commands instead.

## Primary and secondary endpoints

Paired by unit, 95 % paired bootstrap (4000 resamples, seed 7). After the rerun: A 190, B 189, C 183 of 192 units
answered (14 rows still failed at the provider).

| Comparison | Difference | 95 % interval | Pairs | Before the rerun |
|---|---:|---|---:|---|
| **OK share, B − A (primary)** | +0.037 | [−0.032, +0.107] | 187 | +0.053 [−0.012, +0.124], n 169 |
| BROKEN share, B − A | **−0.123** | [−0.209, −0.037] | 187 | −0.118 [−0.201, −0.030] |
| OK share, C − A | **+0.126** | [+0.066, +0.187] | 182 | +0.103 [+0.039, +0.168], n 155 |
| BROKEN share, C − A | 0.000 | [−0.088, +0.088] | 182 | −0.013 [−0.110, +0.077] |
| **BROKEN share, D − B (gate condition)** | **−0.093** | [−0.165, −0.022] | 182 | −0.089 [−0.161, −0.018], n 168 |
| OK share, D − B | 0.000 | [−0.066, +0.066] | 182 | −0.018 [−0.089, +0.054] |
| BROKEN share, D − A | **−0.220** | [−0.302, −0.137] | 182 | −0.228 [−0.311, −0.144] |
| OK share, D − A | +0.038 | [−0.033, +0.104] | 182 | |
| OK share, C − B | **+0.083** | [+0.011, +0.156] | 180 | |
| BROKEN share, C − B | **+0.139** | [+0.067, +0.211] | 180 | |

The reruns moved no conclusion.

## Per arm

| | A: task only | B: with the tool | C: snapshot in the prompt | D: B + the judge's objections |
|---|---:|---:|---:|---:|
| Answers | 190 | 189 | 183 | 184 |
| OK | 0.14 | 0.17 | 0.26 | 0.18 |
| BROKEN | 0.38 | 0.25 | 0.39 | 0.15 |
| ASKED (asks about the machine, no command) | 0.31 | 0.33 | 0.00 | 0.39 |
| UNDECIDED | 0.12 | 0.13 | 0.34 | 0.14 |
| NO_COMMANDS | 0.06 | 0.11 | 0.01 | 0.14 |
| Answers for several systems at once (HEDGED) | 57 % | 17 % | 45 % | 27 % |
| Commands offered per answer / for this machine | 6.8 / 3.5 | 3.6 / 3.3 | 9.0 / 8.4 | 4.0 / 3.4 |
| UNKNOWN commands: judge gap / data gap | 6 % / 28 % | 6 % / 27 % | 8 % / 24 % | 5 % / 27 % |
| Requests per unit (tool calls) | 1.00 | 2.24 (1.24) | 1.00 | 2.36 (1.09) |
| Characters sent per unit | 339 | 16 608 | 6 130 | 23 184 |

All cells are as the run's summary printed them.

What the rows say:

- **B aims at the machine.** With the tool, 17 % of answers hedge across systems against 57 % without; the model
  calls the tool 1.24 times per answer and offers half as many commands. The commands it no longer offers are mostly
  the ones for other systems, so a person reads less and runs fewer wrong ones.
- **C knows the machine and still breaks things.** Every answer gets the snapshot, none asks, but it offers two and a
  half times as many commands, and each extra command is another chance to miss (`program_missing` 248 in C against
  104 in B). More of its answers are OK, and as many are BROKEN.
- **D trades broken answers for questions.** Shown which commands will not run, the model rarely repairs them:
  OK is 0.18 against B's 0.17, while ASKED rises from 0.33 to 0.39 and NO_COMMANDS from 0.11 to 0.14. BROKEN falls
  from 0.25 to 0.15. An answer that asks is better than one that breaks the machine, but it is not a fix, and D
  sends 40 % more text per unit than B.
- **Why OK barely moves in B.** An answer is OK only when every command is shown to fit. A third of commands are
  UNKNOWN in every arm, and four fifths of those are a data gap: the profile does not observe what the command
  needs (a conda environment, a file, a service). No arm can close that gap; a richer snapshot could.

## What this means for the product

- **Claim that holds:** with buddie's environment tool, an agent gives about a third fewer commands that will not run
  on your machine (gpt-oss, synthetic machines, this judge). Not claimed: that commands fit, or that the share of
  fully verified answers rises.
- **Ask, do not inject.** B gets its effect with half the commands and a third of the hedging; C's prompt-sized
  snapshot buys OK at the price of long answers and no fewer breaks. The `environment` skill already has the agent
  ask for the categories it needs, which is B.
- **A command gate is half-qualified.** The protocol proposes a hook gate when D − B BROKEN is below zero (met:
  −9.3 points, interval below zero) and the blind audit shows false objections under 10 % (not yet run). Even then
  the gate's effect is fewer broken answers by asking or omitting, not more working ones; a gate that says so to the
  person is honest, one sold as "fixes your commands" would not be.

## Limits

- One model (gpt-oss-120b on free providers). `claude-opus-5` was not run: no budget left after BDX-003.
- Eight hand-built profiles, 24 tasks: no real machine. The judge parses and reasons about commands; nothing is run.
- The judge is model-free and was validated on pilot answers, not yet on these; the blind audit (PROTOCOL.md, "Audit")
  is the owner's next step.
- 22 of 768 units have no answer after one rerun (2 A, 3 B, 9 C, 8 D), all through the harness's rate-limit crash
  above; whether to run them once more with the fixed client is the owner's decision ("Changes after data").
- `pwsh` parses PowerShell with an 8 s timeout; a cold start past it makes a command UNKNOWN, a possible small
  source of judge gap on PowerShell answers (it stopped arm D's first attempt in the run's own tests).

## Next

1. The owner's blind audit (the audit sheet in run 41428935062's artifact): false objections per reason.
2. The 22 units without an answer, once more with the fixed client: a decision for the owner.
3. The data gap: which observations the UNKNOWN commands needed, as candidates for diagnostics categories.
