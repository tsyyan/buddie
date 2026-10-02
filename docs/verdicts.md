# Verdicts

The authoritative definitions are in the module docstring of [`verbatim/check.py`](../verbatim/check.py) and, for
`NOT_A_QUOTE`, in [`verbatim/report.py`](../verbatim/report.py). This page summarizes them.

## Which link a quote is checked against

1. The citation right after the quote in the same sentence, together with adjacent citations (`”[1][2]`,
   `” ([a](u), [b](v))`).
2. Otherwise, the last link before the quote in the same sentence.
3. Otherwise, every link of the paragraph (`binding: "block"`).

Other links of the paragraph are kept in `block_urls`. A quote found only there is `UNCERTAIN` with `other_link`.
Empty `()` after a quote means the link was lost: the verdict is `NO_SOURCE`.

## Normalization (`FOUND_NORMALIZED`)

The normalizations are case; curly and straight quotes, including single vs double inside a quote; dashes and spaces
around punctuation; `…`/`...` for omitted words (found in order and close together); `[edits]`; and punctuation
between words (`note: "punctuation"`). Blanks `___` and the page's own `[A]t` brackets are also normalized. Two replies
of one speaker joined across a speech tag get `note: "speech_tag"`. Mojibake (`â€™`) in the text layer is repaired
before the search.

## Not found

| Verdict | When |
|---|---|
| `UNCERTAIN` | `doubts`: `unattributed` (the report gives no speaker), `other_language`, `thin_page` (paywall teaser, JS shell), `other_link`, `copy_only`, `abstract_only`, `unread_link` |
| `NOT_A_QUOTE` | `not_quote`: `boilerplate`, `title`, `example`; `miss` keeps the verdict the quote would have had |
| `NOT_FOUND` | none of the above; `closest.ratio` ≈ 0.95+ usually means a changed digit or word, ≈ 0.5 an invented sentence |
| `SOURCE_UNAVAILABLE` | the quote's own link has no readable snapshot: HTTP error, cookie or bot gate, almost no text, or an article URL that redirected to the home page |

## Access cascade (`--access default`)

| Method | Text from | `provenance` |
|---|---|---|
| `browser` | headless Chromium, the page's JavaScript runs | `publisher` |
| `archive` | Wayback Machine (`id_` bytes), then Common Crawl WARC records | `archive` |
| `open_access` | OpenAlex / Unpaywall copy for a DOI, else its abstract | `open_access` |
| `copy` | the same article at a syndication partner (`--copies FILE`) | `copy` |
| `relay` | r.jina.ai rendering, only with `--access all` | `relay` |

Paywalls, captchas and bot protection are never bypassed.

Environment variables: `VERBATIM_STORE` (the store), `VERBATIM_CHROMIUM`, `VERBATIM_BROWSER_CA`, `VERBATIM_CC_CRAWLS`
and `VERBATIM_EMAIL` (the contact address Unpaywall asks for).
