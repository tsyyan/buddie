# BDX-004 implementation plan and ledger

Goal: implement CODEX_TASK.md without model calls or dependencies outside the stdlib.
The supplied brief is the design and execution authorization. All new material stays here,
except `.github/workflows/bdx004.yml`.

Architecture: static diagnostic documents and per-profile task rules feed independent
Markdown extraction, a deterministic snapshot stand-in, and a conservative judge.
Commands are parsed for syntax only, never executed. No provider or network code.

## Commit sequence

1. Profiles and schema/provenance tests. Build eight baseline-complete documents and
   index metadata; validate every document with `buddie.diagnostics.problems`.
2. Tasks and coverage tests. Add 24 tasks, explicit per-profile requirements and a
   deterministic eligible-unit list with seed. Test IDs, references and coverage.
3. Extraction and tests. Preserve command order/shell, strip prompts/output/comments,
   join continuations and cover inline code and Markdown edge cases.
4. Tool and tests. Copy the MCP schema, validate arguments, restrict categories/tools,
   reproduce denial/catalog semantics without probing the host.
5. Judge and tests. Check shell/OS/program/version/privilege rules, parser availability,
   and sequential installs; test conservative UNKNOWN and CLI behavior.
6. Recorded answers. At least 12 distinct pairs with good/bad/question-only answers
   plus tricky cases; assert literal expected outcomes and reasons.
7. CI and README. Pinned actions, Ubuntu/Windows Python 3.12 tests, counts and limits.

Each implementation step starts with failing tests, then implementation, full experiment
tests and a separate all-profile validation before its commit. Final review checks
scope, no execution of answer text, missing observations, unsupported shell syntax,
installer state, and platform-independent outcomes.

## Rulings and progress

- The native worktree tool rejected the nested repository path. Used a sibling Git
  worktree on the explicitly requested branch; no existing checkout was edited.
- Diagnostics does not observe sudo, libc, or ash/sh versions, and does not say which
  Windows shell the user is typing in. Preserve its schema and record those scenario
  assumptions in index/task metadata, never as invented diagnostic observations.
- Python 3.10 may be a target interpreter while buddie itself runs on Python 3.11+.
  The no-venv profile therefore has a separate 3.12 buddie_runtime.
- Profiles complete: 1 test passed; 8 profile documents independently validated.
- Tasks complete: 2 tests passed; 8 profiles validated; 24 tasks and 192 pairs.
- Extraction complete: 7 tests passed; 8 profiles validated.
- Tool complete: 13 tests passed; 8 profiles validated; catalog and schema compared to real code.
- Judge complete: 26 tests ran, 1 skipped (no local POSIX parser); 8 profiles validated.
- Recorded answers complete: 27 tests ran, 1 skipped; 55 answers across 16 complete pairs.
- Ruling: OK retains the protocol's meaning of no proven WONT_RUN. UNKNOWN commands are
  separately counted and `all_commands_decided` is false; consumers must retain these
  fields to avoid counting unproven commands as fitting.
- Final independent review found three important issues, reproduced by failing regression tests:
  Python alias deduplication was mistaken for absence; extraction dropped quoted/wrapped
  executables; Node 20 rules allowed later major versions. Fixed the facts/extraction/rule
  boundaries and retained environment-changing wrappers as UNKNOWN. The recorded Ubuntu
  broken example now uses observed-missing conda rather than an unobserved Python alias.
- Review fixes verified: 31 tests passed with Git Bash and pwsh available; all 8 profiles
  validated again. No deferred review findings. Broader repository tests run separately.
- Final extraction check reproduced common curl/pip/ffmpeg/Docker version output as
  spurious extra commands. Added a failing regression and filtered these output forms;
  32 experiment tests now pass, with all 8 profiles independently validated.

## PR review corrections (2026-11-01)

User-specified follow-up: (1) POSIX shell families and OS/program reason priority;
(2) explicit UNDECIDED answers; (3) cited base-command data; (4) expanded recorded
answers and before/after UNKNOWN shares. Each is a small test-first commit in this folder.
The earlier OK ruling above is superseded by the requested UNDECIDED outcome.

Baseline f59c325: 55 recorded answers, 39 commands, 3 UNKNOWN (7.6923%) with bash,
dash and pwsh available. Saved actual per-command results in tests/unknown_before.json.
Shell-family regressions were observed failing before the fix; the complete 37-test
experiment suite now passes with those parsers. All eight profiles still validate.

UNDECIDED regression observed failing, then fixed. Updated the corpus's literal expected
outcomes and both protocol/README; BROKEN still precedes UNKNOWN and empty text is not OK.

Base-userland regressions observed failing without task-specific whitelist/assumptions, then
fixed with cited availability sets and bounded command-form data. The complete 46-test suite
passes; explicitly missing observations still override base assumptions and unsupported
options/foreign userlands are not inferred as FITS. All eight profiles validate.

Added five hand-labelled recorded review cases (60 answers total) and recorded_stats.py.
Counter/denominator regressions were observed failing before implementation. Reference
UNKNOWN shares with bash/dash/pwsh: before 3/39; after original IDs 1/39; all current
answers 1/44. The immutable before verdict snapshot and after report are checked in.
The comparison reports parser availability and never drops unknown or broken answers.

Final independent review reproduced two false-objection cases: sh regex checks inspected
quoted literals, and shlex's foreign quoting rules were treated as authoritative. Added
failing regressions and fixed both. Added a module-availability-before-tag regression too.
Final suite: 53 tests pass with bash/dash/pwsh; eight profiles validate. Recorded UNKNOWN
counts remain 3/39 before, 1/39 matched after, 1/44 expanded after. No deferred findings.

## Lists and control structures follow-up

User authorization: add quote-aware POSIX lists/PowerShell statements, venv setup state,
POSIX control structures as one extracted command, and recorded cases/UNKNOWN shares.
Plan: commit lists/state with regressions; commit control extraction/evaluation; commit
recorded cases and measurements. All changes stay in this experiment directory.

Captured the current 60-answer/44-command baseline at 5e4c330: 1 UNKNOWN with bash,
dash and pwsh available (tests/lists_before.json). List/state tests were observed failing
before implementation. Full suite now passes 61 tests with those parsers; profiles validate.

Control regressions were observed failing before implementation. Added bounded recursive
if/loop/case parsing, intact extraction, whole-structure syntax and branch-local evaluation.
The parser consumes data only; dynamic/unsupported forms are UNKNOWN. Found and reproduced
Windows CRLF stdin corrupting dash closing keywords; switched parser stdin to LF bytes.
The complete suite now passes 67 tests with bash/dash/pwsh; eight profiles still validate.

Independent review found and regressions reproduced multiline quote/connector splitting,
dynamic case-pattern false FITS, and stale venv proofs after mutations. Fixed logical-line
extraction and invalidated proofs through modeled mutations/unknown effects/conditional
paths; dynamic patterns stay UNKNOWN. Also kept incomplete quoted structures intact.
All 74 tests pass with bash/dash/pwsh; all profiles validate. No review findings deferred.

Added sixteen literal recorded list/control/state cases, including parent and recursive
leaf expectations (76 total answers). A failing metric regression exposed UNKNOWN leaves
hidden by BROKEN parent lists; added separate parent/leaf shares and recursive answer
decidability. Reference shares: original IDs unchanged 1/44; expanded parents 6/60 and
leaves 8/81. Snapshots and README/PROTOCOL record both denominators and parser availability.
Full suite passes 76 tests with bash/dash/pwsh; every profile validates before this commit.

Push encountered concurrent remote 2bd7873 (PROTOCOL v1 only). Rebased the four unpublished
commits without force-pushing; preserved the remote protocol at each conflict and reran
61/67/74/76 tests plus profile checks before each rebase continuation. Added list/control
and metric details back into v1 without changing arms/endpoints/models/audit. Its new
installed-tag override is beyond this request and conflicts with the earlier negative
case; asked the owner asynchronously and, absent new direction, retained current selection
and explicitly recorded this pre-registration follow-up in README/PROTOCOL/PR.

## Pilot-1 sections correction

Fast-forwarded to remote b036dd5 and read the failed pilot's recorded rule change. This
pass makes no model calls and does not change run settings/workflows. Plan: (1) stricter
inline extraction, (2) data-backed section scope/targeting/counts, (3) twelve realistic
multi-system answers, bounded verification forms, measurements and docs. Review after code.
Captured pre-change results for 76 existing plus 31 profile checks on 12 new answers:
107 profile-answer cases, 237 parent commands, 25 UNKNOWN (tests/sections_before.json).
Inline regressions failed first; the complete suite now passes 85 tests with all parsers.
Section regressions failed first, then passed: audience aliases live in JSON, labels/tags
scope commands and state, no matching section gives BROKEN/wrong_os, and targeting/counts
are emitted. Updated old cross-family fixtures to the new no-applicable-section outcome;
primitive reason-order tests still exercise validation directly after selection. Observed
alternate shells use bounded base rules without borrowing default-shell task assumptions.
Validated the twelve multi-OS answers against 31 literal profile outcomes. Node -v tests
failed first, then passed after adding that bounded Node 20 verification form. Added offline
runner integration (no foreign-section feedback), targeting/read-count summaries and paired
metrics. Same 107 cases: parent UNKNOWN 25/237 to 6/109; leaf UNKNOWN 27/258 to 8/130.
The full suite passes 99 tests with all parsers, and all eight profiles validate.
Independent review found six boundary cases: inline instructions in headings, bold audience scope under
neutral subheadings, correlated OS alternatives, manager-only targeting, explicitly invoked unfamiliar
executables, and matching explanations without commands. Added regressions, observed failures, then fixed
them. Full suite now passes 105 tests with all parsers; metrics remain unchanged and all profiles validate.
Default-PATH verification exposed an invalid fixture fallback: UNKNOWN installation cannot establish a
program for later verification, so missing parsers do not always mean UNDECIDED. Replaced that fabricated
expectation with a parser-dependent outcome skip, after still checking selection/count metadata.

## Pilot-2 correction

Fast-forwarded to 94fa8a1, preserving the owner's pilot-2 settings/history. Captured 123 profile/answer
cases before changing code (107 existing plus 16 new pilot-shaped cases), with bash/dash/pwsh available.
Plan: availability/syntax and sudo ordering; section-local uncertain installations and task-proven venvs;
then measurements, documentation and PR update. No provider/model calls or workflow changes.
First regressions failed as expected, then 109 tests passed: fallback FITS requires known presence and
parsed syntax; version/admin/GPU constraints survive unmatched forms. Missing sudo is program_missing;
macOS sudo permission is UNKNOWN. Updated literal recorded expectations for the new semantics.
Second-step regressions failed first, then passed: installation intent has a weaker pending state (no
proof of presence), scoped to the declared audience, including an undecided AND predecessor. Ordinary
successful installs establish presence; task versions still need evidence. Activation tasks explicitly
declare .venv as existing; literal creation and mutation rules remain. fish/csh script variants require
an observed shell. Full suite passes 113 tests with all parsers; all eight profiles validate.
Review regressions reproduced CUDA options bypassing GPU checks, Python options hiding a missing module,
unsupported activation paths bypassing existence proof, and syntax-rejected lists leaking pending intent.
Fixed each; generic installer forms now establish only pending intent, including dry-runs/download-only.
Bounded successful effects still prove installation, and bounded venv options preserve creation proofs.
Windows executable activation remains outside the requested source/dot change; existing_venvs data is POSIX-only.
Recorded 16 pilot-shaped answers with literal expected verdicts. Paired 123-case measurement at 94fa8a1:
parents UNKNOWN 16/128 to 9/128, leaves 18/149 to 10/149, offered/selected counts unchanged (250/128).
README/PROTOCOL updated; historical snapshots retained. Full suite 121 tests passes with bash/dash/pwsh
and on default PATH (51 parser-dependent skips); all eight profiles validate. No new pilot/model calls.

## Last correction before pilot 4

Fast-forwarded to 73bdc3a, preserving the owner's simplified design, pilot-3 material and pilot-4 settings.
Read all ten whole answers. Added literal human-labelled outcome/rationale records preserving each answer's
bytes and source-line/hash; captured all 133 recorded profile/answer cases before changing judge code.
Plan: stage-wise pipelines/base userland; distro manager applicability; richer audience/table/inline labels;
whole-answer regressions, paired measurements and documentation. No model calls or workflow/settings changes.
Pipeline tests failed before implementation; stages now retain individual verdicts with the worst folded
to the parent, preserving list precedence and quoting. Pipeline effects do not establish successful setup.
Manager regressions passed with per-distribution data and explicit observations for optional managers.
Section regressions then failed first and passed after unions, table command columns/row audiences,
trailing inline labels and observed Git Bash/MSYS2 support. Whole material is preserved as UTF-8 with
source hashes; fixed a Windows locale copy error and regenerated only those historical baseline rows from
archived 73bdc3a code. Whole-answer outcomes require Windows activation paths, output-fence exclusion,
and weak NVM/Node/npm install intent too. Review reproduced and fixed comment scopes breaking quoted/control
units and Git Bash losing its selected shell at validation. No important review findings remain.
All ten material outcomes pass (1 OK, 3 BROKEN, 6 UNDECIDED). Saved paired report over all 133 cases:
UNKNOWN parents 34/200 (17%) to 53/212 (25%); leaves 35/221 to 54/248. Reported the increase explicitly,
including the 30 new/18 removed selected instructions and the material-only share; no pilot-4 success claim.
Full suite passes 136 tests with all parsers; default PATH passes with 61 parser-dependent skips. All eight
profiles validate and the saved report reproduces exactly. Only experiment files changed in this pass.
Final targeted regression distinguishes explicit Linux (Debian/Ubuntu) restrictions from broad Linux
headings with examples. It failed first, then the complete suite passed 137 tests; all profiles validate
and the saved paired report is unchanged.

## Pilot-4 remaining forms

Owner reports run 41357808790 had 25.7% UNKNOWN and no false objections. No new protocol history or raw
pilot-4 answers were on the branch at start (45f4317); the 18 new literal records are hand-written from
the supplied forms, not claimed as original model responses. Captured all 151 cases before code changes
with bash/dash/pwsh. Plan: absolute executable identity/cmdlets, sourced distribution userland, bounded
task/answer file proofs, then paired measurements/docs/PR. No model calls, run settings or workflow edits.
Initial executable/cmdlet regressions failed first. Normalization now preserves original command text
and syntax checks while retaining version/OS/module/admin constraints. PowerShell call syntax is parsed
as invocation; POSIX-only cmdlet shapes use selected official verbs without rejecting ordinary hyphenated tools.
Userland regressions failed first, then passed with sourced per-distro service/socket/netcat assumptions.
Unknown distributions do not inherit these sets; explicit missing observations still win. Service restart
aliases retain admin checks. macOS/Alpine do not acquire an unshipped service or ss by a blanket Linux list.
