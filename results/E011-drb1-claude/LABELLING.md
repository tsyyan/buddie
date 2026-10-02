# E011: how the blind sample is labelled

This is the brief each labeller gets, word for word (the E008 brief as in E010). Two separate Claude subagents, A and B, each label every item without seeing the other; neither has seen
verbatim's verdicts and is told where they are so it can stay away from them.

## Input (`data/blind/`)

- `sample_blind.json`: `items`, each with `key`, `system`, `task`, `line`, `quote`, `paragraph` (the report line the
  quote is on, links included), `urls` (the quote's own links as the parser saw them), `block_urls` (every link of the
  paragraph).
- `pages/index.json`: for each link (without `#fragment`), every snapshot the store holds: how it was read (`via`:
  direct fetch, `browser`, `archive` = Common Crawl or Wayback, `open_access`, `copy`), HTTP status, error, `file`.
- `pages/NNNN.txt`: visible text of a snapshot, with a two-line header.
- `snapshots/<sha256>`: the raw bytes (HTML, PDF, maybe gzip/brotli without a header). Check them when a quote seems
  absent from the text, because the text layer can drop words.

Do not open `data/results.json`, `data/stores/`, `data/sealed/`, `data/run*.log` or `data/store/index.json`, and do
not run `verbatim check` or any `locate`/`Page` function of verbatim: they contain or compute the verdicts being
measured. Search the texts yourself (`grep -F`, Python `in`, `difflib`).

## What to decide for each item

First decide which link the report gives as the quote's source: the footnote or link right after the quote in the
same sentence, else the nearest link before it in that sentence, else the paragraph's links. The URL's
`#:~:text=` fragment shows what passage the agent was looking at; use it as a hint, not as proof.

Then pick one label:

| Label | When |
|---|---|
| `IN_SOURCE` | The quoted words are in the own source: exactly, or differing only in case, punctuation, quote style, whitespace, hyphenation, or with edits marked by `…`/`...`/`[ ]`. |
| `AGENT_ALTERED` | The passage exists in the own source but the quote changes it without marking: `sub: "minor"` (a word or sign added, dropped or swapped, same meaning) or `sub: "material"` (reworded, different term, number, author or meaning). |
| `AGENT_ABSENT` | The report presents the words as the source's, the own source is readable, and nothing like them is there. If you find them in another document (another link of the paragraph, or a page you know), say so in `note`. |
| `TRANSLATED` | The source is in another language and the quote is a translation. |
| `NOT_A_QUOTE` | The quote marks do not claim these are the source's words: a title, a term, a hypothetical or example phrase, a slogan used as a name, the agent's own phrase in scare quotes. |
| `UNVERIFIABLE` | No snapshot of the own source has readable text that could hold the passage (403, CAPTCHA, cookie wall, JS shell, home page instead of the article, a page that plainly changed since: e.g. the `#:~:text=` passage is gone and the page is different). |

Judge `NOT_A_QUOTE` from the report's wording, not from whether the words were found. A quote that is both in the
source and introduced as the source's words is `IN_SOURCE`.

## Output

Write `data/blind/labels_<A or B>.json`: a list of
`{"key", "label", "sub" (AGENT_ALTERED only), "own_url", "file" (snapshot file you judged from, or null),
"evidence" (the source passage you compared, ≤ 300 chars, or the reason it is unverifiable), "note"}`, one per key,
in key order. Label every item yourself; do not open the other labeller's file.
