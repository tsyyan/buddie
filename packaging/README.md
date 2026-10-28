<!-- mcp-name: io.github.tsyyan/buddie -->

# Buddie — AI Agent Reliability Toolkit

Verify the claim. Know the context.

Buddie checks agent reports against primary evidence with deterministic Core verification, actionable feedback, and permission-controlled local environment diagnostics.

Install: `pip install buddie==2.0.3`.

[Repository](https://github.com/tsyyan/buddie) | [Privacy](https://github.com/tsyyan/buddie/blob/v2.0.3/PRIVACY.md) | [Release notes](https://github.com/tsyyan/buddie/releases/download/v2.0.3/release-notes.md)

# Buddie 2.0.3

2026-10-28

Buddie — AI Agent Reliability Toolkit: canonical Discovery packaging and consistent README-style branding.

## Changes

- The compact Claude plugin includes the canonical Buddie Discovery skill and reporting reference, read from the release commit and relocated without changing their bytes.
- Discovery distinguishes real Core verification, independent evidence triage with authorized tools, and unverified claims when relevant tools are unavailable.
- Public manifests and generated package descriptions adopt the AI Agent Reliability Toolkit positioning and the existing Verify the claim. Know the context. tagline.
- The plugin and Desktop bundle use the previously created white-dog icon with cyan accents matching the README artwork.
- Packaging rejects missing Discovery dependencies and competing destination paths, including case variants on Windows.
- Worker lifecycle tests retain diagnostics and clean up surviving workers; the historical Linux failure is not claimed resolved by Discovery packaging.

## Upgrade

Install buddie==2.0.3 or use the matching approved plugin or Desktop bundle. The canonical standalone Discovery skill has its own 0.1.0 version. Existing 2.0.2 artifacts remain unchanged.

## Permissions

No new Core runtime permissions are required. Discovery uses only tools and evidence already authorized in the host session; optional Core diagnostics retain existing permission grants. No automatic installation or credential access is added.

## Security

The candidate binds runtime archives, public metadata and the plugin's canonical-source mapping to its source revision and SHA-256 digests. Independent checks never fabricate Core receipts. Report vulnerabilities through SECURITY.md.

## Limitations

Discovery is an instruction skill, not an executable verifier. Automatic hooks and local MCP vary by client; actual Cowork, Claude Chat and mobile behavior is not certified by package validation. Projects/Context, hosted remote MCP and image-understanding tools are not introduced. Agensi submission is pending review, not approved.
