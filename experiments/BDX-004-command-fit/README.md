# BDX-004: do commands an agent suggests run on the user's machine?

Status: **starter set built** (2026-11-01). Eight synthetic profiles, 24 tasks, 192 eligible units,
command extraction, a snapshot stand-in, a model-free judge and 55 human-written answer fixtures are present.
No model calls, provider code or experiment results. The experiment runs after BDX-003 is reported.

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

## Using the starter set

Python 3.11+; run from the repository root. No installation is needed. The workflow tests Python 3.12 on Ubuntu
and Windows. The runtime modules use only the standard library and this checkout's diagnostic registry/validator.

```sh
python -m unittest discover -s experiments/BDX-004-command-fit/tests -v
python experiments/BDX-004-command-fit/judge.py --profile win11-cmd-nogpu --task session-variable --answer answer.md
```

`--profile` and `--task` take IDs. The answer file is UTF-8 Markdown. The CLI prints JSON with the answer status,
each extracted command's status/reason/detail, `unknown_commands` and `all_commands_decided`. Python callers use
`judge_answer(markdown, profile_id_or_row, task_id_or_object)`. To replay a tool call, import `tool.py` from this
directory and use `environment_snapshot(arguments, profile_id_or_row)`. It returns a document, or raises
`ValueError` for a tool error. `TOOL` is the chat API function schema copied from `buddie/mcp.py`;
`{"list": true}` returns a catalog for the fixture, never for the host running the test.

All 24 tasks apply to all eight profiles: **192 units**. `tasks/units.json` records the shuffled pairs and seed 4.
Thirteen tasks have shell-dependent forms. Requirements are keyed by profile and specify the target shell, sudo
assumption, supplemental program assumptions, and anchored command rules (program, OS, elevation, Python modules,
CUDA compatibility, version bounds and installation effects). A task can intentionally be impossible on a profile;
asking about the machine or explaining a limitation is part of what later model answers may do.

`tests/answers.json` has fitting, broken and question-only examples for **16 distinct pairs**, plus seven tricky
answers. Expectations are human-labelled, including explicit alternatives when a parser is absent; the judge does
not generate its own expected labels. `profiles/build.py`, `tasks/build.py` and `tests/build_answers.py` reproduce
the checked-in data, without probing a machine or calling a model.

## Following the diagnostic code

Every profile is **hand-built**, not a recording or an assertion about a real machine. Every baseline category is
included, with unavailable observations labelled honestly; every profile passes `buddie.diagnostics.problems`.
That check establishes internal consistency, not authenticity. Observation names and method names follow the code.

The brief asks for facts the collector does not expose: sudo availability/permission, musl, ash/sh versions and
which Windows shell the person is using. Those are labelled scenario assumptions in `profiles/index.json` or task
requirements, never added as diagnostic observations. The collector's `default` login shell can say `ash`.
The Python launcher lists versions but does not probe their modules, so its module capabilities are also explicit
assumptions. The Ubuntu 22.04 target Python is 3.10 without venv; `buddie_runtime` is a separate Python 3.12, because
buddie requires Python 3.11+. CUDA, GPU and container context keep the collector's actual observation shape.

The stand-in preserves registry ordering, request rejection, category denial and metadata. It returns only named
catalog tools. No fixture grants directory roots, so path-scoped categories are unavailable without a path and
denied with one. Only Fedora grants `development.containers`; other profiles return that category denied.
No host policy, grants file, filesystem path, network or hardware is consulted by the stand-in.

## Judge limits

- **UNKNOWN never means FITS.** The required answer vocabulary has no UNKNOWN label: `OK` means only that no
  command is proven WONT_RUN. Always report `unknown_commands` and `all_commands_decided` alongside OK.
- Only an explicit complete task rule can produce FITS or INSTALLS. Unrecognized flags, programs with no
  observation, incomplete observations, dynamic code, pipelines, compound commands and redirects stay UNKNOWN.
  Missing-on-PATH reports concern the suggested bare program lookup, not whether software is installed elsewhere.
  Unlisted Python aliases stay UNKNOWN: the collector deduplicates interpreters by realpath. Quoted executable
  names and command wrappers survive extraction; environment-changing wrappers remain UNKNOWN rather than
  assuming that the original PATH and module lookup still apply. Node 20 rules require major version 20.
- Bash uses `bash --noprofile --norc -n`; sh uses dash or `busybox sh -n`. PowerShell uses a fixed
  `pwsh -NoProfile -NonInteractive -Command` parser script: answer bytes go only to `ParseInput` through stdin.
  Cmd uses a small explicit syntax rule set. Missing parsers produce UNKNOWN; zsh has no supported parser and
  therefore stays UNKNOWN even for otherwise fitting commands. Windows WSL launcher aliases are not started.
- Shell tags describe the intended execution shell. A block for another scenario shell is rejected with
  `wrong_shell_syntax`; no implicit shell switching is inferred. Explicit cross-shell idioms are rejected even
  without a parser. Windows PowerShell 5.1 does not acquire PowerShell 7's `&&` syntax from the host parser.
- Earlier recognized INSTALLS commands make their programs available to later commands in the same answer,
  assuming successful installation; failed/unknown installers do not. State resets between answers. Downloads,
  package repository availability, privileges outside the stated scenario, service state and file existence are
  not verified. Activation scripts stay UNKNOWN because their existence is not observed.
- CUDA wheel tags use the task's explicit rule `wheel CUDA <= observed driver CUDA`; this is an experiment rule,
  not a general CUDA compatibility oracle. The judge does not infer toolkit presence from the driver's CUDA ceiling.
- Extraction recognizes the documented shell fences and inline commands with a bounded program vocabulary or
  clear executable/flag shape. Arbitrary output can resemble commands; unusual prose, multi-line language constructs,
  heredocs, escaped quotes and programs outside that vocabulary may need audit. The blind audit in PROTOCOL.md
  is still necessary. These fixtures are test material, not measured model performance.
