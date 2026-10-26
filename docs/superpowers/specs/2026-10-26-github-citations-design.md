# GitHub report citations

## Intent and scope

An agent submits its ordinary Markdown report to `verify_report`. Buddie automatically detects cited quotations
and code, then checks their literal presence in a GitHub source. This does not judge the surrounding explanation,
correctness of code, or whether a change fixes a bug. No model, shell execution, new dependency, or new MCP tool.

The user chose automatic report extraction over an explicit per-quote request API and authorized implementation
and a separate PR. The implementation choices below are proposed engineering defaults.

## Approaches

1. Fetch GitHub HTML with the prose checker: small change, but UI text, whitespace normalization and mixed diff
   sides can support the wrong code. Rejected.
2. Separate verification service/tool: isolates code but asks agents to change workflow and duplicates receipts.
3. GitHub source adapter inside the existing quote check: chosen. Keep the current findings, policy and receipts;
   route GitHub citations to a strict matcher and preserve evidence locations as additional quote-row metadata.

## Source contract

- `https://github.com/OWNER/REPO/blob/FULL_SHA/path[#Lstart[-Lend]]`: UTF-8 file via the GitHub contents API at a
  full 40-character commit SHA. Mutable/abbreviated refs are gaps in v1, never silently interpreted as immutable.
- `https://github.com/OWNER/REPO/pull/N`: PR description body only, at observation time. Title, reviews, comments,
  commits and files are different sources; text found there does not support a description quotation.
- `https://github.com/OWNER/REPO/pull/N/files#diff-FILENAME_SHA256Rstart[-Rend]` (or `L`): one file and one side of
  the PR diff. Resolve PR base/head once, then obtain the immutable three-dot compare and its merge base. A file
  omitted from GitHub's bounded compare response is unavailable. Each patch must parse completely and its hunk
  counts/addition/deletion totals must agree with API metadata. Missing patches, binary files, unsupported URL
  shapes, malformed ranges and incomplete evidence give SOURCE_UNAVAILABLE (GAPS), never a negative assertion.

For diff fences, leading `+`, `-`, and space are diff syntax: each line must match its declared kind. Ordinary
code/quotation matches the addressed side, recording whether each matched line is added, deleted or context.
No inference from natural-language words such as "adds" or "fixes"; the receipt states the mechanical scope.

## Report extraction

Reuse existing source binding for prose quotations. Add inline backticks and fenced code blocks. Inline code binds
to links in its own paragraph, fences to exactly one GitHub link in the immediately preceding paragraph or the
immediately following standalone citation paragraph. Multiple possible sources remain UNCERTAIN; never pick the
one where the text happens to match. Do not inherit a source across headings or unrelated paragraphs. Code without
an identifiable GitHub source is outside this adapter's scope. Quotes citing unsupported GitHub URL shapes are gaps.

Preserve code characters, indentation, Unicode and case; normalize CRLF to LF only. Do not join across files,
hunks or discontinuous line ranges. Short inline code is included (no prose minimum). Preserve report line numbers.

## Evidence, permissions and replay

Use the existing GitHub GET and remote public-repository filter. Only fixed API path families are added. Never
fetch report-selected hosts, execute code, follow content download URLs or expose private files remotely.
`github=False` prevents new API reads. `fetch=False` prevents new citation source reads but can replay saved evidence.

Store a content-addressed canonical JSON evidence bundle containing the decoded API responses and resolved
identity; its SHA-256 names these serialized bytes, NOT raw HTTP bytes. Cache by full citation URL including fragment.
Local offline replay verifies the bundle hash and scope, and has unknown provenance. The public server disables
saved-source replay because local authenticated private evidence could exist in the same directory. A supplied GET callback has
caller_supplied provenance; collector_observed requires the existing own-collector and clean-network rules for the
whole assessment. A snapshot hash alone never establishes origin. No persistent provenance elevation.

## Results and compatibility

Reuse FOUND, NOT_FOUND, UNCERTAIN and SOURCE_UNAVAILABLE. Strict mismatches on a complete addressed source block;
ambiguity and incomplete sources flag. Preserve location, revision(s), source kind, normalization, snapshot hash,
observation time and evidence provenance in receipt-v0 quote rows; receipt-v1 evidence points to the same bundle.
Existing non-GitHub reports retain their behavior and receipt shape. Detected/skipped counts cover syntactic
extraction only, not all possible quotations, paraphrases or truth of the report.

## Validation

Offline tests for extraction/binding, strict symbol/indent/case mismatch, file/range/diff-side isolation, removed
vs added lines, multi-hunk boundaries, malformed/truncated API data, mutable refs, PR description snapshots,
private remote access, offline replay/tampering, callback provenance and CLI/MCP/v1 integration. Run the full suite.
