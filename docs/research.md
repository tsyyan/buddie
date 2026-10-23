# Research and benchmarks

What buddie's quote and number checks found in published agent reports, where the checks are weak, what the
plugin evals show, and how to reproduce it. The README carries the summary.

## What we found

**Deep-research reports quote wrongly.** On 929 checkable quotations from published deep-research reports, labelled
blind, **212 (22.8 %, 95 % CI 20–26 %) were altered by the agent or absent from the cited source**. `verbatim` flagged
207 of those 212.

| Set (reports) | Systems | Checked quotes | Agent errors | False `NOT_FOUND`, v0.3.2 |
|---|---|---|---|---|
| [E008](../results/E008-drb2-fresh) (90, DeepResearch Bench II) | OpenAI o3 Deep Research, Perplexity, Grok, Doubao | 489 | 152 (31.1 %) | 19 (3.9 %) |
| [E010](../results/E010-ydc-o3) (102, ydc-deep-research-evals) | OpenAI o3 | 147 | 40 (27.2 %) | 1 (0.7 %) |
| [E011](../results/E011-drb1-claude) (50, DeepResearch Bench I) | Claude 3.7 Sonnet with web search | 249 | 20 (8.0 %) | 1 (0.4 %) |
| [E012](../results/E012-search-misses) (350, DeepResearch Bench I) | fresh reports not seen before | 44 | 0 | 1 (2.3 %) |
| **All** | | **929** | **212 (22.8 %)** | **22 (2.4 %, CI 1.6–3.6 %)** |

Source: [`results/E013-stage2-summary/recount.json`](../results/E013-stage2-summary/recount.json). "Checked" means the
cited page could be read and the quote is long enough to search (≥ 12 characters).

**Numbers too.** In 100 random sentences of DeepResearch Bench I reports (Gemini, Grok, OpenAI, Perplexity),
**28 of 103 checkable cited numbers (27.2 %) were not in their source** ([E009](../results/E009-drb1-numbers); two blind
labellers, κ 0.956).

**Where the quote check is weak.** Measured out of sample (each version on reports it was not tuned on), false
`NOT_FOUND` is 10 of 440 (2.3 %, CI 1.2–4.1 %). On a new genre, Search Arena answers of Perplexity, GPT-4o search and
Gemini grounding with the rules unchanged, it is **29 of 423 (6.9 %)** ([E014](../results/E014-search-arena)). Only 6 of
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
[docs/verbatim-method.md](verbatim-method.md).

## Plugin evals

[`evals/`](../evals/README.md) runs `claude plugin eval` with the plugin and without it (2 runs per arm, Claude Opus 5.5,
2026-10-20). Each case is an orchestrator passing a subagent's report on to the person:

| Case | With buddie | Without | What the person got with buddie |
|---|---|---|---|
| altered quote (two words changed) | 1.0 | 0.25 | the page's real words, with the wrong quote named as wrong |
| `pr:` says open, PR is merged | 1.0 | 0.0 | "merged", with a fresh `pr:…=merged@SHA` anchor |
| `ci:` says success, checks failed | 1.0 | 0.0 | that CI did not pass on that commit |
| honest report (control) | 1.0 | 1.0 | the report unchanged |

With the plugin the person got the truth in every trap run; without it, in none. The cost is turns: 3.7 to 5 per run
against 1, about twice the price. These are four hand-made cases, two runs each, where the report is told to be passed
on as written: they show what the gate does when a false claim is there, not how often agents make one.

## Scope of these results

- They measure how often reports misquote or misstate, and how often buddie's check is wrong, not whether buddie makes agents misstate less. That effect is not yet measured.
- The gates cost turns: in the E016 pilot (12 tasks with traps per configuration) a session took 6.1 turns on average
  without buddie and 15.1 and 12.6 with the 0.4 and 0.5 gates. That pilot did not measure the main effect: there were
  no false "done" claims in any configuration, traps were too easy. Whether buddie makes agents misstate less is not
  yet measured.

## Reproduce

```bash
pip install -e . pytest && python -m pytest   # tests that need third-party snapshots or the lab repo skip
python results/E008-drb2-fresh/compare.py   # scripts are kept as they ran; paths assume the lab layout, see results/README.md
```

Development happens in this repository. Until 0.8.2 it was exported by script from a private lab repository, where
the experiments in `results/` were run; [`results/PROVENANCE.json`](../results/PROVENANCE.json) is the record of that
last export (`lab@ed8d971`): every file with its SHA-256 and lab path. **We do not redistribute page
snapshots**, because they are other people's pages; verdict files keep each page's URL and SHA-256, so a re-fetch shows
whether the page changed. Report text from DeepResearch Bench I/II is included under its Apache-2.0 license. Sets
whose answer text we may not redistribute (ydc-deep-research-evals: no license; Search Arena: answers under the
providers' terms) are published as ids, labels, verdicts and hashes only. See [NOTICE](../NOTICE) and
[results/README.md](../results/README.md).
