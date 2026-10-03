# Changelog

## buddie 0.3.0 (2026-10-03), first public release

The repository `tsyyan/verbatim` became `tsyyan/buddie`; verbatim is buddie's quote module.

- Effect anchors `pr:`, `ci:` (GitHub API) and `run:` (session transcript); output the agent typed itself does not count.
- Work and mandate claims against a task queue (`buddie.toml`, opt-in).
- Repo anchors `path#sha256`, `path@commit`, `fact=value`.
- Receipt v0 (in-toto Statement), CLI, MCP server over stdio, Claude Code hook, plugin and marketplace.
- Results E009 (numbers) and E014 (Search Arena) added.

## verbatim

Each version was measured on reports it was not tuned on. Experiment folders are in `results/`.

## 0.3.3 (2026-10-02)

- Footnote markers inside quotation marks (`[1](url)`, `[2]`) are dropped before search.
- A truncated response body (`IncompleteRead`) is a failed fetch, not a crash of `check`.
- E014 in-sample recount: false `NOT_FOUND` 26 of 423 instead of 29; no agent error became a find.

## 0.3.2 (2026-10-02)

- Two replies of one speaker joined across the page's speech tag are found (`note: "speech_tag"`).
- The page's `[A]t` brackets and `___` blanks are normalized. Mojibake in the text layer is repaired before search.
- E012: none of 200 labelled agent errors became a find.

## 0.3.1

- New hints that mark an example before the quote marks: `like “`, `something like: “`, `might include: “`,
  `questions (“`. E011: 2 hits in 249 checked quotes, both correct.

## 0.3.0

- `NOT_A_QUOTE` verdict for words the report itself shows are not a quotation (`boilerplate`, `title`, `example`).
- Punctuation between words is ignored at the last normalization level.
- E010: false `NOT_FOUND` 5 of 147 (3.4 %).

## 0.2

- A quote is checked against its own link. A find under another link of the paragraph is `UNCERTAIN`.
- `UNCERTAIN` doubts and the access cascade (`--access`: browser, Wayback / Common Crawl, open access, copies).
- PDF via `pdftotext`, compressed bodies, cookie and bot gates are reported as `SOURCE_UNAVAILABLE`.

## 0.1

- `snap`, `text`, `check`: the content-addressed store, the visible-text layer and the quote search.
