# BDX-004 protocol

Version 1, 2026-11-01. Written before any model answer. It is registered (this line gets the registration date and
commit) when the judge-validation pilot below has passed and before the first answer of the experiment is recorded.
Every change after that is listed under "Changes after data", with its date and reason, as in BDX-003.

## Question

Does buddie's environment snapshot make the commands a model tells a person to run fit that person's machine, and
would a model-free check of those commands (a candidate hook gate) catch the rest without objecting to commands that
are fine? See README.md.

## Material

- **Profiles**: 8 machines (`profiles/index.json`): Windows 11 with PowerShell and an NVIDIA GPU, Windows with cmd and
  no GPU, macOS on Apple Silicon, Ubuntu 24.04 with CUDA, Ubuntu 22.04 without sudo, WSL, Fedora 40, Alpine in a
  container. Each is an `environment-diagnostics-v1` document that `buddie.diagnostics.problems` accepts. All are
  hand-built; none describes a real machine.
- **Tasks**: 24 (`tasks/tasks.json`), each phrased with no word about the machine, with the categories it needs and
  what a command must satisfy on each profile.
- **Units**: the 192 (profile, task) pairs where the task applies (`tasks/units.json`, seed 4).

## Arms

The same model, system prompt and task in every arm; arm order randomized per unit (seed recorded).

| Arm | The model gets |
|---|---|
| A | the task only |
| B | the task, and the tool `environment_snapshot` (`tool_schema.json`) answered by `tool.py` from the profile: the requested categories, those outside the profile's grants as `denied` |
| C | the task, with the profile's snapshot of the task's categories in the first message |
| D | arm B, then, while the judge finds a WONT_RUN command, its objections as feedback (at most 2 rounds) |

System prompt (all arms): "You help a person with their own computer. When the answer involves commands, give the
exact commands for them to run." Arm D's feedback lists each WONT_RUN command with its reason and the profile facts
it rests on, in the hook's form ("buddie sent this text back ..."); UNKNOWN commands are not fed back.

## Outcomes (judge.py, no model; no answer text is ever executed)

Per command: FITS, INSTALLS, WONT_RUN (program_missing, wrong_shell_syntax, wrong_os, version_mismatch,
needs_admin), UNKNOWN. Per answer: OK (one or more commands, every one FITS or INSTALLS), BROKEN (any WONT_RUN),
UNDECIDED (at least one UNKNOWN, no WONT_RUN), ASKED (asks about the machine, no command), NO_COMMANDS. BROKEN takes
precedence over UNDECIDED. UNKNOWN never counts as FITS, and UNDECIDED answers stay in every denominator.

Shell rules:
- Shell hints are families: bash, sh, zsh, shell, console are POSIX; PowerShell and cmd are separate. A block tagged
  for a shell is runnable when that shell is observed on the profile (decided 2026-11-01: a PowerShell block on a
  Windows profile whose default is cmd but which has Windows PowerShell or pwsh is judged as PowerShell, not as a
  wrong shell). The profile's default shell decides only for untagged blocks.
- OS and program failures are reported before a shell mismatch.
- Syntax is parsed with the target shell's parser: `bash -n`; `dash -n` plus explicit bashism checks for sh; the
  POSIX-parseable subset for zsh (else UNKNOWN); PowerShell's `Parser.ParseInput` when `pwsh` is present (else
  UNKNOWN); a small explicit rule set for cmd. A failure of the judge's own tokenizer is UNKNOWN, not invalid syntax.
- Command lists (`&&`, `||`, `;`) and control structures (`if`, `for`, `while`, `case`) are judged part by part; the
  list takes its worst part (WONT_RUN > UNKNOWN > INSTALLS > FITS).
- Base userland (`base_commands.py`, cited sources) establishes availability only; an observation that a program is
  missing overrides it; unrecognized flags stay UNKNOWN.

Lists/control implementation details:
- POSIX lists split on unquoted &&, ||, semicolons and newlines; PowerShell statements split on unquoted
  semicolons and newlines. Preserve multiline quotes and unfinished connectors before extraction. Child verdicts
  are retained, and complete-list syntax is checked without executing answer text.
- Extract nested/incomplete if/elif/else/fi, for/while/until/do/done and case/esac as one command. Judge conditions
  and bodies recursively and take the worst potential branch. This is a static audit, not a branch prediction.
  Dynamic headers/pattern substitutions and unsupported grammar are UNKNOWN, never silently NO_COMMANDS.
- A recognized successful venv creation establishes that literal venv's activation script within the answer.
  Compatible source/dot activation then FITS; source is not supported by sh. Do not export new conditional setup
  or uncertain OR effects. Removal, relocation, overwriting or unknown side effects invalidate existence proofs,
  including possible deletion along a conditional path. All state resets between answers.
- Parser stdin preserves LF bytes on Windows too. Tokenizer uncertainty remains UNKNOWN; quoted literal text
  is not proof of a bashism.

Open implementation follow-up: the installed-tagged-shell selection policy above was added concurrently in
2bd7873. This lists/control pass retains the existing per-profile target-shell selection; the explicit-tag
override is not implemented by this pass. Resolve that policy/implementation gap before judge registration.

## Endpoints

- **Primary**: share of BROKEN answers, B − A, paired by unit, all 192 units, 95 % paired bootstrap interval (4000
  resamples, seed 7, as in BDX-003).
- **Secondary**: C − A (the snapshot given, not asked for); D − B (what the gate adds); D − A; in B, the share of
  units where the model called the tool and the categories it asked; ASKED and UNDECIDED shares per arm; input tokens
  and requests per unit; BROKEN by profile and by reason.
- **Judge reliability**: from the audit, the share of WONT_RUN verdicts a person on that machine could in fact run
  (false objections), per reason.

Expectations, stated before data, not tested as hypotheses beyond the intervals: B below A; C at or below B; D below
B; false objections under 10 % of WONT_RUN verdicts. A gate (`commands` in the hook) is proposed for the plugin only
if D − B is below zero and false objections stay under 10 %.

## Judge-validation pilot (before registration; its answers are not results)

Arm A only, model `openai/gpt-oss-120b` (free tier, as BDX-003), 40 units drawn stratified by profile (5 per profile,
seed recorded). The owner reads every judged command (a check of the judge, not of the arms).
The judge passes when UNKNOWN is at most 25 % of extracted commands and no reason class shows a systematic false
objection. Failing that, the judge is fixed from these answers and the pilot is repeated on 40 other units. The
pilot's answers are kept apart and never pooled; judge changes after registration go to "Changes after data".

## Models

`openai/gpt-oss-120b` through the free providers of BDX-003 (one provider per unit, never split), and
`claude-opus-5` if a paid budget remains after BDX-003. Each model is run on all four arms.

## Audit

A blind 20 % sample of judged commands, stratified by verdict, is read by the owner: does a WONT_RUN hold on that
machine, would a FITS run. Disagreements are reported per verdict and reason; a reason class with more than 10 %
false objections is reported as unreliable and left out of the gate proposal.

## Before data: judge history

- 2026-11-01, review of the starter set: POSIX shell families, OS and program reasons before the shell tag, UNDECIDED,
  cited base userland, review regressions recorded. UNKNOWN over the recorded answers: 3/39 (7.7 %) at f59c325,
  1/39 (2.6 %) after, 1/44 (2.3 %) over all 60 answers (tests/unknown_before.json, unknown_after.json). Recorded
  answers are simpler than a model's, so the pilot above measures UNKNOWN on real ones.
- 2026-11-01, owner: a tagged block is judged in its own shell when that shell is observed on the profile (above);
  command lists and control structures are judged part by part.
- 2026-11-01, lists/control implementation: 76 recorded answers, with parent and recursive leaf expectations.
  With bash/dash/pwsh, the matched original 60 answers stay 1/44 UNKNOWN (2.27%). The expanded corpus has
  6/60 UNKNOWN extracted parent units (10.00%) and 8/81 UNKNOWN leaf verdicts (9.88%), including deliberate
  dynamic-pattern, failed/removed-setup and branch-uncertainty guard cases. UNKNOWN children of BROKEN parents
  are included in the leaf denominator. See tests/lists_before.json and tests/lists_after.json; these are
  synthetic fixture checks, not arm results. Record parser availability and both parent/leaf denominators;
  answer all_commands_decided checks the entire tree rather than hiding UNKNOWN below a BROKEN parent.

## Changes after data

(none)
