# BDX-004: do commands an agent suggests run on the user's machine?

Status: **pilot-4 remaining-form correction** (2026-11-02). Eight synthetic profiles, 24 tasks, 192 eligible units,
command extraction, a snapshot stand-in and the model-free judge are present. The recorded corpus has 76 earlier
answers, 12 realistic multi-system answers (31 profile checks), 16 pilot-2-shaped answers and ten whole
pilot-3 answers supplied as judge material, plus 18 hand-written pilot-4-shaped records:
132 distinct answers, 151 profile-answer cases.
Pilots 1–3 failed; the owner reports pilot 4 was at 25.7% UNKNOWN with no false objection.
This pass uses only existing recordings and offline tests, preserves
the simplified A/B/C design and run settings, and makes no model calls or new pilot run.

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
| D | Deferred; snapshot plus command feedback is considered only after B or C shows benefit |

The current protocol asks for commands for this person's machine, with asking or explicit audience labels
when the system is unknown. OK-answer share is the primary endpoint; A/B/C and the smaller stratified audit
follow PROTOCOL.md. The runner and pilot-4 settings were preserved in this correction.

Judged without a model (`judge.py`): every command of the answer is FITS, INSTALLS (it installs what is missing),
WONT_RUN (with a reason) or UNKNOWN; an answer is OK (all commands FITS/INSTALLS), UNDECIDED (UNKNOWN but no
WONT_RUN), BROKEN (a WONT_RUN command), ASKED (asks about the machine
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
each extracted command's status/reason/detail, `unknown_commands` and `all_commands_decided`. List/control
parents retain child verdicts in `commands`; `unknown_commands` counts UNKNOWN leaves and `unknown_constructs`
counts UNKNOWN parents. `all_commands_decided` checks the entire tree, including UNKNOWN children of a BROKEN
parent. Python callers use
`judge_answer(markdown, profile_id_or_row, task_id_or_object)`. To replay a tool call, import `tool.py` from this
directory and use `environment_snapshot(arguments, profile_id_or_row)`. It returns a document, or raises
`ValueError` for a tool error. `TOOL` is the chat API function schema copied from `buddie/mcp.py`;
`{"list": true}` returns a catalog for the fixture, never for the host running the test.

All 24 tasks apply to all eight profiles: **192 units**. `tasks/units.json` records the shuffled pairs and seed 4.
Thirteen tasks have shell-dependent forms. Requirements are keyed by profile and specify the target shell, sudo
assumption, supplemental program assumptions, and anchored command rules (program, OS, elevation, Python modules,
CUDA compatibility, version bounds and installation effects). A task can intentionally be impossible on a profile;
asking about the machine or explaining a limitation is part of what later model answers may do.

`tests/answers.json` has fitting, broken and question-only examples for **16 distinct pairs**, plus 28 tricky
answers. Expectations are human-labelled, including explicit alternatives when a parser is absent; the judge does
not generate its own expected labels. `profiles/build.py`, `tasks/build.py` and `tests/build_answers.py` reproduce
the checked-in data, without probing a machine or calling a model.

The review additions include correct bash-fenced commands for macOS/zsh and Alpine/sh, Alpine `[[ ]]` and array
failures, and a PowerShell block for a cmd-profile user. The cmd profile also has Windows PowerShell installed;
the negative case concerns the user's selected cmd execution family, not absence of powershell.exe.

## Earlier shell-family review measurement (2026-11-01)

`recorded_stats.py` counts every extracted command across every recorded answer, including UNKNOWN commands
inside BROKEN answers. Questions and prose contribute zero commands. It reports both the complete current corpus
and the unchanged original answer IDs, so additions cannot conceal the matched comparison.

| Corpus | Answers | All commands | UNKNOWN | Share |
|---|---:|---:|---:|---:|
| Before fixes, f59c325 | 55 | 39 | 3 | 7.69% |
| After fixes, original IDs | 55 | 39 | 1 | 2.56% |
| After fixes, expanded corpus | 60 | 44 | 1 | 2.27% |

Measured with bash, dash and pwsh available on the same local Windows setup. The original zsh checker always
returned UNKNOWN; the new checker accepts its POSIX subset through dash. The remaining UNKNOWN is the intentionally
unsupported `python --imaginary`. These are synthetic regression-corpus measurements, not model experiment results.
The actual before verdicts are saved in `tests/unknown_before.json`; the after report is `tests/unknown_after.json`.
Missing parsers change the share and produce explicit parser-availability fields, never filtered denominators.

```sh
python experiments/BDX-004-command-fit/recorded_stats.py
```

## Lists/control follow-up UNKNOWN share (2026-11-01)

The preceding table and unknown_before/after files preserve the earlier review's historical measurement.
For this follow-up, tests/lists_before.json captures actual verdicts at 5e4c330 with bash/dash/pwsh available;
tests/lists_after.json reports the same parser setup after adding sixteen hand-labelled list/control/state cases.

| Corpus | Answers | Extracted units | UNKNOWN parents/units | Share | Leaf verdicts | UNKNOWN leaves | Leaf share |
|---|---:|---:|---:|---:|---:|---:|---:|
| Before, 5e4c330 | 60 | 44 | 1 | 2.27% | 44 | 1 | 2.27% |
| After, original IDs | 60 | 44 | 1 | 2.27% | 44 | 1 | 2.27% |
| After, expanded corpus | 76 | 60 | 6 | 10.00% | 81 | 8 | 9.88% |

An extracted control structure or command list is one parent unit; its status is its worst child status.
The recursive leaf view also counts UNKNOWN child verdicts under BROKEN parents, and explicit UNKNOWN leaves
for unmodeled subconstructs. No UNKNOWN is hidden by a WONT_RUN sibling. The new guard examples deliberately
include dynamic patterns, unsupported literal forms, removed/failed venv setup and uncertain branches; the
expanded numerator therefore grows. The matched original-corpus share is unchanged. These are fixture checks,
not evidence about model performance. Parser-dependent expected outcomes remain explicit in answers.json.

```sh
python experiments/BDX-004-command-fit/recorded_stats.py --baseline experiments/BDX-004-command-fit/tests/lists_before.json
```

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

PROTOCOL v1 was added in 2bd7873. The subsequent 103b913 update implemented observed tagged-shell selection.
Core alternate-shell commands can
now be established by known presence and parsed syntax; default-shell task forms are not borrowed for another shell.

## Pilot-1 audience sections

`section_targets.json` maps label aliases and block tags to OS, distro, package manager, runtime and shell
constraints. `sections.py` scopes markdown headings by depth; unrecognized child headings inherit their parent,
while peer headings end that scope. Standalone bold/colon labels (including commands on the same line) are
supported. A code block's tag refines its enclosing audience; a POSIX tag does not mean Linux only.

Only applicable sections enter the command judge or establish install/venv state. Generic shared verification
steps apply after a matching targeted section. No declared section applies: BROKEN with answer reason wrong_os
and zero judged commands. No recognized audience labels or tags: judge the whole answer as before.
Responses include `targeting` (TARGETED for one audience, HEDGED for several), `commands_total` (all extracted
parent units offered), `commands_for_profile` (selected units), and section applicability metadata. Repeated
verification subheadings for one audience do not make it HEDGED. Counts exclude inline references filtered by
the invocation rule, and retain list/control parent units consistently with the earlier metrics.

The 12 hand-written examples in `tests/multi_section_answers.json` include brew/winget/apt/dnf alternatives,
headings, bold/colon labels, WSL/Alpine, nested verification steps, package-manager-only labels, shared checks,
and unavailable audiences. Node 20 verification accepts both `node --version` and `node -v` while keeping its
major-version constraint. `summarize.py` reports targeting and offered/selected command counts per arm; old run
rows without these fields are UNRECORDED, not silently relabelled TARGETED.

### Offline pilot-shape UNKNOWN comparison

The same 107 profile-answer cases were judged before (b036dd5, actual verdicts captured before changes) and after,
with bash, dash and pwsh available. This is a synthetic regression comparison, not a repeated model pilot.

| View | Before | After |
|---|---:|---:|
| Extracted commands offered | 237 | 231 |
| Parent units judged for the profile | 237 | 109 |
| UNKNOWN parent units / judged units | 25/237 (10.55%) | 6/109 (5.50%) |
| UNKNOWN leaf verdicts / judged leaves | 27/258 (10.47%) | 8/130 (6.15%) |

Six inline references are no longer commands; 122 offered instructions belong to other audiences and are excluded
from judgment. Answers without applicable instructions remain BROKEN/wrong_os, not missing denominator rows.
The new multi-system subset has 0/50 UNKNOWN judged commands across its 31 profile checks; guarded UNKNOWN cases
in the earlier corpus remain. Evidence is in tests/sections_before.json and tests/sections_after.json.

```sh
python experiments/BDX-004-command-fit/recorded_stats.py --baseline experiments/BDX-004-command-fit/tests/sections_before.json --multi-section experiments/BDX-004-command-fit/tests/multi_section_answers.json
```

## Judge limits (continued)

- **UNKNOWN never means FITS.** `OK` requires every command to be FITS or INSTALLS. `UNDECIDED` means at least
  one UNKNOWN and no WONT_RUN. BROKEN takes precedence when both occur. Keep `unknown_commands` and
  `all_commands_decided` for analysis; empty answers remain ASKED or NO_COMMANDS, never OK.
- FITS means program present (observed or base/scenario userland), target-shell syntax parses, and no task
  constraint is broken. Task patterns describe additional constraints/effects, not a command whitelist. Unknown
  flags of a present program FITS; this does not prove option semantics or task success. Unobserved programs,
  missing parsers, dynamic code, unsupported pipeline stage forms and redirects remain UNKNOWN.
  Missing-on-PATH reports concern the suggested bare program lookup, not whether software is installed elsewhere.
  Unlisted Python aliases stay UNKNOWN: the collector deduplicates interpreters by realpath. Quoted executable
  names and command wrappers survive extraction; environment-changing wrappers remain UNKNOWN rather than
  assuming that the original PATH and module lookup still apply. Node 20 rules require major version 20.
- `base_commands.py` contains sourced availability subsets for GNU coreutils/util-linux plus tar on Linux,
  BusyBox applets on Alpine, Apple's BSD userland, core PowerShell cmdlets and cmd builtins. Each list cites its
  primary source in a comment. These are explicit synthetic-scenario assumptions, not new diagnostic observations
  or guarantees about arbitrary installations. Observed missing programs override the assumptions. Known
  effect rules support common uses such as `ls -la`, `mkdir -p output`, `rm -f temp.txt`, tar archives,
  `Get-ChildItem`, `dir` and `set`; availability plus parsed syntax can approve unfamiliar options. Their semantics are not
  validated, and task-specific privilege constraints still apply.
- Bash uses `bash --noprofile --norc -n`; sh uses `dash -n`. Explicit checks also reject `[[ ]]`, arrays and
  `source` on sh: dash's syntax parser alone treats `[[` as an ordinary command name. These checks ignore
  quoted/escaped literal text. Non-native tokenizer failures stay UNKNOWN unless the target-shell parser
  establishes a syntax error. PowerShell uses a fixed
  `pwsh -NoProfile -NonInteractive -Command` parser script: answer bytes go only to `ParseInput` through stdin.
  Cmd uses a small explicit syntax rule set. Missing parsers produce UNKNOWN. For zsh, POSIX text accepted by
  dash is supported; syntax outside that subset is UNKNOWN. Windows WSL launcher aliases are not started.
- bash, sh, zsh, shell and console fences share the POSIX family. Tag mismatches produce `wrong_shell_syntax`
  only across POSIX, PowerShell and cmd families. The profile's shell determines the syntax check, not the tag.
  OS applicability and observed program availability are checked before a family mismatch. Cross-shell idioms are rejected even
  without a parser. Windows PowerShell 5.1 does not acquire PowerShell 7's `&&` syntax from the host parser.
- Earlier recognized INSTALLS commands make their programs available to later commands in the same section,
  assuming successful installation; failed/unknown installers do not. State resets between answers. Downloads,
  package repository availability, privileges outside the stated scenario, service state and file existence are
  not verified. An unfamiliar literal install form records pending intent: subsequent uses are at worst
  UNKNOWN for availability, even if the snapshot previously said missing. This does not override OS, version,
  syntax or admin failures. Only bounded successful effect rules prove presence; dry-runs/download-only forms
  never prove it. Pending intent survives valid uncertain branches/AND predecessors, but not rejected syntax.
  State resets between declared audience sections; neutral child verification headings retain it.
  Literal `python -m venv DIR` (including observed python3/py forms) also records DIR after a FITS
  result. POSIX `source DIR/bin/activate` or `. DIR/bin/activate` then FITS when the profile shell supports it;
  source is rejected for sh. The POSIX activate-venv task explicitly declares .venv as existing; other unknown
  paths stay UNKNOWN. activate.fish/activate.csh require the matching shell observation. Unsupported paths
  cannot bypass the existence check. The whole pilot-3 Windows example also requires literal task-declared
  .venv\Scripts\activate.bat / Activate.ps1 paths; these are extracted and validated in their own shell.
  Interpreter options before -m preserve module constraints; bounded venv options preserve creation proofs.
  Modeled rm/mv/cp operations affecting the venv or its activation script invalidate the proof. Unknown
  commands can change cwd/files and also invalidate it; potential deletion in a conditional path is retained
  conservatively even though new conditional setup is not exported.
- POSIX lists split on unquoted `&&`, `||`, `;` and newlines; PowerShell statements split on unquoted `;`
  and newlines. Nested expansions and script blocks remain opaque. Each list keeps child verdicts under
  `commands` and takes the worst: WONT_RUN > UNKNOWN > INSTALLS > FITS. Complete-list syntax is also checked
  by the profile parser. No answer text is executed. Effects flow through successful sequential/AND steps;
  a failed or unknown AND predecessor cannot establish setup. OR alternatives use separate state, and
  proven effects are not exported from an OR-containing list (only pending install intent). POSIX/PowerShell pipelines split on unquoted top-level |, judge each stage, and fold the worst verdict.
  Stages use independent setup state; only pending installation intent can flow out. No pipeline is executed
  and no dataflow/stream contents or external script success is inferred.
- POSIX if/elif/else/fi, for/while/until/do/done and case/esac structures are extracted intact, including
  nested and incomplete structures. The complete text is syntax-checked by the profile shell (dash for sh),
  then conditions and body commands are judged recursively. The worst potential branch wins; this is a
  static audit of suggested commands, not a prediction of which branch executes. Each branch has its own
  copy of prior answer state, so setup in one branch cannot prove activation in another or after a loop/if.
  Dynamic headers and unsupported grammar remain UNKNOWN, never a default FITS or silently NO_COMMANDS.
  Command substitution in case patterns is dynamic too and cannot be approved as inert pattern data.
  Quote state and unfinished list operators are preserved across physical lines; quoted command-looking
  text is not extracted as an instruction.
- CUDA wheel tags use the task's explicit rule `wheel CUDA <= observed driver CUDA`; this is an experiment rule,
  not a general CUDA compatibility oracle. The judge does not infer toolkit presence from the driver's CUDA ceiling.
- Extraction recognizes the documented shell fences and inline commands with a bounded program vocabulary or
  clear executable/flag shape. Arbitrary output can resemble commands; unusual prose, multi-line language constructs,
  heredocs, unsupported control grammar, complex expansions and programs outside that vocabulary may need audit. The blind audit in PROTOCOL.md
  is still necessary. These fixtures are test material, not measured model performance.

Inline code is an instruction only when its sentence directly says to run/type/execute it, or it contains
a program and at least one argument. Plain tool names, versions, settings and directory/file references are
not commands. An explicit "do not run" instruction is not an instruction to execute that code.
Explicit instructions retain unfamiliar executables (including `./configure`) for judgment rather than
silently discarding them. Neutral child headings preserve a bold/colon audience and may themselves contain
inline commands. Mixed alternatives such as Windows / Ubuntu keep their OS/distro/manager constraints
separate. A matching explanatory section with no commands counts as applicable (NO_COMMANDS or ASKED);
it does not become a wrong_os failure just because another platform has commands.

## Running

| Path | What |
|---|---|
| `run.py` | the arms A-D against a model (`client.py`: the BDX-003 chat client, copied), rows to `data/*.jsonl` |
| `summarize.py` | rows to numbers (GitHub notices) and a sheet of every judged command for the owner |
| `run.env` | what a push to `experiment/bdx-004-run` runs (job `run` in `.github/workflows/bdx004.yml`) |

## Pilot-2 rule correction and offline measurement (2026-11-02)

Program/OS checks precede admin objections. On macOS sudo privilege stays UNKNOWN because the snapshot cannot
observe admin group membership; an explicit missing sudo still yields program_missing. sudo on Alpine is
program_missing even when the process is root, and apt on macOS is wrong_os. The profile documents stay unchanged.

`tests/pilot2_answers.json` records 16 pilot-shaped answers: curl -L -o, chmod +x, nvcc -V, unknown flags,
sudo ordering, unmatched/uncertain installs followed by verification, pip install, existing/created venvs,
and absent fish/csh shells. Separate regression tests cover extra CUDA/interpreter flags, dry-run effects,
conditional/OR intent, rejected list syntax and unsupported activation paths. No model answers were fetched
or regenerated and no pilot was rerun.

With bash/dash/pwsh, the same 123 recorded profile/answer cases at 94fa8a1 versus this implementation:

| Metric | Before | After |
|---|---:|---:|
| UNKNOWN parent commands | 16/128 (12.50%) | 9/128 (7.03%) |
| UNKNOWN recursive leaves | 18/149 (12.08%) | 10/149 (6.71%) |

Both sides include every recorded answer, including BROKEN answers and UNKNOWN children; offered commands
stay 250, selected parents 128. These synthetic tests do not establish that the real pilot now passes.
Snapshots: tests/pilot2_before.json and tests/pilot2_after.json. Earlier measurement tables are historical.

```sh
python experiments/BDX-004-command-fit/recorded_stats.py --baseline experiments/BDX-004-command-fit/tests/pilot2_before.json --multi-section experiments/BDX-004-command-fit/tests/multi_section_answers.json --extra-answers experiments/BDX-004-command-fit/tests/pilot2_answers.json
```

## Last iteration before pilot 4 (2026-11-02)

The ten supplied whole answers in tests/pilot/pilot3_answers.jsonl are each recorded in
`tests/pilot3_answers.json`, with a literal human-labelled outcome, rationale, source line and UTF-8 text hash.
Tests verify exact source text, including its truncation; no missing continuation is invented. They are judge
regression material, not arm results. The owner’s simplified protocol (A/B/C, D deferred, OK primary) and
pilot-4 settings are preserved. This implementation neither launches pilot 4 nor registers the experiment.

Audience fixes include multi-system unions (Unix-like Linux/macOS/WSL), table command columns and OS/shell
rows, a command’s immediate parenthesized audience, and Git Bash/MSYS2 only with an explicit shell observation.
WSL guest instructions can refine a Windows-host heading. Broad Linux headings are not narrowed by distro
examples. Standalone audience comments can constrain commands in a fence, while quoted strings and whole
control structures remain intact. Interpretation-table headers and explicitly introduced sample-output
fences are not commands. Tables retain pipeline bars inside inline-code cells.

`package_manager_distros.json` defines native distro-manager families; foreign apt/dnf/apk/pacman/zypper
commands are wrong_os before sudo/admin objections. An explicitly observed additional manager can still
run. brew on Linux and winget/choco on Windows require observations; otherwise program_missing.
The base userland adds sourced grep/awk/sed/sort/head/tail/wc/xargs/cut/ps and core PowerShell pipeline cmdlets.
NVM install attempts and Node’s bundled npm establish only pending availability, never successful setup/version.

| Whole material | Expected outcome |
|---|---|
| 01 Windows venv activation | OK |
| 02 Alpine GPU alternatives | BROKEN (missing sudo/tools) |
| 03 Alpine ffmpeg | BROKEN (no Alpine section) |
| 04 WSL GPU probes | UNDECIDED (unobserved optional tools) |
| 05 WSL service probes | UNDECIDED (unobserved service/init tools) |
| 06 Windows Node/NVM | UNDECIDED (unproved setup/version) |
| 07 macOS Git | UNDECIDED (Xcode/placeholder remote arguments) |
| 08 macOS port/process | UNDECIDED (sudo/PID placeholders) |
| 09 Ubuntu without sudo, Git | BROKEN (sudo absent) |
| 10 Fedora Node/NVM | UNDECIDED (unproved setup/version) |

Paired measurement of **all 133 recorded cases**, at 73bdc3a and this implementation, with bash/dash/pwsh:

| Metric | Before | After |
|---|---:|---:|
| Offered parent commands | 415 | 455 |
| Selected/judged parents | 200 | 212 |
| UNKNOWN parents | 34/200 (17.00%) | 53/212 (25.00%) |
| UNKNOWN recursive leaves | 35/221 (15.84%) | 54/248 (21.77%) |

The UNKNOWN share **increases**. The ten whole answers introduce 30 newly extracted selected instructions,
20 UNKNOWN, and remove 18 earlier extractions; three matched false WONT_RUN commands become UNKNOWN and
one UNKNOWN becomes FITS. The earlier 123-case corpus is otherwise unchanged. On the deliberately problematic
ten-answer subset alone, UNKNOWN parents are 25/72 (34.72%) to 44/84 (52.38%); outcomes change from
7 BROKEN / 3 UNDECIDED to 1 OK / 3 BROKEN / 6 UNDECIDED. The missing observations are retained as uncertainty
rather than invented presence. These counts do not demonstrate a successful pilot-4 judge check.

Before/after snapshots are tests/pilot3_before.json and tests/pilot3_after.json. Reproduce:

```sh
python experiments/BDX-004-command-fit/recorded_stats.py --baseline experiments/BDX-004-command-fit/tests/pilot3_before.json --multi-section experiments/BDX-004-command-fit/tests/multi_section_answers.json --extra-answers experiments/BDX-004-command-fit/tests/pilot2_answers.json --extra-answers experiments/BDX-004-command-fit/tests/pilot3_answers.json
```

## Pilot-4 remaining forms (2026-11-02)

The owner reports run 41357808790 had 25.7% UNKNOWN (25% limit) and no false objection. Its raw answers were
not supplied on this branch. `tests/pilot4_answers.json` therefore contains **18 hand-written cases based on
the supplied forms**, with literal expected verdicts; they are not labelled as original model responses.

- Absolute executable names (including quoted Windows paths and PowerShell’s spaced or attached `&` call
  operator) resolve to their basename for program/version/OS/module/admin checks. Original text is preserved
  for display and shell parsing. An absolute path cannot bypass those constraints. Unquoted shell operators
  are never erased as path prefixes. Placeholder paths such as /full/path/to remain UNKNOWN.
- Direct POSIX file execution FITS only with task/answer evidence for the exact literal file. The permissions
  task declares script.sh as provided. Bounded successful touch/chmod/cp commands and a single literal curl
  URL/output pair can establish evidence; help, missing URLs, ambiguous outputs and unmodeled forms cannot.
  File evidence shares section/branch/reset/mutation rules with venv evidence. Absolute rm/cd/mv identities
  invalidate proofs too. Conditional, failed or unknown setup cannot establish a file outside its branch.
  This follows the requested existence rule; contents, interpreter/shebang and executable mode are not probed.
- `base_commands.py` cites primary package/manpage/config sources for Ubuntu/Debian service, ss, nc, ps;
  Fedora service, ss, nc/ncat, ps; Alpine BusyBox nc/ps/netstat and related applets; macOS BSD nc/netstat.
  These are explicit package-backed scenario assumptions, not a claim that every minimal image installs
  every package. Unlisted tools remain UNKNOWN and explicit missing observations override the base sets.
  Standard service mutators, including force-reload, retain admin constraints.
- Conventional PowerShell Verb-Noun cmdlets on POSIX-only profiles give wrong_shell_syntax. Normal observed
  POSIX programs and hyphenated tools such as nvidia-smi/apt-get are not rejected merely for their names.
  Existing audience selection and observed alternative-shell behavior are preserved.

With identical bash/dash/pwsh availability, all **151 recorded profile/answer cases**, before 45f4317 and after:

| Metric | Before | After |
|---|---:|---:|
| Offered extracted parents | 476 | 476 |
| Selected/judged parents | 233 | 233 |
| UNKNOWN parents | 71/233 (30.47%) | 53/233 (22.75%) |
| UNKNOWN recursive leaves | 72/269 (26.77%) | 54/269 (20.07%) |

BROKEN answers and UNKNOWN children remain included; no denominator is filtered for parser availability.
Questions/prose contribute zero commands. The 18 new cases expect 10 OK, 4 BROKEN and 4 UNDECIDED answers.
This is a paired offline regression comparison, not a rerun of pilot 4 or proof that a fresh pilot passes.
Snapshots: tests/pilot4_before.json and tests/pilot4_after.json. Historical tables above remain historical.

```sh
python experiments/BDX-004-command-fit/recorded_stats.py --baseline experiments/BDX-004-command-fit/tests/pilot4_before.json --multi-section experiments/BDX-004-command-fit/tests/multi_section_answers.json --extra-answers experiments/BDX-004-command-fit/tests/pilot2_answers.json --extra-answers experiments/BDX-004-command-fit/tests/pilot3_answers.json --extra-answers experiments/BDX-004-command-fit/tests/pilot4_answers.json
```
