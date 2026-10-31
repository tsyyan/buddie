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

## Audit
A blind 20 % sample of judged commands is read by the owner (does WONT_RUN hold on that machine; would FITS run).

## Models
To be fixed before the run: one free model (as BDX-003) and one paid model if a budget is available.

## Changes after data
(none)
