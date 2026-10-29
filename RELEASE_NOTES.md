# buddie 2.0.5

2026-10-30

One name and icon across every channel, and a Claude Code marketplace that installs only released plugins.

## Changes

- Every manifest and listing uses the single name buddie; the tagline and the AI agent reliability toolkit category move to descriptions.
- The plugin and Desktop icon is the same dog image as a 23 KB palette PNG instead of 884 KB.
- The repository's Claude Code marketplace installs the released compact plugin from the plugin-stable branch instead of the default branch. The compact plugin carries its own marketplace file.
- Codex reads a dedicated .agents/plugins/marketplace.json and keeps installing the repository plugin; a tag pins a release.
- Documentation records the current channel check, listing copy with tool access labels and the plan for a new Anthropic directory submission.
- Two tests no longer fail when the suite runs as the root user.

## Upgrade

Install buddie==2.0.5 or update the plugin. Claude Code users who added the repository marketplace now receive releases from plugin-stable; no reinstall is needed. Codex users who want only releases add the marketplace pinned to a tag.

## Permissions

No new runtime permissions. Checks run locally without a model; GitHub credentials stay optional.

## Security

plugin-stable, now the Claude Code channel, is protected against deletion and force pushes. The candidate binds archives and public metadata to the source revision and SHA-256 digests. Report vulnerabilities through SECURITY.md.

## Limitations

Checks support evidence review and do not establish that every claim is true. Directory listings and their display of name and icon are updated separately by the owner. The Anthropic directory submission is not yet made.
