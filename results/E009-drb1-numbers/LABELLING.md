# E009: how the blind sample is labelled

This is the brief each labeller gets, word for word. Two separate Claude subagents, A and B, each label every item
without seeing the other; neither has seen the tool's verdicts and is told where they are so it can stay away from
them. The layout follows E010 (`experiments/E010-not-a-quote/LABELLING.md`); the unit is a number, not a quote.

## Input (`data/blind/`)

- `sample_blind.json`: `items`, one per report sentence, each with `key`, `system`, `task`, `sentence` (the report
  text, links and footnote markers included), `urls` (the sentence's cited links, footnotes already resolved to
  URLs, in the order they appear), and `numbers`: the numbers to label, each `{key, text}` (`S001.1`, `S001.2`, ...).
  A range such as `15-40%` is two numbers (`15` and `40%`).
- `pages/index.json`: for each link (without `#fragment`), every snapshot the store holds: how it was read (`via`:
  direct fetch, `browser`, `archive` = Common Crawl or Wayback, `open_access`), HTTP status, error, `file`.
- `pages/NNNN.txt`: visible text of a snapshot, with a two-line header.
- `snapshots/<sha256>`: the raw bytes (HTML, PDF). Check them when a number seems absent from the text.

Do not open `data/results.json`, `data/sealed/`, `data/store/`, `data/*.log` or `data/fetch_log.json`, and do not
import or run `verbatim.numbers` or `verbatim check`: they contain or compute the verdicts being measured. Search the
texts yourself (`grep`, Python), and read the passage around each hit: a number on the page is only support if it is
about the same thing.

## What to decide for each number

First decide which link is the number's own source: the link or footnote right after the number in the same sentence
(or table row), else the nearest one before it, else any of the sentence's links. The URL's `#:~:text=` fragment
shows what passage the agent was looking at; use it as a hint, not as proof.

Then pick one label:

| Label | When |
|---|---|
| `IN_SOURCE` | The own source states this value for the same thing: same digits, or another spelling (`3.349 million` = `3,349,000`; `28 April 2025` = `April 28, 2025`), or a rounding of a more precise source number at the precision the report writes (`29%` for `29.4%`), or within a few percent after "about"/"nearly"/"over" when the source supports that wording. |
| `WRONG_VALUE` | The own source has the passage about this thing but gives a different value, year, date or unit: `sub: "minor"` (a rounding the wording does not allow, an off-by-one year, a unit slip that keeps the meaning) or `sub: "material"` (a different number, a different year, the number belongs to another quantity, region or period). |
| `ABSENT` | The own source is readable and says nothing that supports this number for this thing. If the number is in another link of the sentence or a page you know, say so in `note`. |
| `DERIVED` | The number is the agent's own arithmetic or conversion from values that are in the own source (a sum, a difference, a currency conversion, a share computed from two counts, "doubled"). Put the source values in `evidence`. If the arithmetic is wrong, use `WRONG_VALUE`. |
| `NOT_A_CLAIM` | The sentence does not attribute this number to the source: the publication year of the cited work in an author-year reference ("Smith et al. (2019)", "([2018](link))"), a product or model name ("Windows 11", "8K editing" as a feature name, "TrackNet v2"), a section or figure number, a number inside a title the sentence quotes. |
| `UNVERIFIABLE` | No snapshot of the own source has readable text that could hold the number (403, CAPTCHA, cookie wall, JS shell, home page instead of the document, a page that plainly changed since, a PDF whose text layer is empty). |

Judge from what the source says, not from whether the digits happen to be somewhere on the page: a `2023` in the
page footer does not support "launched in 2023".

## Output

Write `data/blind/labels_<A or B>.json`: a list of
`{"key" (the number's key, e.g. "S001.2"), "label", "sub" (WRONG_VALUE only), "own_url", "file" (snapshot file you
judged from, or null), "evidence" (the source passage you compared, ≤ 300 chars, or why it is unverifiable),
"note"}`, one per number, in key order. Label every number yourself; do not open the other labeller's file.
