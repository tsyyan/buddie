<!-- mcp-name: io.github.tsyyan/buddie -->

# buddie

Verify the claim. Know the context. AI agent reliability toolkit.

buddie checks agent reports against primary evidence with deterministic Core verification, actionable feedback, and permission-controlled local environment diagnostics.

Install: `pip install buddie==2.0.7`.

[Repository](https://github.com/tsyyan/buddie) | [Privacy](https://github.com/tsyyan/buddie/blob/v2.0.7/PRIVACY.md) | [Release notes](https://github.com/tsyyan/buddie/releases/download/v2.0.7/release-notes.md)

# buddie 2.0.7

2026-10-31

A quote that is not on its page comes back with the page's own sentence to copy from.

## Changes

- When a quote is not found, the failing line shows the whole sentence of the page around the nearest match (from similarity 0.75), instead of the near match cut to the quote's length.
- Receipts carry it as closest.passage (at most 480 characters); closest.text and closest.ratio are unchanged.
- Below similarity 0.75 no text to copy is offered: such a quote is most likely not on the page at all.
- The hook's fix instruction points to that sentence first and to the source_text tool second.
- Hook decisions and exit codes are unchanged in all 819 recorded gate scenarios; only the failing quote line and the fix text differ.

## Upgrade

Install buddie==2.0.7 or update the plugin. The Claude Code marketplace follows plugin-stable and receives this release after publication; no reinstall is needed.

## Permissions

No new runtime permissions or dependencies. Checks run locally without a model. Optional evidence checks request cited URLs and the GitHub API (api.github.com, or an administrator-approved Enterprise API); GitHub credentials stay optional. No report or transcript is sent to a Buddie collection service.

## Security

Python hooks still run with -I and require Python 3.11 or newer. The candidate binds archives and public metadata to the source revision and SHA-256 digests. Report vulnerabilities through SECURITY.md.

## Limitations

Checks support evidence review and do not establish that every claim is true. Local source snapshots, pending report lines and feedback state can contain personal data and have no automatic expiry; the person can delete them. See PRIVACY.md for controls. Passing automated directory validation does not imply Anthropic approval; publication in its directory requires a separate review.
