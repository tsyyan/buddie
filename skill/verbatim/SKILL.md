---
name: verbatim
description: Check quotations against the bytes of their sources. Use when your result quotes web pages (quotation marks, dates or figures with a link). Snapshot the sources, quote from the snapshot text, and run verbatim check before answering.
---

# verbatim: quote only from saved bytes

A summary of a page (WebFetch and similar tools) can invent quotes and shift times. A quote in your result must exist in
a snapshot of the page, not in a summary of it. `verbatim` checks this mechanically, without a model.

## Install (once per session)

```bash
pip install -q git+https://github.com/tsyyan/verbatim
export VERBATIM_STORE=$PWD/.verbatim      # snapshot store; keep it next to your result
```

## Workflow

1. **Snapshot sources before reading.** `verbatim snap URL [URL ...]` stores the bytes under their SHA-256 with the
   fetch time. A 403 or failed fetch is recorded too. Do not quote such a page; say "source unavailable".
2. **Read and quote from the snapshot.** `verbatim text URL --grep 'regex'` shows the visible text around the matches,
   and `verbatim text URL` prints the whole text. Copy quotes from there, character for character.
3. **Bind each quote to its link.** Put the quote in `“…”`, `«…»` or `"…"`, with its source right after it in the same
   sentence (`[text](url)`, a bare URL or a footnote `[^1]`). The check uses that link, not other links in the
   paragraph. Mark omissions inside a quote with `…`.
4. **Check before answering.**
   ```bash
   verbatim check REPORT.md --fetch --json REPORT.verbatim.json
   ```
   The exit code is 1 on any `NOT_FOUND`. For each `MISS`, either copy the quote from the `closest` line (similarity
   ≥ 0.9 usually means a wrong digit or word), or drop the quotation marks and mark the sentence as a paraphrase.
   Review `miss?` lines too: they mark an unattributed phrase, a translation or an empty page. Do not leave `N/A`
   (source unavailable) or `NOSRC` (no link) unmentioned. For paywalled or JavaScript pages, retry with
   `--access default`.
5. **Report it.** Give one summary line, for example `verbatim: 12/12 quotes found in snapshots`, plus the path to the
   JSON. Each verdict there carries the snapshot SHA-256 and the quote's offset. List anything that was not found.

## What verbatim does not do

- It does not check whether a found passage **supports** the claim around it. A real quote attached to the wrong
  time or event passes. That needs a reader. When it matters, use two independent readers that share no context with
  the author and report their agreement.
- It does not check dates, time zones, unquoted paraphrase, or quotes shorter than 12 characters.
- A verdict holds for the snapshot hash and time it names, not for the page today.
