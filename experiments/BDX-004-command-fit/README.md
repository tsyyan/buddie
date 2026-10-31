# BDX-004: do commands an agent suggests run on the user's machine?

Status: **scaffold** (2026-11-01). The starter set (machine profiles, tasks, a model-free judge, recorded answers and
their tests) is being built; no model has been asked anything. The experiment runs after BDX-003 is reported.

## Question

An agent that tells a person "run `py -3.12 -m venv .venv`" or "install CUDA 12.4" guesses the machine unless it
looks. buddie's `environment_snapshot` (docs/environment.md, "Diagnostics") observes the categories a task needs
(OS, shell, GPU and driver, Python, package managers ...), only those the person granted. Today nothing in the
plugin leads a model to call it, and nothing checks the commands an answer gives against it.

1. How often does an answer give a command that cannot run on the person's machine (a program that is not there, a
   shell's syntax for another shell, a version the machine cannot take)?
2. Does access to the snapshot (as a tool, or given up front) lower that share, and at what cost in tokens and
   turns?
3. Would a model-free check of the answer's commands against the snapshot (a candidate hook gate, `commands`)
   catch what is left, and how often would it object to a command that is fine?

## Design (draft, see PROTOCOL.md)

Units are (machine profile, task) pairs. A profile is an `environment-diagnostics-v1` document, as the tool returns
it, for a machine that does not exist (hand-built, schema-checked with `buddie.diagnostics.problems`) or one that
was recorded. A task is what a person asks with no word about their machine ("set up PyTorch with my GPU").

| Arm | The model gets |
|---|---|
| A | the task only |
| B | the task and the tool `environment_snapshot`, answered from the profile (granted categories only) |
| C | the task and the profile's snapshot in the first message |
| D | B, then the judge's objections to its commands as feedback, at most 2 rounds (the candidate gate) |

Judged without a model (`judge.py`): every command of the answer is FITS, INSTALLS (it installs what is missing),
WONT_RUN (with a reason) or UNKNOWN; an answer is OK, BROKEN (a WONT_RUN command), ASKED (asks about the machine
and gives no command) or NO_COMMANDS.

## Layout

| Path | What |
|---|---|
| `profiles/*.json` | machine profiles (environment-diagnostics-v1) and their provenance |
| `tasks/tasks.json` | tasks, the categories each needs, and per-profile requirements |
| `tool.py` | the `environment_snapshot` stand-in, answered from a profile |
| `commands.py` | commands extracted from an answer |
| `judge.py` | the model-free judge |
| `tests/` | recorded good and bad answers with the judge's expected outcomes |
| `CODEX_TASK.md` | the brief the starter set is built from |

Run the tests: `python -m unittest discover -s experiments/BDX-004-command-fit/tests` (stdlib only, no network;
`pwsh` used when present for PowerShell syntax, otherwise those checks are UNKNOWN).
