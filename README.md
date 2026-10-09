# buddie

**Receipts for agent work.** In a multi-agent setup an executor reports to an orchestrator, and the orchestrator
reports to a human. Every hand-off restates claims such as "the source says X", "tests passed" or "PR merged", and a
wrong claim travels on. `buddie` checks those claims at the hand-off against primary evidence: the bytes of the cited
page, the repository, the GitHub API and the session transcript. No model takes part in the check, so the agent being
checked cannot talk its way past it. Every check ends in a receipt that anyone can re-run.

[![ci](https://github.com/tsyyan/buddie/actions/workflows/ci.yml/badge.svg)](https://github.com/tsyyan/buddie/actions/workflows/ci.yml)
· Python ≥ 3.11 · no dependencies · Apache-2.0 · Claude Code plugin, MCP server and CLI

> This repository was called `verbatim` until October 2026. `verbatim` is now buddie's quote module (the `verbatim/`
> package here); old links redirect.

## Why this matters for oversight

An agent's account of its own work is easy to accept and expensive to re-check. A quote that was altered, a test run
that never happened or a PR described as merged while it is still open all pass as evidence when the reader cannot
re-open every source. This is a narrow but measurable form of **unfaithful reporting**. buddie checks the account
against records the agent did not write, without access to its reasoning. That makes it a small piece of **scalable
oversight** that still works when the overseer is weaker than, or not trusted by, the agent.

## What it checks

| Claim in a report | Checked against | Bad outcome |
|---|---|---|
| A quotation with a link | the visible text of a SHA-256 snapshot of **that** link (`verbatim`) | `NOT_FOUND`, with the closest passage |
| A repo anchor `⚓ path#sha256`, `⚓ path@commit` | the file's current bytes, or the file at that commit | `BROKEN` |
| "Merged", "CI green": `⚓ pr:OWNER/REPO#N=merged@SHA`, `⚓ ci:OWNER/REPO@SHA=success` | the GitHub API: PR state and merge commit, all check runs and statuses on the commit | `BROKEN` |
| "I ran it and got this": `⚓ run:CMD => OUTPUT` | the Claude Code session transcript: a tool call with CMD and OUTPUT in **its result** | `BROKEN`, also when the output was typed by the agent (`echo "41 passed"`) |
| "Step N is done", "the user agreed", "next step is in the accepted plan" (opt-in, `buddie.toml`) | the task queue at a commit, the accepted-plans list, the user's own messages | `BROKEN` |
| A number or date in a sentence with a link | the visible text of the snapshot of that link (`verbatim.numbers`) | `NOT_FOUND`: a gap by default, a failure with `--numbers fail` |

The executor writes the anchors. Lines that state work in prose without an anchor ("merged", "CI is green", "tests
passed", "41 passed") are listed in the receipt (`prose_work`); in a final answer the hook returns them with ready
anchors (PRs named in the text or tool output, the run that printed the count), and a `buddie:` disclosure does not
let them through (0.7.1). A negated claim ("not merged yet") is not one.

## Quick start

```bash
pip install git+https://github.com/tsyyan/buddie
cd examples/quickstart
verbatim add https://status.example.com/incidents/42 page.html   # or let buddie fetch the page itself
buddie verify report.md --no-fetch
```

```
BLOCK quote L3.1 not found in https://status.example.com/incidents/42: “elevated error rates on the API between 14:58 and 15:41 UTC” (closest 0.98: “elevated error rates on the API between 14:59 and 15:41 UTC”)
BLOCK quote L7.1 not found in https://status.example.com/incidents/42: “the root cause was a misconfigured load balancer” (closest 0.50: “. The rest of the article discusses unrelated bac”)
buddie FAIL: quotes 1/3 found, 2 not found
```

A claim about work, checked against the session transcript ([`examples/work`](examples/work)):

```bash
cd examples/work
buddie verify report.md --transcript session.jsonl --no-github
```

```
BLOCK anchor line 3 ⚓ run:pytest -q => 41 passed: output has no '41 passed'; it ends: ….......................................... 1 failed, 40 passed in 3.1s
buddie FAIL: effects 0/1 hold, 1 broken
```

The exit code is 1 on `FAIL`, so the check can gate a CI job, a hook or a hand-off. A wrong digit shows up as a close
passage (similarity ≈ 0.98), an invented sentence as a distant one (≈ 0.5).

### In Claude Code

```
/plugin marketplace add tsyyan/buddie
/plugin install buddie@buddie
```

The plugin brings three things:

- **a hook** (`hooks/hooks.json`) on `PreToolUse` for messages that leave the session (`SendMessage`)
  and on `Stop`; [`examples/hooks/projects.json`](examples/hooks/projects.json) adds matchers for other reply tools.
  On `FAIL` it returns the report to the model with the reasons, before anyone reads it. Since 0.6 it
  also counts live subagents (`SubagentStart`/`SubagentStop`); when none is left, the orchestrator is asked once for
  a summary built by code and a choice card for the next steps, and the person's pick (`AskUserQuestion`) goes to the
  journal, where the anchor `choice:<id>=<step>` is checked;
- **an MCP server** (stdio, no SDK): `verify_report`, `snap`, `source_text`, `summary`;
- **skills**: [`skills/buddie`](skills/buddie/SKILL.md) for executors and orchestrators,
  [`skills/verbatim`](skills/verbatim/SKILL.md) for quoting from snapshots.

The hook runs through `hooks/run.sh`, which starts the first of `python3`, `python` and `py -3` that is Python 3.11+,
so it works on Linux, macOS and Windows (Claude Code runs hooks there in Git Bash).

Without Claude Code: `python3 run.py verify REPORT.md --repo .` from a clone works without installing anything.

### Levels and the intro mode

`buddie init` writes `buddie.toml` in the repo with the default level of each class of claims and turns the intro
mode on. Each class is `block` (the text goes back to the model), `warn` (the text leaves; you see what the gate would
have said) or `off`:

| Class | What | Default |
|---|---|---|
| `anchors` | a broken anchor: `path@commit`, `path#sha256`, `pr:`, `ci:`, `run:` | `block` |
| `quotes` | a quote not on its source | `block` |
| `final` | a final answer with no anchor, or a count line without one | `block` |
| `prose` | work claimed in prose ("merged", "tests passed") with no anchor on the line | `warn` |
| `numbers` | a number of a cited sentence not in its source | `warn` |
| `work` | a claim about the work queue that does not hold (`[mandate]`) | `block` |
| `summary` | return a `Stop` once for the summary of the subagents' results | `off` |
| `promises` | return a `Stop` for a promise whose condition holds | `off` |

```toml
[gates]
prose = "block"

[intro]
finals = 20
```

In the intro mode nothing is returned: each would-be return is a warning that says what it would have returned. It
ends by itself after `finals` final answers with no false return reported; `buddie intro --false` reports one and
restarts the count, `buddie intro` shows where it stands, `buddie enforce` ends it now. Without `buddie.toml` the
defaults apply and there is no intro.

### The loop

The hook also learns from its own returns; none of it is written by the model:

- **How the gate was passed.** A return logs `reasons`; the next attempt of the same tool in the session logs `gate`:
  per flagged line `proved`, `removed` or `kept`, and the way through (`proof`, `removal`, `mixed`, `disclosure`,
  `returned`).
- **Lessons at start.** On `SessionStart` the hook prints a summary of past sessions' journal: how many messages came
  back, for what, and the shape of a line that passes (at most ten lines).
- **Ready anchors.** A return offers `pr:`, `ci:` and `run:` anchors that already hold (checked now), to copy onto the
  line instead of rewording it.
- **Measure.** `buddie journal measure --sessions 10`: the share of sessions whose first checked message passed, and
  how returns were passed (proof vs removal).
- **Context gate.** Past `BUDDIE_CONTEXT_LIMIT` tokens of context a non-final reply is returned with a reminder to hand
  the result over; final answers, hand-offs to another session and `Stop` are never held.

## Receipt v0

Each check produces an [in-toto Statement](https://github.com/in-toto/attestation): the subject is the SHA-256 of the
report text; the predicate (`predicateType: https://github.com/tsyyan/buddie#receipt-v0`) lists the verdict of every
quote with the snapshot SHA-256 and offset, the status of every anchor, and the outcome:

| Outcome | When | What the receiver does |
|---|---|---|
| `FAIL` | a quote `NOT_FOUND` in its readable source, or an anchor or work claim `BROKEN` | does not pass it on as is: fix it, or add a line starting with `buddie:` that discloses what is unconfirmed; a broken `pr:`/`ci:`/`run:` anchor must be corrected or removed |
| `GAPS` | something could not be checked: source unavailable, quote without a link, anchor in another repo, GitHub offline | passes it on, naming what was not checked |
| `PASS` | all quotes found, all anchors hold | passes it on with the receipt line |
| `EMPTY` | nothing to check | knows that no check took place |

`ci:` and `run:` receipts carry a note: an anchor shows what happened (a PR in that state, checks on that commit, a
command and its output), not that the code is correct. A green CI on weak tests stays weak.

## What we found

**Deep-research reports quote wrongly.** On 929 checkable quotations from published deep-research reports, labelled
blind, **212 (22.8 %, 95 % CI 20–26 %) were altered by the agent or absent from the cited source**. `verbatim` flagged
207 of those 212.

| Set (reports) | Systems | Checked quotes | Agent errors | False `NOT_FOUND`, v0.3.2 |
|---|---|---|---|---|
| [E008](results/E008-drb2-fresh) (90, DeepResearch Bench II) | OpenAI o3 Deep Research, Perplexity, Grok, Doubao | 489 | 152 (31.1 %) | 19 (3.9 %) |
| [E010](results/E010-ydc-o3) (102, ydc-deep-research-evals) | OpenAI o3 | 147 | 40 (27.2 %) | 1 (0.7 %) |
| [E011](results/E011-drb1-claude) (50, DeepResearch Bench I) | Claude 3.7 Sonnet with web search | 249 | 20 (8.0 %) | 1 (0.4 %) |
| [E012](results/E012-search-misses) (350, DeepResearch Bench I) | fresh reports not seen before | 44 | 0 | 1 (2.3 %) |
| **All** | | **929** | **212 (22.8 %)** | **22 (2.4 %, CI 1.6–3.6 %)** |

Source: [`results/E013-stage2-summary/recount.json`](results/E013-stage2-summary/recount.json). "Checked" means the
cited page could be read and the quote is long enough to search (≥ 12 characters).

**Numbers too.** In 100 random sentences of DeepResearch Bench I reports (Gemini, Grok, OpenAI, Perplexity),
**28 of 103 checkable cited numbers (27.2 %) were not in their source** ([E009](results/E009-drb1-numbers); two blind
labellers, κ 0.956).

**Where the quote check is weak.** Measured out of sample (each version on reports it was not tuned on), false
`NOT_FOUND` is 10 of 440 (2.3 %, CI 1.2–4.1 %). On a new genre, Search Arena answers of Perplexity, GPT-4o search and
Gemini grounding with the rules unchanged, it is **29 of 423 (6.9 %)** ([E014](results/E014-search-arena)). Only 6 of
the 29 (1.4 %) are real quotations the search missed; the rest are words the agent itself put in quotation marks
(role-play lines, satire, example prompts). Telling "is this a quote" from the report text alone does not transfer
across genres; our ≤ 2 % target is not demonstrated for arbitrary answers. The same set had 69 agent errors (16.3 %).

**On our own agents.** We use buddie in a Claude-based multi-agent project (Claude Code threads, an orchestrator,
GitHub Actions). There it found 4 automatic task launches that the orchestrator announced before the parent change had
merged, and the launch rule was changed to start only from the post-merge record. All 8 claims about PRs and CI in
earlier thread reports held, and 3 of 3 deliberately false anchors were caught in a live run. Before buddie, a two-hour
audit of the same threads found 14 reporting errors, and none was fixed by reasoning without going back to the source.
These runs use the project's private chat, so their raw data is not published; the numbers are reported as observed.

The labellers were Claude subagents working blind to the verdicts, not humans. Verdicts were committed before labelling
and rules frozen by commit before each out-of-sample run. The protocol is in
[docs/verbatim-method.md](docs/verbatim-method.md).

## The quote module: verbatim

`verbatim` saves the bytes of every cited source under their SHA-256, extracts the text a reader would see, and
searches each quotation in it. Each quote is checked against **its own** link, the citation next to it in the same
sentence, not just any link in the paragraph.

| Command | Does |
|---|---|
| `verbatim snap URL…` | fetch and store the bytes (failures are recorded too) |
| `verbatim text URL --grep RE` | print the visible text of a snapshot: quote from this, not from a summary |
| `verbatim check REPORT [--fetch] [--access default]` | verdict for every quote in a Markdown or JSON report |
| `verbatim access METHOD URL…` / `verbatim merge DIR` | run one access method, or merge another store into yours |

Verdicts: `FOUND` / `FOUND_NORMALIZED`, `HIDDEN_ONLY` (only in markup the reader does not see), `FOUND_IN_COPY`,
`UNCERTAIN`, `NOT_A_QUOTE`, `NOT_FOUND`, `SOURCE_UNAVAILABLE` / `NO_SOURCE`; see
[docs/verbatim-verdicts.md](docs/verbatim-verdicts.md). `--access default` tries lawful routes for unreadable pages in
order: a headless browser (`pip install 'buddie[browser]'`), the Wayback Machine and Common Crawl, open-access copies
by DOI, known syndicated copies. `verbatim` never bypasses paywalls, captchas or bot protection.

## Configuration

| Variable | Default | Effect |
|---|---|---|
| `VERBATIM_STORE` | `./.verbatim` | snapshot store |
| `BUDDIE_FETCH` | on | `0`: the hook uses stored snapshots only |
| `BUDDIE_GITHUB` | on | `0`: no GitHub calls, `pr:`/`ci:` become `UNCHECKABLE` |
| `BUDDIE_GITHUB_TOKEN`, `GITHUB_TOKEN` | none | token for the GitHub API (public repos work without one, within rate limits) |
| `BUDDIE_REPOS` | git repos around the working directory | `dir:dir` repos for anchors |
| `BUDDIE_FINAL` | `final_mark` in `[mandate]` of `buddie.toml`, else none | regex marking a final answer that must carry anchors at any event; with none, the last message at `Stop` is the final answer; empty turns the rule off |
| `BUDDIE_LOG` | `~/.cache/buddie/hook.jsonl` | hook run log; `0` turns it off |
| `BUDDIE_SHARED_LOG` | `/mnt/project-files/buddie/hook`, only if that folder exists | second log, one file per session; `0` turns it off |
| `BUDDIE_STORES` | none | `dir:dir` extra snapshot stores the hook reads with the session's own |
| `BUDDIE_GATES` | `[gates]` of `buddie.toml` | `class=level,...` overrides the levels above |
| `BUDDIE_INTRO` | `~/.cache/buddie/intro.json` | the intro mode's count per `buddie.toml`; `0` keeps none |
| `BUDDIE_NUMBERS` | from the `numbers` level | `gap`, `fail` or `off`: how the receipt judges a number missing from its source |
| `BUDDIE_JOURNAL_TEXT` | `[journal] text` of `buddie.toml`, else off | `1`: the journal also keeps promise sentences, choice and decision cards as text |
| `BUDDIE_LESSONS` | on | `0`: no lessons at `SessionStart` |
| `BUDDIE_CONTEXT_LIMIT` | `200000` | context tokens past which a non-final reply is returned; `0` turns it off |

### What leaves your machine

- **Cited pages.** To check a quote the hook downloads the page it cites (`BUDDIE_FETCH=0`: stored snapshots only).
  Snapshots go to `VERBATIM_STORE`. Only `--access default` in the CLI or MCP server also asks archive.org, Common
  Crawl and open-access copies by DOI.
- **GitHub API.** `pr:` and `ci:` anchors call `api.github.com`, with `BUDDIE_GITHUB_TOKEN` or `GITHUB_TOKEN` if set
  (`BUDDIE_GITHUB=0`: no calls).
- Nothing else: no telemetry, no model calls. The full list of what is read, sent and kept is in
  [PRIVACY.md](PRIVACY.md).

### The transcript and the journal

**The transcript.** The hook reads the current session's transcript (`transcript_path`, and its subagents' files next
to it) because a claim about a command can only be checked against what the session actually ran:
`⚓ run:pytest -q => 41 passed` holds only if the transcript shows that call with that output. It also takes the
final answer at `Stop`, the token count for the context gate, snapshot stores the session named, and the commands
behind ready anchors from there. It reads the file in place; nothing from it is copied into the journal or sent
anywhere. No other session, no memory, no chat history is read. There is no switch for this reading yet: without
the transcript the hook has no final answer to check at `Stop` and no way to tell a real `run:` from an invented one.

**The journal.** Each check appends one line to `BUDDIE_LOG` (`~/.cache/buddie/hook.jsonl`): time, session id, tool,
outcome, counts of verdicts, exit code and the SHA-256 of the checked text. It never holds the text. Promise lines
(«launch №N after PR #M») keep the row, the condition and the sentence's SHA-256; choice lines (the person's pick on a
summary card or an `ask_decision` card) keep hashes of the picked steps and the numbers of a typed answer, and a
decision card line keeps its options' label hashes and queue numbers, which is enough for `choice:<id>=<step>` to be
checked. `[journal] text = true` in `buddie.toml` (or `BUDDIE_JOURNAL_TEXT=1`) also keeps
those sentences and answers. `BUDDIE_LOG=0` turns the journal off; lessons at `SessionStart` then have nothing to sum.

## Scope and limits

- It checks that words exist in the source, not that they **support** the claim around them. A real quote attached to
  the wrong date or event still passes.
- Unquoted paraphrase is not checked. Numbers are checked only in a sentence with a link, and a missing one is a gap by
  default (out of sample 6 of 139 checkable numbers were false `NOT_FOUND`).
- Pages change: a verdict holds for the snapshot hash and time it names. `pr:` and `ci:` judge the state now; write
  `merged@SHA` and `ci:` on a SHA for history.
- `run:` trusts the transcript, which the harness writes on the same machine as the agent. Its format (Claude Code
  jsonl) is undocumented; other agents are not supported. A command that prints a prepared file passes: the anchor says
  "the command answered this", not "the test passed".
- Work-claim and final-answer rules match Russian and English phrasing. By default the final answer is the last
  message at `Stop`; set `BUDDIE_FINAL` or `final_mark` to mark it in replies sent earlier.
- The gates cost turns: in the E016 pilot (12 tasks with traps per configuration) a session took 6.1 turns on average
  without buddie and 15.1 and 12.6 with the 0.4 and 0.5 gates. That pilot did not measure the main effect: there were
  no false "done" claims in any configuration, traps were too easy. Whether buddie makes agents misstate less is not
  yet measured.

## Reproduce

```bash
pip install -e . pytest && pytest      # 233 self-contained tests; 28 more need third-party snapshots or the lab repo and skip
python results/E008-drb2-fresh/compare.py   # scripts are kept as they ran; paths assume the lab layout, see results/README.md
```

Every exported file is listed with its SHA-256 and origin in [`PROVENANCE.json`](PROVENANCE.json). Development happens
in a private lab repository, and this repository is exported from it by script. **We do not redistribute page
snapshots**, because they are other people's pages; verdict files keep each page's URL and SHA-256, so a re-fetch shows
whether the page changed. Report text from DeepResearch Bench I/II is included under its Apache-2.0 license. Sets
whose answer text we may not redistribute (ydc-deep-research-evals: no license; Search Arena: answers under the
providers' terms) are published as ids, labels, verdicts and hashes only. See [NOTICE](NOTICE) and
[results/README.md](results/README.md).

## Status

buddie 0.8.2 with verbatim 0.3.7, research preview: it checks claims about quotes, numbers, PRs, CI and runs
against primary data; its effect on agent behaviour is still being measured. Next: current Claude models with web search and as coding
sub-agents, measured on how often their reports misstate sources, tests or merges; and an intervention study, where the
agent runs buddie before it reports and we check whether false claims drop or the agent shifts to unverifiable wording.

## Cite

See [CITATION.cff](CITATION.cff).
