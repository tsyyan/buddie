# Results

Each folder contains one experiment as it was run in the lab repository. `REPORT.ru.md` is the original report, written
in Russian. This page summarizes the reports in English. The protocol is described in [../docs/verbatim-method.md](../docs/verbatim-method.md).

| Folder | Question | Answer |
|---|---|---|
| [E004-pilot-drb1](E004-pilot-drb1) | Do published deep-research reports quote words that are not in the cited source? | Pilot on DeepResearch Bench I (spring 2025; OpenAI, Perplexity, Grok, Gemini; 50 tasks). Serious quote errors in 7–35 % of quote-citations for three of the four systems. Gemini rarely quotes verbatim. |
| [E005-blind-relabel](E005-blind-relabel) | Does the E004 labelling hold when the labeller cannot see the earlier labels? | Re-labelled 58 misses blind. This found tool defects (wrong link binding, neighbour links, unreadable pages), which were fixed in v0.2. |
| [E006-blind-sample-v02](E006-blind-sample-v02) | v0.2 on a new random sample of misses | 63 items; four more fixes. |
| [E008-drb2-fresh](E008-drb2-fresh) | Fresh reports (DeepResearch Bench II: o3 Deep Research, Perplexity, Grok, Doubao; 90 reports) | 489 checked quotes, 152 agent errors (31 %). On v0.2: 55 false `NOT_FOUND`, 46 of them words the agent itself put in quotes. This led to `NOT_A_QUOTE` in v0.3. |
| [E009-drb1-numbers](E009-drb1-numbers) | Are cited numbers and dates in their sources? (100 sentences of DRB I reports, 193 numbers) | 28 of 103 checkable numbers (27.2 %) not in their source; two labellers, 187/193 agreement, κ 0.956. Module `verbatim/numbers.py`. |
| [E010-ydc-o3](E010-ydc-o3) | v0.3 out of sample (102 new o3 reports) | 147 checked quotes, 5 false `NOT_FOUND` (3.4 %), all of them the agent's own examples; two labellers, 94/97 agreement, κ 0.954. Published as ids, labels and verdicts only (no license). |
| [E011-drb1-claude](E011-drb1-claude) | v0.3.1 out of sample, on another system (50 Claude 3.7 Sonnet reports) | 249 checked quotes, 4 false `NOT_FOUND` (1.6 %), all real quotes the search missed; 20 agent errors (8 %); 73/76 agreement, κ 0.935. |
| [E012-search-misses](E012-search-misses) | v0.3.2 search fixes: do they find the E011 misses and do they hide agent errors? | 3 of the 4 E011 misses are now found, and none of 200 labelled agent errors became a find. On 350 unseen DRB I reports (44 checked quotes), 13 of 13 misses were labelled as not quotes or a translation. |
| [E013-stage2-summary](E013-stage2-summary) | All labelled sets recounted on v0.3.2 | 212 of 929 agent errors (22.8 %), 22 false `NOT_FOUND` (2.4 %), out of sample 10 of 440 (2.3 %). The ≤ 2 % false-alarm target is not demonstrated. |
| [E014-search-arena](E014-search-arena) | v0.3.2 out of sample on another genre: Search Arena answers (Perplexity, GPT-4o search, Gemini grounding) | 423 checked quotes, 29 false `NOT_FOUND` (6.9 %), 6 of them real quotes missed (1.4 %), the rest non-source text in quotation marks; 69 agent errors (16.3 %); κ 0.967. `v033.json`: the 0.3.3 in-sample recount. Published as ids, labels and verdicts only. |

## Files

| File | What |
|---|---|
| `DATASET.json` | dataset, revision and SHA-256 of every report file used |
| `sample_blind.json` | what the labellers saw: quote, paragraph, links (no verdicts) |
| `verdicts_sealed.json` | the tool's verdicts, committed before labelling |
| `labels_A.json`, `labels_B.json`, `blind_labels.json` | the labels |
| `comparison.json` | verdicts × labels, rates, Wilson 95 % intervals, agreement |
| `results.json` | full `verbatim check` output for every report (E008) |
| `compare.py`, `scripts/` | the code that produced the files, kept as it ran |

The scripts assume the lab layout (`experiments/<name>/`, and snapshot folders that are not published), so they
document the computation rather than run here as is. Comparison files recompute from the labels and sealed verdicts
alone.

## What is not here

- **Page snapshots.** They are other people's pages. Each verdict keeps the URL, fetch time and SHA-256 of the bytes it
  judged.
- **E010 and E014 answer text.** The ydc-deep-research-evals dataset states no license, and Search Arena answers are
  under the answering providers' terms. Their labels keep `key`, `label` and `own_url`, and their verdicts keep
  everything except page excerpts. URL text fragments (`#:~:text=`) are removed.
- **E001–E003, E007.** These are the first outage case study, the verifier bootstrap, an audit of our own agent threads,
  and a paywall-access study. They depend on snapshots or internal logs. Their conclusions are folded into the tool and
  into `docs/`.
- **buddie's runs on our own project** (the 4 early launches, PR/CI claims, hook logs). They read the project's private
  chat; the README reports their numbers only.
