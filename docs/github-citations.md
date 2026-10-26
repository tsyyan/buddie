# GitHub citations in ordinary reports

Pass the whole Markdown report to `buddie verify` or the existing MCP `verify_report` tool. Buddie extracts literal
quotations, inline code and fenced code linked to GitHub, resolves the cited source, and applies strict matching.
No per-quote JSON or special anchors are required. This is part of the `sources` module's `quote` check.

## Write a report

A file citation must name a full commit SHA. For example, this excerpt addresses the historical source at that
revision (the SHA below is an actual repository revision; the examples do not describe the installed release):

```markdown
The file declares `class Fact(str, Enum):` ([source](https://github.com/tsyyan/buddie/blob/0bc048e7439ac283409fdfd05f763a506a95888a/buddie/core.py)).
```

For a code block, put one source in the paragraph immediately before it, or a standalone citation immediately
after it. The block quotes whole lines, so preserve indentation. The notation below uses placeholders:

````markdown
[Source](https://github.com/OWNER/REPO/blob/FULL_COMMIT_SHA/src/auth.py#L10-L11)

```python
if user.is_admin:
    allow()
```
````

The paragraph can also introduce a normal quotation, such as `The PR says “Literal description text.” ([PR](URL)).`
Short GitHub quotations and inline code are included, even below the prose checker's usual minimum length.
Text in link labels, unlinked code examples, headings and distant paragraphs do not become code citations.
Extraction is a documented Markdown subset, not a complete CommonMark parser: nested fenced list items,
indented code blocks and arbitrary HTML are outside its scope. Always inspect the extracted quote rows.

## Supported source addresses

| Source | URL | Meaning |
|---|---|---|
| File | `/OWNER/REPO/blob/FULL_SHA/path` | UTF-8 file at a 40-character commit SHA |
| File lines | Same, with `#L10` or `#L10-L12` | Only the specified lines |
| PR description | `/OWNER/REPO/pull/7` | Description body observed during this check |
| PR diff | `/OWNER/REPO/pull/7/files#diff-HASHR10-R12` | One file, new/right side, specified lines |
| PR diff, old side | Same, ending `L10-L12` | One file, old/left side |

Use canonical HTTPS links on `github.com`. `HASH` is GitHub's SHA-256 of the UTF-8 filename, the value used in its
diff links; copy a line permalink from Files changed. A bare PR URL refers to its description, **not** every file,
comment, review or commit. `/files` without a file/line fragment is ambiguous. Branch names, abbreviated SHAs,
raw/patch/commit/compare URLs, PR comments and GitHub Enterprise URLs are currently unsupported and give GAPS when
cited as sources. Buddie never falls back to searching a GitHub UI page for a match.

For PR diffs Buddie observes base/head SHAs, then reads the immutable three-dot compare between them and records
its merge base. It verifies each selected patch's hunk lengths and addition/deletion totals. Missing/binary/large
patches, files omitted from GitHub's compare response (which can be bounded), and ranges with unobserved lines give
SOURCE_UNAVAILABLE. It never joins text across separate files or hunks. Renamed files use the current filename hash;
the old-side text and numbers come from the patch, not from the head file.

## Strict matching and diff semantics

Only CRLF → LF is normalized. Case, punctuation, Unicode forms, tabs, spaces and indentation remain significant.
Inline code and prose quotes look for a literal substring in the addressed scope. Fenced code must match whole
lines including indentation. Neither ellipses nor editorial insertions stand for omitted text in this mode.

A `diff` fence additionally checks the leading patch markers: `+` is added, `-` is deleted and a space is context.
Do not include `@@` headers or file headers in the quoted fence. For example:

````markdown
[Deleted line](https://github.com/OWNER/REPO/pull/7/files#diff-FILENAME_HASHL20)

```diff
-old = True
```
````

Changing that `-` to `+` cannot pass against a deleted line. Ordinary code from a right-side link may be added **or
context**; the receipt records the matched kinds. Buddie does not parse natural-language verbs such as "adds" or
"fixes" to infer a patch kind. Use a diff fence when that distinction is part of the literal assertion.

Multiple bound sources produce UNCERTAIN, even if one happens to contain the code. Buddie does not guess which
source the author intended. A complete addressed source without the literal text produces NOT_FOUND and blocks;
an incomplete or unavailable source flags a gap instead.

## Receipt and evidence

The existing outcomes and quote verdicts are retained. Each GitHub quote row in receipt-v0 adds `github` metadata:
source kind, repository, file path, commit or base/head/merge-base identities, line scope, actual match location,
matched kinds, normalization and whether evidence was collected live or replayed. The regular `sha256` and
`fetched_at` identify the evidence bundle and its observation time. Receipt-v1 uses the same finding and includes
an evidence reference to that bundle; look at the bundle for the full resolved scope.

The bundle is canonical JSON containing the API responses and resolved citation identity. Its hash is **not** a
hash of raw HTTP response bytes. A PR description is mutable independently of commits: its bundle/time identify
what was checked. A PR diff is tied to the pair observed during the check, not to future updates to the PR.

A live response can be `collector_observed` only under Buddie's existing own-collector, own-store and clean-network
rules. A custom callback is `caller_supplied`. Replayed snapshots have `unknown` provenance, regardless of what
their index says. A hash proves byte identity, not publisher identity, authorship, correctness or authenticity of
the receipt. As before, a caller who can replace the checker itself controls its claims.

## Run and replay

```bash
buddie verify report.md --numbers off --json receipt.json
buddie verify report.md --no-fetch --no-github --numbers off --json replay.json
```

Locally, the second command can recheck saved GitHub bundles for the exact citation URLs, including fragments. It verifies
their hashes and source scopes. No saved bundle means a gap. `--no-fetch` prevents new citation-source reads;
`--no-github` prevents citation API collection and also disables the existing PR/CI anchor API lookups. As before,
`--no-fetch` alone does not disable PR/CI state anchors. MCP equivalents are `fetch: false` and `github: false`.
A fresh online citation check reads current API evidence rather than silently reusing a stored PR description.

The remote MCP server requires live GitHub collection for these citations; it does not replay stored GitHub bundles,
because a shared directory could also contain private evidence saved by a local authenticated client. With `fetch:
false` or `github: false`, remote GitHub citations are gaps. It checks repository publicity before reading contents,
PR descriptions or compares. Only fixed API endpoint families are allowed; arbitrary API requests, token forwarding
to report URLs, local files, diagnostic permissions and command execution are not added. Saved public snapshots
remain in the server's existing shared store. Local authenticated API access may read private repositories:
protect the local snapshot directory accordingly.

## Interpret coverage narrowly

A receipt counts syntactically detected citations. It cannot prove all quotations or claims in an arbitrary report
were found. PASS means the checked citations matched their addressed sources; it does not establish that the
report is true, the explanation follows from the code, tests passed, or a change fixes a bug. Semantic claims,
paraphrases, and unsupported Markdown forms require separate review. Existing `pr:`/`ci:` status anchors retain
their separate meaning.
