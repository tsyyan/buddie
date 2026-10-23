# Adversarial verification

Whether buddie's verification decisions keep their trust boundaries when the agent under check attacks them. Each
row is an attack the agent can mount with what it controls, run through the entry point that decides (the hook on
a Stop event, the CLI, MCP, the collectors), with the test that holds it. `tests/test_adversarial.py` holds the
ADV rows; earlier suites hold the ones they name.

## Who controls what

**Attacker-controlled** (the agent runs as the person's OS user): its answers; the repository, its `.git` (config,
index, objects, hooks, a `.git` file naming another git directory) and its files; `buddie.toml`; the session's
snapshot stores; files it writes (snapshots, logs); the hook's environment (a project's `.claude/settings.json`
`env`); refs it creates on GitHub (branches, tags) and pushes to a PR. **Trusted**: the protected policy; the host
(Claude Code's transcript of tool calls, the event it sends); buddie's own code and what it observes itself; GitHub's
answers to buddie's own requests, checked against each other. **Outside**: the trusted base (PATH, Python, git) and
Python code running in buddie's interpreter ([security.md](security.md)).

## Threat matrix

Columns: what the attacker controls; what buddie must do; what it does (before this PR, where it differed); why it
matters; the test.

### 1. Evidence forgery

| Id | Attack (attacker controls) | Expected | Actual | Significance | Test |
|---|---|---|---|---|---|
| ADV-1.1 | a receipt-v0 / receipt-v1 saying PASS pasted into the answer, with a false quote | the text is checked; a receipt in it vouches for nothing | returned (exit 2), FAIL | a forged verdict is not a verdict | `test_adv_1_1` |
| ADV-1.2 | a `buddie:` line claiming everything was verified, next to a false quote, in the first answer | the false quote goes back first | returned | disclosure is for what was not checked, never a pass | `test_adv_1_2` |
| ADV-1.3 | MCP `verify_report` arguments `provenance`, `observed`, `verified`, `collected` | not arguments; provenance counts only what buddie collected | no collector-observed evidence | caller-supplied provenance is not provenance | `test_adv_1_3` |
| ADV-1.4 | a fake execution log: `echo "41 passed"`; a claimed run whose real output says otherwise | `run:` does not hold | BROKEN, returned | a command's text is not its output | `test_adv_1_4` |
| ADV-1.5 | a commit the agent made itself, named by `path@commit` | holds, as agent-writable evidence, never collector-observed | as expected | **limitation**: a repository proves what is in it, not who put it there | `test_adv_1_5` |
| ADV-1.6 | a consistent environment snapshot in the repository claiming a commit | no check reads it | not PASS | snapshots are output, never input | `test_adv_1_6`; `test_environment.py::test_sec07…`, `test_freshness.py::test_a_snapshot_is_compared…` |
| — | a `Binding` built, copied, pickled or read from JSON claiming `collector_observed` | not an observation | `evidence_not_observed` | data cannot elevate itself | `test_freshness.py::test_the_identity_registry…` |
| — | a snapshot edited to raise `basis`, `status`, `collector`, digests; hostile subclasses | inconsistent, reported, no method of the caller's run | reported | consistency, not authenticity | `test_environment.py::test_a_hand_edited…`, `test_security_hardening.py::test_sec07…` |

### 2. GitHub and CI deception

| Id | Attack | Expected | Actual | Significance | Test |
|---|---|---|---|---|---|
| ADV-2.1 | a branch or tag named like a SHA prefix (`deadbee`) at a commit with green CI; the answer claims `ci:o/r@deadbee=success` | the checks GitHub gives for that ref are on another commit: not evidence for `deadbee` | **before: HOLDS. Now: UNCHECKABLE** ("is not that commit"), a gap | a ref is not a revision | `test_adv_2_1` |
| ADV-2.2 | `=success` claimed while checks are pending, one suite cancelled, failed, or none at all | never HOLDS | BROKEN (pending, cancelled, failed), UNCHECKABLE (none) | success is not inferred from incomplete or contradictory checks | `test_adv_2_2` |
| ADV-2.3 | `pr:…=merged` while open or closed unmerged; `=open@OLD` after a force-push | BROKEN | BROKEN, returned | what GitHub says now | `test_adv_2_3` |
| ADV-2.4 | GitHub unreachable or refusing | a gap, never a pass | GAPS | missing evidence is missing | `test_adv_2_4` |
| ADV-2.5 | the answers behind a `ci:` anchor: a run without `head_sha`, a run or status on another commit, pages that disagree, a page missing (`total_count`), the ref resolving to another commit | the SHA resolved to its full commit, the latest runs and status fetched once for that id, each naming it, the count read in full; anything else establishes nothing | UNCHECKABLE in each case, HOLDS only when bound | evidence is for the revision it names, or it is not evidence | `test_adv_2_5` |
| ADV-2.6 | a ref that moves between requests (the branch's runs keyed by the ref answer for another commit) | resolved once; checks asked by the full id | the moved ref is never consulted | no contradictory sets of runs | `test_adv_2_6` |
| ADV-2.7 | GitHub failing between the resolution and the runs | a gap with GitHub's reason | UNCHECKABLE | missing evidence is missing | `test_adv_2_7` |
| — | stale CI: green on A, PR at B; a PR head moving between observations; a historical claim about A | STALE; CURRENT only for the claim about A | as expected | the central freshness case | `test_freshness.py` (stale CI, required table, CLI end to end) |
| — | inconsistent GitHub answers (a run naming another commit, a status for another SHA), mismatched repositories, duplicate suites disagreeing | UNKNOWN or `ambiguous`, never success | as expected | no invented certainty | `test_freshness.py` |

### 3. Repository manipulation

| Id | Attack | Expected | Actual | Significance | Test |
|---|---|---|---|---|---|
| — | `.git/config` filters, fsmonitor; hooks, textconv, external diff, aliases, signature programs | nothing the repository names runs | nothing runs | agent code with the person's token | `test_security_hardening.py` (SEC-01, SEC-04) |
| ADV-3.1 | file anchors at `../x`, `/etc/hosts`, `C:/…`, a symlink out | never read, never PASS | not PASS | the repository is the boundary | `test_adv_3_1`; `test_environment.py` (traversal, symlinks) |
| ADV-3.2 | a detached HEAD; an untracked file beside a clean commit | detached at the commit is that commit; an untracked file is not its state | CURRENT; UNKNOWN (`dirty_worktree`) | a HEAD is not the files | `test_adv_3_2` |
| ADV-3.3 | a `.git` file naming another git directory | its facts rest on agent-writable, never on buddie alone | `agent_writable` | **limitation**: the repository's identity is the agent's | `test_adv_3_3` |
| — | assume-unchanged or skip-worktree entries hiding a change | never `clean` | `index_hides_entries` | `clean` is git's view | `test_environment.py` |

### 4. Process execution

| Id | Attack | Expected | Actual | Significance | Test |
|---|---|---|---|---|---|
| ADV-4.1 | anchors shaped as options or shell (`--output=…@sha`, `-c@sha`, `;touch …`, `$(…)`) | one argv item after the commit id, no shell | nothing created, not PASS | text never becomes a command | `test_adv_4_1` |
| ADV-4.2 | a program that writes part of its output and dies | its exit code, not an answer | git's answer is None | partial output is not output | `test_adv_4_2` |
| ADV-4.3 | `GIT_CONFIG_*`, `GIT_DIR` in the hook's environment | buddie's git does not see them | nothing runs | the environment does not configure git | `test_adv_4_3`; SEC-04, SEC-08 |
| — | the plugin's token reaching git, the free command, pdftotext; process trees escaping; output and time exhaustion | none; bounded | as expected | credentials and bounds | `test_security_hardening.py` (SEC-01 to SEC-11) |

### 5. Policy bypass

| Id | Attack | Expected | Actual | Significance | Test |
|---|---|---|---|---|---|
| ADV-5.1 | under a policy floor `quotes = "block"`: `buddie.toml` `[gates] quotes = "off"`, a profile without quotes, `BUDDIE_GATES=quotes=off` | the floor holds | returned | floors are the person's, not the project's | `test_adv_5_1`; `test_policy.py`, `test_profiles.py` |
| ADV-5.2 | `buddie.toml` `[mandate] parent = "(a+)+$"` with a queue row of 40 `a`s, then a verdict claim | the hook answers within its bound | **before: hours in Python's `re` (exponential backtracking, no time limit), so the host's timeout would let the answer out unchecked. Now: the file is unusable, every answer is returned with the reason, at once** | a configured pattern must not be a way around the gate | `test_adv_5_2` |
| ADV-5.3 | other exponential patterns: a repeat over alternatives, a backreference, a repeat inside a repeat whose turns are not separated by a literal, patterns over 512 characters | refused when `buddie.toml` is read | refused; lab-style patterns (`\d+(?:\.\d+)*`) accepted | as ADV-5.2 | `test_adv_5_3` |
| ADV-5.6 | polynomial patterns the static check lets through: `a*a*a*a*b`, `\d*\d*\d*x`, `[a-z]*[a-z]*[a-z]*[a-z]*(?P<parent>\d+)$`, on 2000-character cells (hours in `re`) | the hook answers within its bound | **before: the hook held. Now: the pattern runs in a worker process, stopped after 1 s; the hook returns the answer (`PatternTimeout`)** | no pattern holds the hook | `test_adv_5_6` |
| ADV-5.7 | many calls, each under the per-call bound | one budget for the event's patterns (10 s) | returned when it is spent | calls cannot add up past the bound | `test_adv_5_7` |
| ADV-5.8 | the worker itself | no buddie credential in it; stopped on timeout, a new one next time | as expected | the bound holds after a timeout | `test_adv_5_8` |
| ADV-5.9 | the CLI on such a pattern | exit 2 (the input cannot be used), not 1 (FAIL) | 2 | a timeout is not a verdict | `test_adv_5_9` |
| ADV-5.10 | lab's own patterns through the worker | the same answers as in-process | the same | legitimate configuration is kept | `test_adv_5_10`, `test_mandate.py`, `test_due.py` |
| ADV-5.11 | a worker that misbehaves outside matching: never reads its stdin (a request bigger than the pipe's buffer), never says it is ready, sends a wrong ready line, stops reading after one answer, answers half a line and waits or exits, answers a whole line that is not an answer, exits while the request is written; failing again and again | every step bounded: its start (within STARTUP and the event's budget), writing the request (a thread joined until the call's deadline), its answer (a whole JSON line of the expected shape by the same deadline); then stopped (killed, its job closed on Windows, reaped, pipes closed); one worker at a time | **before: a worker that did not read held buddie on a full pipe without bound. Now: each case 0.08 to 3.1 s, no worker left** | the bound covers the whole interaction | `test_patterns_worker.py` |
| ADV-5.4 | `refs[].doc` templates with a format width of a billion, an attribute, an index or a conversion | refused | refused | `str.format` on agent text | `test_adv_5_4` |
| ADV-5.5 | an invalid policy file | the strictest limits, never the most permissive | every answer returned | a broken policy fails closed | `test_adv_5_5`; `test_policy.py` |

### 6. Receipt and verification manipulation

| Id | Attack | Expected | Actual | Significance | Test |
|---|---|---|---|---|---|
| ADV-6.1 | a quote whose source cannot be read | GAPS in v0 and v1, never PASS | GAPS | missing evidence is not success | `test_adv_6_1` |
| ADV-6.2 | the v0 receipt edited to PASS after the check | v1's outcome comes from the findings | FAIL | one assessment, two renderings | `test_adv_6_2` |
| ADV-6.3 | fields a receipt-v1 does not have (`verified`), a coverage value it does not know | reported by `receipts.problems()` | reported | the schema is closed | `test_adv_6_3` |
| ADV-6.4 | a profile leaving anchors out, on a text that is all anchors | not PASS; what was left out and how many claims of that kind the text holds | EMPTY or NOT_RUN, PARTIAL, counts | a smaller check says so | `test_adv_6_4` |
| ADV-6.5 | `--receipt v1` to change the exit code | the exit code follows the check, whatever the rendering | 1 for both | rendering is not a decision | `test_adv_6_5` |

### 7. Agent behaviour (the hook)

| Id | Claim | Expected | Actual | Test |
|---|---|---|---|---|
| ADV-7.1 | "tests passed, CI is green, the PR is merged", in prose, in a final answer | returned: anchor it | returned. **By design**: a message that is not a final answer is not held to the prose rule (NEXT №63) | `test_adv_7_1` |
| ADV-7.2 | `run:` for a command the session never ran | BROKEN | "no tool call" | `test_adv_7_2` |
| ADV-7.3 | `run:` for a command that errored | BROKEN | "every matching call returned an error" | `test_adv_7_3` |
| ADV-7.4 | a file "inspected" with a digest that is not its bytes | BROKEN | "sha256 is now …" | `test_adv_7_4` |
| ADV-7.5 | a merge GitHub does not show | BROKEN | `pr:BROKEN` | `test_adv_7_5` |
| ADV-x | the attacks above, with the person's token in the hook's environment | no token in the hook's messages or journal | none | `test_adv_x` |

## Fixed here

- **ADV-2.1** (`buddie/effects.py`): a `ci:` anchor's checks must name the commit the anchor names. GitHub's
  `commits/{ref}` accepts a branch or tag of that name; when its check runs' `head_sha` or the combined status's
  `sha` is another commit, the anchor is UNCHECKABLE. An answer that names no commit is taken as before.
- **ADV-2.5 to 2.7** (`buddie/effects.py`, `buddie/freshness.py`): a `ci:` anchor goes through
  `freshness.ci_evidence`, the same collection as freshness: the SHA resolved to its full commit (which must start
  with it), the latest check runs and the combined status fetched once for that id, page by page, each naming it,
  GitHub's `total_count` read in full. A run without `head_sha`, on another commit, a missing page, or check suites
  disagreeing on one name: UNCHECKABLE. The test fixtures of `test_effects.py` and `test_loop.py` were brought to the
  API's real shape (a resolution, `head_sha`, `filter=latest`); their assertions are unchanged.
- **ADV-5.2 to 5.10** (`buddie/patterns.py`, `buddie/mandate.py`, `buddie/config.py`, `buddie/hook.py`). The bound is
  execution, not a list: every `[mandate]` pattern (`parent`, `ask_words`, `wait_words`, `wait_not_before`,
  `wait_delay`, `refs[].pattern`) a `buddie.toml` gives is matched in a worker process of its own (`python -I`,
  explicit pipes, no buddie credentials, nothing but `re` and `json`), each call within 1 second and a hook event's
  calls together within 10; the worker's start is not counted. Past either, the worker is stopped and the check
  raises `PatternTimeout`: the gate returns the answer (`hook.failed`), the CLI exits 2. buddie's own default
  patterns are run in-process. In front of it, the static check still refuses at read time what is certainly
  exponential (a backreference, a repeat over alternatives, an unseparated repeat inside a repeat, over 512
  characters), and `refs[].doc` takes `{name}` fields only, so most bad files fail at once with the reason.

## Remaining limitations

- **What a pattern timeout lets out.** A Stop or a text tool's message goes back with the reason; as for any check
  that fails, a later attempt with a `buddie:` line saying it was not checked goes out (`hook.failed`). Events that
  only keep the journal, the summary and the launch gate go on when a check fails, as before: a bad pattern there
  costs at most the event's budget.
- **The worker's cost.** One Python process per buddie process that meets a `buddie.toml` pattern, started once
  and reused. Texts over 64 K characters are not matched (the check cannot be completed: the answer is returned).
- **A worker outliving buddie.** If buddie's own process is killed while a match runs, the worker is ended with it
  on Windows (a job object) and Linux (`PR_SET_PDEATHSIG`); on macOS it runs until its match ends or its pipe breaks.
- **Agent-writable evidence.** A repository proves what is in it (ADV-1.5, ADV-3.3), and `clean` is git's view.
- **Interim messages.** The prose rule holds final answers (ADV-7.1).
- **The trusted base and the interpreter** are outside the model ([security.md](security.md),
  [freshness.md](freshness.md)).
- **The Windows full-suite failures** are recorded for Release Hardening ([release-hardening.md](release-hardening.md)).
