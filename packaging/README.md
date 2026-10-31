<!-- mcp-name: io.github.tsyyan/buddie -->

# buddie

Verify the claim. Know the context. AI agent reliability toolkit.

buddie checks agent reports against primary evidence with deterministic Core verification, actionable feedback, and permission-controlled local environment diagnostics.

Install: `pip install buddie==2.0.7`.

[Repository](https://github.com/tsyyan/buddie) | [Privacy](https://github.com/tsyyan/buddie/blob/v2.0.7/PRIVACY.md) | [Release notes](https://github.com/tsyyan/buddie/releases/download/v2.0.7/release-notes.md)

# buddie 2.0.7

2026-10-30

A shell hook launcher the Anthropic directory can inspect, preserving existing runtime behavior.

## Changes

- Hook startup uses separate, literal python3, python and py -3 commands instead of a computed command name.
- Path normalization is split into independently readable shell commands; Windows backslashes and paths with spaces remain supported.
- The no-Python fallback uses equivalent builtin tests and parameter matching instead of case patterns that the directory misread as program names.
- Python 3.11+, isolated mode, interpreter fallback order, hook stdin and arguments, and the no-Python Stop disclosure remain unchanged.
- Real-shell compatibility tests cover all three interpreter choices, Windows paths, argument boundaries and isolated mode.

## Upgrade

Install buddie==2.0.7 or update the plugin. The Claude Code marketplace follows plugin-stable and receives this release after publication; no reinstall is needed.

## Permissions

No new runtime permissions or dependencies. Checks run locally without a model. Optional evidence checks request cited URLs and the GitHub API (api.github.com, or an administrator-approved Enterprise API); GitHub credentials stay optional. No report or transcript is sent to a Buddie collection service.

## Security

Python hooks still run with -I and require Python 3.11 or newer. The candidate binds archives and public metadata to the source revision and SHA-256 digests. Report vulnerabilities through SECURITY.md.

## Limitations

Checks support evidence review and do not establish that every claim is true. Local source snapshots, pending report lines and feedback state can contain personal data and have no automatic expiry; the person can delete them. See PRIVACY.md for controls. Passing automated directory validation does not imply Anthropic approval; publication in its directory requires a separate review.
