---
name: verbatim
description: Check quotations against the bytes of their sources. Use when your result quotes web pages (quotation marks, dates or figures with a link). Snapshot the sources with buddie's snap tool, quote from source_text, and check the answer with verify_report before answering.
---

# verbatim: quote only from saved bytes

A summary of a page (WebFetch and similar tools) can invent quotes and shift times. A quote in your result must exist in
a snapshot of the page, not in a summary of it. `verbatim`, buddie's quote module, checks this mechanically, without a
model.

## Tools

With the buddie plugin nothing needs installing: its MCP server has the three tools this skill uses, `snap`,
`source_text` and `verify_report`.

Without the plugin, the same steps run from a shell after `pip install buddie==2.0.3` (a pinned release from PyPI):
`buddie-verbatim snap URL`, `buddie-verbatim text URL --grep 'regex'` and `buddie-verbatim check REPORT.md --fetch`.

## Workflow

1. **Snapshot sources before reading.** Call `snap` with the URLs. It stores the bytes under their SHA-256 with the
   fetch time. A 403 or a failed fetch is recorded too. Do not quote such a page; say "source unavailable".
2. **Read and quote from the snapshot.** `source_text` with `grep` shows the visible text around the matches, and
   without `grep` the whole text. Copy quotes from there, character for character.
3. **Bind each quote to its link.** Put the quote in `“…”`, `«…»` or `"…"`, with its source right after it in the same
   sentence (`[text](url)`, a bare URL or a footnote `[^1]`). The check uses that link, not other links in the
   paragraph. Mark omissions inside a quote with `…`.
4. **Check before answering.** Call `verify_report` with your answer as `text`. `FAIL` means a quote is not on its
   page. For each one, copy the quote from the `closest` passage the receipt gives (similarity ≥ 0.9 usually means a
   wrong digit or word), or drop the quotation marks and mark the sentence as a paraphrase. Do not leave a source
   that could not be read, or a quote with no link, unmentioned.
5. **Report it.** Put the receipt's `predicate.line` under the answer, copied from the tool's result, for example
   `buddie PASS: quotes 12/12 found`. Never write that line yourself. List anything that was not found.

## What verbatim does not do

- It does not check whether a found passage **supports** the claim around it. A real quote attached to the wrong
  time or event passes. That needs a reader. When it matters, use two independent readers that share no context with
  the author and report their agreement.
- It does not check dates, time zones, unquoted paraphrase, or quotes shorter than 12 characters.
- A verdict holds for the snapshot hash and time it names, not for the page today.
