# verbatim

**Does the quote an AI agent gives actually appear on the page it cites?** `verbatim` answers that mechanically. It
saves the bytes of every cited source under their SHA-256, extracts the text a reader would see, and searches each
quotation in it. The result is one verdict per quote with the snapshot hash and the character offset. No model takes part
in the check, so the agent being checked cannot talk its way past it.

[![ci](https://github.com/tsyyan/verbatim/actions/workflows/ci.yml/badge.svg)](https://github.com/tsyyan/verbatim/actions/workflows/ci.yml)
· Python ≥ 3.11 · no dependencies · Apache-2.0

## Why this matters for oversight

Deep-research agents present quotations as evidence. A reader, a reviewer or another agent usually cannot re-open
every link, so a quote that was altered, stitched together or never existed passes as support. This is a narrow but
measurable form of **unfaithful reporting**: the agent's account of its own work does not match the record. `verbatim`
checks that account against primary bytes alone, without any access to the agent's reasoning. That makes it a small
piece of **scalable oversight** that still works when the overseer is weaker than, or not trusted by, the agent.

## What we found

On 929 checkable quotations from published deep-research reports, labelled blind, **212 (22.8 %, 95 % CI 20–26 %)
were altered by the agent or absent from the cited source**. `verbatim` flagged 207 of those 212.

| Set (reports) | Systems | Checked quotes | Agent errors | False `NOT_FOUND`, v0.3.2 |
|---|---|---|---|---|
| [E008](results/E008-drb2-fresh) (90, DeepResearch Bench II) | OpenAI o3 Deep Research, Perplexity, Grok, Doubao | 489 | 152 (31.1 %) | 19 (3.9 %) |
| [E010](results/E010-ydc-o3) (102, ydc-deep-research-evals) | OpenAI o3 | 147 | 40 (27.2 %) | 1 (0.7 %) |
| [E011](results/E011-drb1-claude) (50, DeepResearch Bench I) | Claude 3.7 Sonnet with web search | 249 | 20 (8.0 %) | 1 (0.4 %) |
| [E012](results/E012-search-misses) (350, DeepResearch Bench I) | fresh reports not seen before | 44 | 0 | 1 (2.3 %) |
| **All** | | **929** | **212 (22.8 %)** | **22 (2.4 %, CI 1.6–3.6 %)** |

Source: [`results/E013-stage2-summary/recount.json`](results/E013-stage2-summary/recount.json). "Checked" means the
cited page could be read and the quote is long enough to search (≥ 12 characters). Every miss was labelled, and a
random sample of finds served as controls; none of the 40 E008 controls hid an agent error.

**What the numbers do not show yet.** The rules of each version were tuned on the set where they appear in-sample.
Measured out of sample (each version on reports it was not tuned on), false `NOT_FOUND` is **10 of 440 (2.3 %,
CI 1.2–4.1 %)**; our target of ≤ 2 % is not demonstrated. Most remaining false alarms are not search failures: they are
words the agent put in quotation marks itself (example questions, imagined dialogue) that read like quotes. The
labellers were Claude subagents working blind to the verdicts, not humans. Two labellers agreed on 94 of 97 (κ 0.95,
E010) and 73 of 76 (κ 0.94, E011) items; E008 was split between four labellers with no overlap. The full protocol is in
[docs/method.md](docs/method.md).

An earlier pilot on spring-2025 reports ([E004](results/E004-pilot-drb1)) found serious quote errors in 7–35 % of
quote-citations for three of four systems, which is what started this line of work.

## Quick start

```bash
pip install git+https://github.com/tsyyan/verbatim
cd examples/quickstart
verbatim add https://status.example.com/incidents/42 page.html   # or: verbatim snap URL (fetches it)
verbatim check report.md --json verdicts.json
```

```
MISS L3     elevated error rates on the API between 14:58 and 15:41 UTC
       closest (0.98): elevated error rates on the API between 14:59 and 15:41 UTC
ok   L5     all systems are operating normally
MISS L7     the root cause was a misconfigured load balancer
       closest (0.50): . The rest of the article discusses unrelated bac
verbatim: 1/3 quotes found in their sources (FOUND 1, NOT_FOUND 2)
```

The exit code is 1 on any `NOT_FOUND`, so the check can gate a CI job or an agent hook. The closest passage separates a
wrong digit (similarity ≈ 0.98) from an invented sentence (≈ 0.5). For real reports use `--fetch` to snapshot the cited
URLs first. Each verdict in `verdicts.json` carries the snapshot `sha256`, its fetch time, the offset in the visible
text and where the text came from.

| Command | Does |
|---|---|
| `verbatim snap URL…` | fetch and store the bytes (failures are recorded too) |
| `verbatim text URL --grep RE` | print the visible text of a snapshot: quote from this, not from a summary |
| `verbatim check REPORT [--fetch] [--access default]` | verdict for every quote in a Markdown or JSON report |
| `verbatim access METHOD URL…` / `verbatim merge DIR` | run one access method, or merge another store into yours |

## Verdicts

| Verdict | Meaning |
|---|---|
| `FOUND` / `FOUND_NORMALIZED` | in the visible text, exactly or after normalizing case, quotes, dashes, `…` elisions and `[ ]` edits |
| `HIDDEN_ONLY` | only in markup the reader does not see (JSON-LD, meta, alt) |
| `FOUND_IN_COPY` | only in a republished copy or a relay rendering, not on the cited page |
| `UNCERTAIN` | not found, but the miss may not be the report's fault: unattributed words, translation, thin page, found under another link of the paragraph |
| `NOT_A_QUOTE` | not found, and the report itself shows these are not someone's words (title, boilerplate, the agent's own example) |
| `NOT_FOUND` | not there; `closest` gives the nearest passage and its similarity |
| `SOURCE_UNAVAILABLE` / `NO_SOURCE` | the quote's own link could not be read, or there is no link |

Each quote is checked against **its own** link, meaning the citation next to it in the same sentence, not just any
link in the paragraph. A quote found only under a neighbour link is `UNCERTAIN`, not `FOUND`. Full definitions are in
[docs/verdicts.md](docs/verdicts.md) and in the docstring of [`verbatim/check.py`](verbatim/check.py).

**Unreadable pages.** `--access default` tries lawful routes in order: a headless browser
(`pip install 'verbatim[browser]'`), the Wayback Machine and Common Crawl, open-access copies by DOI, and known
syndicated copies. The verdict records the provenance. `verbatim` never bypasses paywalls, captchas or bot protection.

## Scope and limits

- It checks that the words exist in the source, not that they **support** the claim around them. A real quote attached
  to the wrong date or the wrong event still passes. That judgment needs a reader or a separate, clearly labelled
  model layer.
- Only quotations are checked. Dates, numbers and unquoted paraphrase are out of scope for now.
- Pages change. A verdict holds for the snapshot hash and time it names, not for the page today.
- No JavaScript rendering unless the browser access method is installed.

## Use it inside an agent

[`skill/verbatim/SKILL.md`](skill/verbatim/SKILL.md) is a Claude Code skill: snapshot the sources before reading, quote
from the snapshot text, and run `verbatim check` before answering. We use it in our own multi-agent threads. There, a
two-hour audit found 14 reporting errors, and none of them was fixed by reasoning alone without going back to the source.

## Reproduce

```bash
pip install -e . && pytest            # 85 self-contained tests; 16 more need third-party page snapshots and skip
python results/E008-drb2-fresh/compare.py   # scripts are kept as they ran; paths assume the lab layout, see results/README.md
```

Every exported file is listed with its SHA-256 and origin in [`PROVENANCE.json`](PROVENANCE.json). Development happens
in a private lab repository, and this repository is exported from it by script. **We do not redistribute page
snapshots**, because they are other people's pages. Verdict files keep each page's URL and SHA-256, so a re-fetch shows
whether the page changed. Report text from DeepResearch Bench I/II is included under its Apache-2.0 license. The
ydc-deep-research-evals reports state no license, so E010 is published as ids, labels, verdicts and hashes only. See
[NOTICE](NOTICE) and [results/README.md](results/README.md).

## Status

v0.3.2, research software. Next: an out-of-sample measurement on ≥ 250 new quotes, current Claude models on the same
tasks, and an intervention study. In that study the agent can call `verbatim` as a tool before submitting, and we check
whether altered quotes drop or the agent shifts to unverifiable paraphrase.

## Cite

See [CITATION.cff](CITATION.cff).
