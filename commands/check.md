---
description: Check a text with buddie now (your last answer, a file, or pasted text)
argument-hint: "[file or text]"
---

Check this with buddie's `verify_report` tool (the buddie MCP server): $ARGUMENTS

- If the line above names a file, pass it as `path`. If it is text, pass it as `text`. If it is empty, pass your
  previous answer in this conversation as `text`, word for word.
- Show the receipt's `predicate.line` first, then each item of `blocking` and `gaps` on its own line.
- `FAIL`: for a quote, copy the right words from the page with `snap` and `source_text` and show the corrected
  sentence; for an anchor, show what holds instead. `GAPS`: say what could not be checked and why. `EMPTY`: say that
  the text had no quotations with links and no anchors, so nothing was verified.
- Do not rewrite anything else, and do not call a text verified unless the outcome is `PASS`.
