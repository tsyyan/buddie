# BDX-004 protocol (DRAFT)

Not registered. It is fixed, with its date, before the first model answer is recorded; every change after that is
listed under "Changes after data" with its reason, as in BDX-003.

## Question
See README.md. Primary: share of BROKEN answers (at least one WONT_RUN command), B − A, paired by unit.
Secondary: C − A; D − B; tool use in B (share of units where the model called the tool, categories asked); objections
of the judge to commands that a person on that machine could run (false objections, from the audit); tokens and
requests per unit.

## Material
- Profiles: at least 8 machines across Windows (PowerShell, cmd), macOS (Apple Silicon), Linux (Ubuntu, Fedora,
  Alpine container, no root), WSL; with and without an NVIDIA GPU. Each is an environment-diagnostics-v1 document that
  `buddie.diagnostics.problems` accepts, and says whether it is hand-built or recorded.
- Tasks: at least 24, each phrased without a word about the machine, each with the categories it needs and what a
  command must satisfy on each profile.
- Units: every (profile, task) pair whose task applies to the profile; the list and its seed are recorded.

## Arms
A, B, C, D as in README.md; same system prompt, task and model; order randomized per unit.

## Outcomes (judge.py, no model)
Per command: FITS, INSTALLS, WONT_RUN (program_missing, wrong_shell_syntax, wrong_os, version_mismatch,
needs_admin), UNKNOWN. Per answer: OK (one or more commands, every one FITS/INSTALLS), BROKEN (any WONT_RUN),
UNDECIDED (at least one UNKNOWN and no WONT_RUN), ASKED (machine question without commands), NO_COMMANDS
(other text without commands). BROKEN takes precedence over UNDECIDED. UNKNOWN is never counted as FITS;
UNDECIDED answers must not be counted as OK or silently dropped from the outcome denominator.

Shell hints are families: bash/sh/zsh/shell/console are POSIX, separate from PowerShell and cmd. A tag mismatch
is a shell failure only across families. OS/program failures take precedence over the tag. Parse the command
using the profile's shell: sh uses dash -n plus explicit bashism checks; zsh accepts the POSIX-parseable subset
and is UNKNOWN outside it. No answer text is executed.
Quoted literal text is not evidence of a bashism. A failure in the judge's non-native tokenizer is UNKNOWN
unless a target-shell syntax check establishes invalid syntax. Missing Python modules are availability
failures and also precede a shell-tag mismatch.

The judge may also use the cited base-command subsets and bounded forms in base_commands.py. They model the
synthetic profile's userland (Linux coreutils/util-linux, Alpine BusyBox, macOS BSD, PowerShell core or cmd
builtins). They establish availability only; stronger observations and task constraints still apply, and
unrecognized flags remain UNKNOWN. A missing observation overrides a base availability assumption.

Report the share of UNKNOWN commands over **all extracted commands across all recorded answers**. Include
UNKNOWNs in BROKEN answers; questions/prose have no commands. Record parser availability. When the answer corpus
changes, report both the full current corpus and the original-ID subset with its original denominator.

## Pre-run review corrections (2026-11-01)
Added POSIX-family hints, OS/program reason precedence, UNDECIDED, cited base-userland data and five recorded
review regressions. No model answers have been collected. With bash, dash and pwsh available, UNKNOWN changes
from 3/39 (7.69%) at f59c325 to 1/39 (2.56%) for the original 55 answers, or 1/44 (2.27%) for all 60 current
answers. See tests/unknown_before.json and tests/unknown_after.json. This is a fixture check, not an arm comparison.

## Audit
A blind 20 % sample of judged commands is read by the owner (does WONT_RUN hold on that machine; would FITS run).

## Models
To be fixed before the run: one free model (as BDX-003) and one paid model if a budget is available.

## Changes after data
(none)
