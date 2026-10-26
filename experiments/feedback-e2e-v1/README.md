# Feedback E2E v1

Does Verification Feedback v1 help an AI agent hand in a report it can rely on? This directory holds the protocol
([PROTOCOL.md](PROTOCOL.md)), the offline benchmark and its results ([REPORT.md](REPORT.md)).

| File | What |
|---|---|
| `world.py` | the fixed offline world: snapshot store, synthetic repo (fixed commit dates), work queue, GitHub answers |
| `scenarios.py` | the 8 scenarios, their hand-written ground truth, the scripted smoke candidates |
| `harness.py` | per-condition tool adapters over `buddie.mcp.handle`, isolation per run, the independent validator, run records |
| `analyze.py` | the metrics with exact k/n, paired cells, signal agreement |
| `bench.py` | the commands (below) |
| `metrics.schema.json`, `approval.schema.json` | the run record, the live-phase approval |
| `prompts/` | the live phase's task text and the two condition prompts |
| `results/smoke.jsonl`, `results/smoke-summary.json` | the smoke phase as committed |

## Reproduce (offline, no model, about a minute)

From the repository root, with this branch checked out (the feedback tools come from tsyyan/buddie#60, which is not
in a release):

```bash
python experiments/feedback-e2e-v1/bench.py smoke --out experiments/feedback-e2e-v1/results/smoke.jsonl
```

```bash
python experiments/feedback-e2e-v1/bench.py analyze experiments/feedback-e2e-v1/results/smoke.jsonl experiments/feedback-e2e-v1/results/smoke-summary.json
```

```bash
python experiments/feedback-e2e-v1/bench.py replay experiments/feedback-e2e-v1/results/smoke.jsonl
```

```bash
python -m pytest -q tests/test_feedback_experiment.py
```

`replay` re-runs the recorded plan (same seed) and compares every field but wall-clock time. It exits 1 on any
difference.

## Live pilot (prepared, not run)

`approval.pilot.json` is the completed manifest for the approved pilot. It specifies:
- `claude-sonnet-5-5`;
- 16 paired, randomized runs;
- at most 2 repairs per run;
- at most USD 10 in total and USD 0.60 per run;
- at most 8000 tokens per request and 8 requests per run.

Its `final_authorization` is empty.

```bash
python experiments/feedback-e2e-v1/live.py check --approval experiments/feedback-e2e-v1/approval.pilot.json
```

```bash
python experiments/feedback-e2e-v1/live.py execute --approval experiments/feedback-e2e-v1/approval.pilot.json --out experiments/feedback-e2e-v1/results/live-pilot
```

`execute` sends paid requests. It refuses until a person fills in `final_authorization` and `ANTHROPIC_API_KEY` is
set. It writes:
- `live.jsonl`: run records;
- `ledger.jsonl`: per-request usage and cost;
- `status.json`: complete or aborted, and why;
- `plan.json`.

`tests/test_feedback_live.py` checks the gate offline with a fake transport.

## Live phase with another harness

1. A person writes an approval (`approval.schema.json`).
2. `bench.py plan --approval approval.json --out live/` writes the randomized, paired plan and calls no model.
3. The approved operator runs each planned run with the provider's own harness. The agent's only tools are
   `bench.py serve --arm <condition> --world <fresh dir>`, and its prompt is `prompts/task.md` plus the condition's
   prompt.
4. `bench.py record --run run.json` turns each transcript summary into a run record. The label is made from the
   final report alone.
5. `bench.py analyze live.jsonl`.
