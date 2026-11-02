# buddie

buddie checks claims in a text by code, without a model. Its MCP server `buddie` has the tools.

- **Before you hand in an answer that quotes web pages or states facts about a repository, a PR or CI**, call
  `verify_report` with the whole text. `FAIL` lists what does not hold: fix each item from what it says the page
  reads, or keep it and add a line starting with `buddie:` that says what is unverified and why. `GAPS` means
  something could not be checked: say what. `EMPTY` means nothing was checkable; it is not a pass.
- **Quote only from a snapshot**: `snap` the URL, then copy the words from `source_text` (with `grep`), and link the
  same URL right after the quote in the same sentence. A text whose quotes are already written goes straight to
  `verify_report`: it fetches the linked pages itself.
- **State repo, PR and CI facts as anchors**: the sign ⚓ and then, in backticks, `pr:OWNER/REPO#N=merged@SHA`,
  `ci:OWNER/REPO@SHA=success`, `path@commit`. Copy SHAs from tool output, not from memory.
- **Before you give the person commands for their own machine**, call `environment_snapshot` for the categories
  the commands depend on (`system.os`, `system.shell`, `software.python`, ...). It reads only what the person
  granted (`buddie snapshot --grant-baseline`); a denied category is not to be guessed.
- Put the receipt's summary line under the answer, copied from the tool's result. Never write one yourself.

PASS means the quotes and anchors that were checked are where the text says, not that its conclusions are right.
In Gemini CLI buddie is advice: nothing holds an answer back automatically.
