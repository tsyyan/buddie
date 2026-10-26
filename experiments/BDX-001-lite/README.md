# BDX-001 Lite — environment grounding in buddie 2.x

Does structured environment context from buddie (`environment_snapshot`) make an agent's system-specific
recommendations more applicable than no diagnostics (A) or a restricted diagnostic shell (B)? This directory holds
the experiment: scenarios, genuine recordings, a harness, a deterministic evaluator, results and the report
([REPORT.ru.md](REPORT.ru.md), in Russian).

It measures the usefulness of diagnostic **context**. It does not measure network reliability, remote MCP
performance or transport security: every tool answer is replayed from a recording.

Nothing in `buddie/`, `tests/`, the MCP contract, permissions or receipt formats is changed. The harness uses buddie
as an observer through what its adapters already produce (the CLI's diagnostics documents; `mcp.TOOLS`,
`diagnostics.validate / lines / problems`, read-only), and registers nothing in the verification-module registry
(PR #54's boundary: observers are not verification modules).

## Layout

| Path | What |
|---|---|
| `scenarios/scenarios.json` | 12 scenarios (agent-facing text, devices) and the smoke subset; `bindings` are read by the tool router only |
| `evaluation/ground_truth.json` | per scenario: ground-truth environment, relevant facts, expected behaviour, acceptable clarifications, failure modes, deterministic rules, assumption probes, coverage of each channel. Frozen before any model run |
| `evaluation/evaluate.py` | the evaluator: condition-blind rule pass, then labels |
| `evaluation/context_cost.py` | model-free measurement of how many bytes each channel needs for the relevant facts |
| `fixtures/collect/` | `collect.py` (records one environment), `shell_menu.json` (condition B's commands, frozen before the scenarios), `workflow.yml` (the GitHub Actions job that recorded the Linux environments) |
| `fixtures/raw/<env>/` | per environment: `buddie_full.json` (real `buddie snapshot`, every category and catalog tool), `buddie_catalog.json`, `shell.json` (every menu command's stdout, stderr, exit), `meta.json` |
| `harness/bdx/` | scenarios, prompts, tool specs and router, buddie replay, stdio MCP server, backends, CLI |
| `harness/tests/` | harness validation tests |
| `results/` | `static/context_cost.json`; `smoke/` plan and, once run, run records and evaluations |

## Environments (all genuine recordings, 2026-10-26)

| env | where | used by |
|---|---|---|
| `win-laptop` | the experimenter's Windows 11 laptop (GTX 1650, PowerShell 5.1, no WSL distribution) | OS-1, RT-2, RT-3, HW-1, CTX-1, CTX-2, CTX-3 |
| `linux-x64` | GitHub-hosted `ubuntu-24.04` runner, native | OS-2, OS-3, CTX-1 |
| `linux-arm64` | GitHub-hosted `ubuntu-24.04-arm` runner, native | HW-3 |
| `linux-container-2g` | `python:3.12-slim` container, `--memory=2g` | HW-2 |
| `debian-nopython` | `debian:bookworm-slim` + `apt-get install python3` only | RT-1 |

User and host names are replaced with placeholders (`user`, a host alias); nothing else is edited.

## Conditions

Same model, task text, base instructions and limits everywhere; one paragraph differs.

- **A** — no tools.
- **B** — `run_diagnostics(device, commands[])`: up to 8 commands per call from a fixed 35-command menu (28 parity
  commands reading what buddie's collectors read, 7 conventional extras buddie deliberately does not collect: host
  name, clock, PATH, disk, WSL distributions). Each command was run on every environment in its default shell.
- **C** — `environment_snapshot(device, categories[], tools[], task, path, list)`: buddie's own tool description and
  schema plus a `device` argument; the agent chooses categories. Answers are cut from the recorded document, checked
  with `diagnostics.problems()`, and rendered as buddie's MCP adapter renders them.

B and C: at most 4 tool calls per run, the same envelope (device, collection time).

## Reproduce

```bash
cd experiments/BDX-001-lite/harness
python -m pytest -q tests                                   # harness validation
python -m bdx plan --set smoke --seed 20261026 --out ../results/smoke
python -m bdx preview ../results/smoke                      # exact prompts, no model call
python -m bdx run ../results/smoke --model MODEL --confirm-cost   # costs model usage
python -m bdx evaluate ../results/smoke
python -m bdx packet ../results/smoke                       # blinded packet for manual review
```

Re-recording an environment: `python fixtures/collect/collect.py --env-id ID --host-alias ALIAS --out DIR` on that
machine (it uses a temporary grants file; the person's own grants file is never read or changed).

## Labels

`APPLICABLE`, `INAPPLICABLE`, `JUSTIFIED_CLARIFICATION` (allowed in that condition, not counted as success),
`UNJUSTIFIED_CLARIFICATION`, `NO_RESULT` (manual review), `HARNESS_FAILURE` (excluded from rates). ARR = APPLICABLE / n.
