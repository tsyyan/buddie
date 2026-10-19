<!-- Paste into your project's AGENTS.md so Codex checks reports with buddie (MCP server `buddie`). -->
## Checking reports with buddie

Before you hand in a result that quotes sources or states facts about the repo, a PR or CI, check it with the
`verify_report` tool of the `buddie` MCP server and put its receipt line (`predicate.line`) under the report.

- Quote only from page snapshots: call `snap` with the URLs first, then copy quotes character for character from
  `source_text` (with `grep` for the passage), each with its link.
- State repo and GitHub facts as anchors the tool can check: ⚓ `path#sha256`, ⚓ `path@commit`,
  ⚓ `pr:OWNER/REPO#N=merged@SHA`, ⚓ `ci:OWNER/REPO@SHA=success`.
- Pass `repos` with the workspace path: in Codex the server does not look for a repo around its own directory.
- `FAIL`: fix each listed item, or keep it and add a line starting with `buddie:` that says what is unverified and
  why. `GAPS`: say what could not be checked. Do not drop a true claim only to get a `PASS`.
- `run:` anchors (a command and its output) are not checked in Codex; give the command and let the reader re-run it.
