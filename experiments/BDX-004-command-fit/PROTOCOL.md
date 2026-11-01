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
| D | *deferred* (2026-11-02): arm B, then the judge's objections as feedback, the candidate gate; run only if C − A or B − A shows the snapshot helps |

System prompt (all arms; 2026-11-02, before registration): "You help a person with their own computer. Answer for
this person's machine. When the answer involves commands, give the exact commands for them to run. If you do not
know their system, ask, or say which system your commands are for." A person asking for help expects commands for
their machine; an answer for several systems at once stays possible and is measured (HEDGED), but it is no longer
what the prompt invites. Arm D's feedback, when it runs, lists each WONT_RUN command with its reason and the profile
facts it rests on, in the hook's form ("buddie sent this text back ..."); UNKNOWN commands are not fed back.

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
  missing overrides it; unrecognized flags of a present program FITS when syntax parses and no task constraint
  is broken. Patterns add constraints/effects, not a whitelist. FITS concerns machine fit, not option semantics
  or successful completion of the requested task.

Lists/control implementation details:
- POSIX lists split on unquoted &&, ||, semicolons and newlines; PowerShell statements split on unquoted
  semicolons and newlines. Preserve multiline quotes and unfinished connectors before extraction. Child verdicts
  are retained, and complete-list syntax is checked without executing answer text. POSIX/PowerShell pipelines
  split on top-level unquoted |; stages are judged individually and take the worst verdict. Pipeline stage
  setup is isolated; only pending install intent is exported, with no execution or dataflow inference.
- Extract nested/incomplete if/elif/else/fi, for/while/until/do/done and case/esac as one command. Judge conditions
  and bodies recursively and take the worst potential branch. This is a static audit, not a branch prediction.
  Dynamic headers/pattern substitutions and unsupported grammar are UNKNOWN, never silently NO_COMMANDS.
- A recognized successful venv creation establishes that literal venv's activation script within its section.
  Activate-venv tasks also declare .venv as existing, including literal Windows bat/ps1 paths; fish/csh activation scripts require that shell observed.
  Compatible source/dot activation then FITS; source is not supported by sh. Do not export new conditional setup
  or uncertain OR effects. Removal, relocation, overwriting or unknown side effects invalidate existence proofs,
  including possible deletion along a conditional path. State resets between answers and declared audience sections; neutral child headings retain scope.
- Parser stdin preserves LF bytes on Windows too. Tokenizer uncertainty remains UNKNOWN; quoted literal text
  is not proof of a bashism.

The installed-tagged-shell follow-up from 2bd7873 was implemented in 103b913. Audience selection now precedes
command validation; observed alternate shells use explicit alternate task rules or bounded base/generic rules,
without borrowing the default shell's task forms or builtin assumptions.

## Endpoints

- **Primary** (2026-11-02, before registration): share of **OK** answers (commands for this machine, every one FITS
  or INSTALLS), B − A, paired by unit, all 192 units, 95 % paired bootstrap interval (4000 resamples, seed 7, as in
  BDX-003). OK rather than BROKEN, so that an answer that only asks (ASKED) or says nothing runnable does not count as
  a success.
- **Secondary**: C − A (the snapshot given, not asked for: what knowing the machine is worth at most); in B, the share
  of units where the model called the tool and the categories it asked; BROKEN, ASKED, UNDECIDED and HEDGED shares
  per arm; commands a person must read (offered, and for their machine); input tokens and requests per unit; BROKEN
  by profile and by reason; D − B if D runs.
- **Judge reliability**: from the audit, the share of WONT_RUN verdicts a person on that machine could in fact run
  (false objections), per reason.

Expectations, stated before data, not tested as hypotheses beyond the intervals: OK higher in B than A; C at or above
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
`claude-opus-5` if a paid budget remains after BDX-003. Each model is run on arms A, B, C (D only as stated above).

## Audit

A blind sample of judged commands, up to 10 per arm and verdict (round-robin across reasons, seed 11), is read by the owner: does a WONT_RUN hold on that
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

- 2026-11-01, judge-validation pilot 1 (runs 41256702706 and 41257207065, arm A, gpt-oss-120b, 40 units; answers
  kept apart): **failed**. UNKNOWN 43-50 % of commands (limit 25 %), and a systematic false objection: 30 of 33
  answers give commands for several systems (brew, winget, apt and dnf side by side; 14 commands per answer), and the
  judge objected to every section meant for another system (82-86 % BROKEN). A person reads the section for their
  machine. Before registration, so the rule changes (below) and the pilot is repeated on 40 other units:
  - an answer is split into sections by the system or shell they say they are for (headings, labels such as
    "On macOS", "Windows (PowerShell)", "Debian/Ubuntu", and block tags); only the section(s) for this profile are
    judged; a section for another system is no objection;
  - an answer with sections, none of them for this profile, is BROKEN (wrong_os); an answer without sections is
    judged whole, as before;
  - new secondary outcome: TARGETED (the answer is for one system) vs HEDGED (sections for several), per arm, with the
    number of commands a person must read;
  - inline code is a command only when the text tells the person to run it, or when it has a program and an
    argument; values, paths and lone names are not commands.

- 2026-11-01, judge-validation pilot 2 (run 41338667507, arm A, gpt-oss-120b, 40 units other than pilot 1's): **failed
  again**. Sections work (22 of 37 answers hedged; 3.7 of 7.9 offered commands judged for the profile), but UNKNOWN is
  47 % of commands and three objections are systematic:
  - UNKNOWN for ordinary runnable commands with no task-specific rule (`curl -L -o`, `chmod +x`, `pip install torch`,
    `nvcc -V`): FITS is to mean *runs on this machine* (program present, syntax parses, no task constraint broken),
    not *matches a task pattern*; task rules add constraints (versions, GPU, admin), they are not a whitelist;
  - a verification after an install (`ffmpeg -version` after `sudo apt install ffmpeg`) is program_missing when the
    install step was not recognized: an install command for a program, recognized or UNKNOWN, makes the later use of
    that program UNKNOWN at worst, never program_missing;
  - `sudo` on macOS reads as unavailable: an administrator account on macOS has sudo; and a command whose program is
    missing (apt on macOS, sudo on Alpine as root) is program_missing / wrong_os before needs_admin.
  The judge is fixed and the pilot repeated on 40 further units (pilot 3).

- 2026-11-02, judge-validation pilot 3 (run 41346301829, 40 units used by neither earlier pilot): **failed**,
  closer. UNKNOWN 35 % (limit 25 %); 28 of 34 answers hedged across systems. Remaining false objections come from
  sections the judge does not see: headings for several systems at once ("Unix-like shells (Linux, macOS, WSL)"),
  commands in tables under a system heading, labels inside a sentence ("Install with `sudo apt install inxi`
  (Debian/Ubuntu)"); remaining UNKNOWN mostly pipelines (`ps -ef | grep sshd`) and package managers of another
  distribution read as unobserved instead of wrong_os. Ten whole answers are kept as judge material in
  tests/pilot/pilot3_answers.jsonl (run 41346616739, same units; not results).

- 2026-11-02, owner, before registration: the design is simplified (system prompt that asks for commands for this
  person's machine; primary endpoint on OK answers; arms A, B, C, with D deferred; a smaller stratified audit). The
  judge gets one more iteration on the pilot-3 material (pipelines, another distribution's package manager as
  wrong_os, multi-system headings, tables, inline labels), then pilot 4 on 40 units no earlier pilot used, with the
  new system prompt.

- 2026-11-02, owner reports judge-validation pilot 4 (run 41357808790): 25.7% UNKNOWN (limit 25%) and
  no false objection. Remaining forms are literal file execution with task/answer existence evidence, absolute
  executable identities, distribution-shipped service/socket tools and PowerShell cmdlets on POSIX-only profiles.
  The follow-up below uses hand-written records of the supplied forms; no raw pilot-4 answers were supplied
  on this branch and no new model/pilot run is made by this correction.

## Changes after data

(none)

## Pilot-1 rule implementation (before registration)

Audience mappings are data in section_targets.json. Labels and fence tags constrain OS/distro/package manager/
runtime/shell; aliases within an axis are alternatives and different axes are conjunctive. Explicit mixed-system
alternatives (Windows / Ubuntu) preserve separate correlated constraints rather than intersecting them.
Matching command-free explanations are applicable sections; neutral child headings retain bold/colon scopes
and inline instructions. TARGETED/HEDGED distinguishes package-manager alternatives such as apt versus dnf.
Heading depth scopes
subheadings; generic verification peers are shared only after some targeted section applies. Only selected
sections establish setup state. No applicable section yields answer BROKEN/wrong_os with no fabricated command.
TARGETED/HEDGED and commands_total/commands_for_profile are emitted on every answer; counts are extracted parent
units after inline filtering, before/after audience selection. No new model calls or pilot results in this fix.
The synthetic check contains 88 distinct hand-written answers / 107 profile cases, including 12 realistic
multi-system answers. With bash/dash/pwsh, UNKNOWN parents change from 25/237 (10.55%) before b036dd5 to
6/109 (5.50%) after; leaves from 27/258 (10.47%) to 8/130 (6.15%). Offered commands change 237 to 231 because
six inline references are excluded; 122 other-audience instructions are then filtered. Before/after snapshots
are tests/sections_before.json and tests/sections_after.json. This does not qualify or register a new pilot;
repeat the judge-validation pilot on 40 other units separately as specified above.

## Pilot-2 rule implementation (before registration)

FITS is based on known program availability, parsed shell syntax and additive task constraints. Extra options
do not erase version, GPU/CUDA, module, OS or privilege constraints. Unfamiliar flags are not validated as an
application CLI. Unsupported dynamic constructs remain UNKNOWN; no suggested command is executed.

Install intent for apt/dnf/apk/brew/winget/choco/pip/npm/conda suppresses later program_missing for its literal
package within the same section, even if the install is UNKNOWN. Only recognized successful effect rules
prove presence; other forms record pending uncertainty. This includes conditional/OR attempts but excludes
syntax-rejected constructs. Other decisive constraints still apply. macOS sudo permission is UNKNOWN unless
explicitly missing; missing program/OS reasons precede admin. Source/dot activation requires a task-declared
or created venv; unknown paths and unobserved fish/csh variants cannot pass via the generic fallback.

Sixteen new literal recorded answers plus the earlier corpus make 123 profile/answer cases. Identical
bash/dash/pwsh availability before/after: UNKNOWN parents 16/128 (12.50%) to 9/128 (7.03%); recursive leaves
18/149 (12.08%) to 10/149 (6.71%). Both include UNKNOWNs beneath BROKEN parents; offered counts stay 250.
See tests/pilot2_before.json (94fa8a1), tests/pilot2_after.json and README reproduction command. This is an
offline synthetic comparison, not a new pilot or registration. Pilot 3 on 40 further units remains separate.

## Pilot-3 material correction (before pilot 4, 2026-11-02)

Implemented the owner’s last judge iteration while preserving the simplified design and pilot-4 settings.
Ten whole source answers are recorded verbatim as tests/pilot3_answers.json with expected outcomes and
rationales, source line and UTF-8 text hashes. The original source/truncation stays unchanged. Audience
unions, table columns/rows, immediate suffix labels, observed Git Bash/MSYS2, and syntax-safe comment labels
select only applicable instructions; explicit sample output and interpretation headers are excluded.
Pipeline stages receive separate verdicts and fold to the worst; sourced base userland includes the common
filters. Foreign distro managers are wrong_os; optional brew/winget/choco require observed availability.

All 133 recorded profile/answer cases, with identical bash/dash/pwsh availability: UNKNOWN parents
34/200 (17.00%) before 73bdc3a to 53/212 (25.00%) after; UNKNOWN leaves 35/221 (15.84%) to
54/248 (21.77%). Offered counts are 415 to 455. On the ten material answers, 30 new selected instructions
(20 UNKNOWN) replace 18 older extractions; three matched WONT_RUN become UNKNOWN, one UNKNOWN becomes FITS.
Their outcomes change 7 BROKEN/3 UNDECIDED to 1 OK/3 BROKEN/6 UNDECIDED; their parent UNKNOWN share is
25/72 (34.72%) to 44/84 (52.38%). Missing tool/setup/privilege observations remain UNKNOWN. The increase
is reported explicitly rather than discarded or treated as success. See pilot3_before.json/pilot3_after.json
and the README reproduction command. This is offline judge regression material, not pilot-4 results or
registration; the planned fresh pilot remains separate.

## Pilot-4 remaining-form correction (before registration, 2026-11-02)

Absolute executable paths use the normal program’s availability and task constraints, while original text
is syntax-checked and retained in output. Literal placeholders never establish presence. Direct file
execution requires task-provided or bounded successful earlier-command evidence for the exact path; the
permissions task declares script.sh. File/venv state shares conservative branch, scope and mutation rules.
No host filesystem or suggested program is inspected/executed. Program basenames also drive mutation
invalidation, preventing stale proofs after absolute rm/mv/cd commands.

Sourced per-distro userland adds service and nc/ncat/ss/process tools where assumed by these scenarios;
unlisted tools remain uncertain and missing observations still win. Admin constraints survive service
mutator aliases. A conventional PowerShell cmdlet in a POSIX-only profile receives wrong_shell_syntax;
normal observed programs and observed alternative shells retain their existing treatment.

Eighteen new hand-written cases with literal expectations make 151 recorded profile/answer cases. With
bash/dash/pwsh available on both sides, UNKNOWN parents are 71/233 (30.47%) at 45f4317 versus 53/233 (22.75%)
after; recursive leaves 72/269 (26.77%) versus 54/269 (20.07%). Offered/selected parent counts stay 476/233.
All BROKEN answers and UNKNOWN children are retained. Evidence: tests/pilot4_before.json, pilot4_after.json,
pilot4_answers.json and README reproduction command. This is an offline corpus check, distinct from the
owner-reported pilot-4 percentage; no fresh pilot qualification or registration is claimed.
