<!-- mcp-name: io.github.tsyyan/buddie -->

# buddie

Verify the claim. Know the context. AI agent reliability toolkit.

buddie checks agent reports against primary evidence with deterministic Core verification, actionable feedback, and permission-controlled local environment diagnostics.

Install: `pip install buddie==2.0.4`.

[Repository](https://github.com/tsyyan/buddie) | [Privacy](https://github.com/tsyyan/buddie/blob/v2.0.4/PRIVACY.md) | [Release notes](https://github.com/tsyyan/buddie/releases/download/v2.0.4/release-notes.md)

# buddie 2.0.4

2026-10-29

Buddie — AI Agent Reliability Toolkit: canonical Discovery, README-style branding, Linux worker guard hardening and Stop-hook corrections without duplicate answers.

## Changes

- The compact Claude plugin includes the canonical Buddie Discovery skill and reporting reference, read from the release commit and relocated without changing their bytes.
- Discovery distinguishes real Core verification, independent evidence triage with authorized tools, and unverified claims when relevant tools are unavailable.
- Public manifests and generated package descriptions adopt the AI Agent Reliability Toolkit positioning and the existing Verify the claim. Know the context. tagline.
- The plugin and Desktop bundle use the previously created white-dog icon with cyan accents matching the README artwork.
- Packaging rejects missing Discovery dependencies and competing destination paths, including case variants on Windows.
- On Linux, regex workers refuse to proceed if registering the parent-death signal fails or if the expected parent has already ended. The liveness test handles a process disappearing during the /proc read and retains diagnostics and cleanup.
- At Stop, failed verification now asks for corrected lines instead of repeating the full answer that is already displayed. PreToolUse delivery checks retain their existing behavior.
- Ready pull requests automatically run full validation. CI runs the main suite in parallel and the timing-sensitive worker tests separately, with pip caching.

## Upgrade

Install buddie==2.0.4 or use the matching approved plugin or Desktop bundle. This release replaces the unpublished 2.0.3 candidate and includes merged PR77. Standalone Discovery retains version 0.1.0. Published 2.0.2 artifacts and the immutable 2.0.3 candidate remain unchanged.

## Permissions

No new Core runtime permissions are required. Discovery uses only tools and evidence already authorized in the host session; optional Core diagnostics retain existing permission grants. No automatic installation or credential access is added.

## Security

Linux regex workers now fail closed when their parent-death guard cannot be established. The candidate binds archives, public metadata and canonical Discovery sources to the source revision and SHA-256 digests. Issue73 was closed at the owner’s request after PR77; the historical intermittent failure’s precise root cause remains unproven. Report vulnerabilities through SECURITY.md.

## Limitations

Discovery is an instruction skill, not an executable verifier. Automatic hooks and local MCP vary by client; actual Cowork, Claude Chat and mobile behavior is not certified by package validation. Projects/Context, hosted remote MCP and image-understanding tools are not introduced. Agensi submission is pending review, not approved.
