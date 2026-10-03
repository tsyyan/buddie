# How the numbers were measured

Each measurement (E008, E010–E012) follows the same protocol. Everything below is in the result folders, so you can
re-run the counts from the files without trusting the summary.

## 1. Freeze, then run

The rules of the `verbatim` version under test are committed before the run. A version is measured **out of sample**
only on reports it was not tuned on. When a run exposes a defect, the fix goes into the next version and is measured on
the next, unseen set. In-sample numbers are always reported as such (see the `fitted_here` field in
`results/E013-stage2-summary/recount.json`).

## 2. Seal the verdicts

The tool's verdicts for the sample are written to `verdicts_sealed.json`, and its hash is committed before anyone
labels. Labellers get `sample_blind.json`, which holds the quote, its paragraph and its links. They also get the
visible text and the raw bytes of every snapshot. They do not get the verdicts and are told not to run `verbatim` or
its search functions.

## 3. Label blind

Labels and their definitions are given word for word in each `LABELLING.md`:

| Label | Meaning |
|---|---|
| `IN_SOURCE` | the words are in the quote's own source, up to case, punctuation, quote style or marked edits |
| `AGENT_ALTERED` | the passage exists, but the quote changes it without marking (`minor` or `material`) |
| `AGENT_ABSENT` | presented as the source's words, the source is readable, and nothing like them is there |
| `TRANSLATED` | the quote is a translation of a source in another language |
| `NOT_A_QUOTE` | the quote marks do not claim these are the source's words (title, term, the agent's own example) |
| `UNVERIFIABLE` | no readable snapshot could hold the passage |

**Agent error** = `AGENT_ALTERED` + `AGENT_ABSENT`. A **false `NOT_FOUND`** is `NOT_FOUND` on an item labelled
`IN_SOURCE`, `NOT_A_QUOTE` or `TRANSLATED`.

The labellers are Claude subagents with no shared context with the agent being checked and no access to the verdicts.
In E010–E012 two labellers, A and B, label every item independently, and agreement is reported (Cohen's κ). Their
disagreements are listed and counted both ways. In E005, E006 and E008, each item was labelled once (in E008 by four
labellers on disjoint parts), so agreement was not measured there. Both labellers come from the same model family and may share blind
spots. Independent labelling by different models is one of the next steps.

## 4. Sample and controls

The sample holds every checked miss (`NOT_FOUND`, `UNCERTAIN`) and a random set of finds as controls. In E008 none of
the 40 controls was an agent error, so rates are reported over all checked quotes: finds count as correct.

## 5. Count by script

`compare.py` in each folder unseals the verdicts and joins them with the labels into `comparison.json`. E013
recomputes every set on the current version (`scripts/recount.py`, output `recount.json`). It re-reads pages only when
needed, and it counts a change only if the old search on the same bytes disagrees with the new search. Otherwise the
page itself changed. Confidence intervals are Wilson 95 %.

## 6. Pin every number

In the lab repository, every number in a report or plan carries an anchor: a file hash, a commit, or a fact a script
recomputes. CI checks these anchors. This export lists every file with its SHA-256 in `PROVENANCE.json`.
