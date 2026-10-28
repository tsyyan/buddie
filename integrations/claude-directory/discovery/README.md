# Directory companion to canonical Discovery

The authoritative Discovery implementation is `integrations/agensi/SKILL.md`, with `references/reporting.md`, in PR #69. This directory deliberately contains no competing SKILL.md.

PR #69 was merged after full CI and gate passed on head `bcf1c0f367fc7aac7341856faa7e1516c8b106c0`. Compact packaging reads its canonical source from the release commit and relocates the exact blobs to `skills/buddie-discovery/`; the package manifest records the mapping and digests. This does not establish Directory approval or availability on every Claude surface.

Buddie — AI Agent Reliability Toolkit

Verify the claim. Know the context.

Verify provides evidence checks and feedback. Observe provides permission-controlled environment awareness. Context is the future Projects capability, not shipped.

## Surface boundaries

- Claude Code: use only installed, available MCP tools and supported hooks; transcript checks require actual authorized transcript access.
- Cowork: verify startup and tool availability independently; do not assume hooks, local MCP, credentials or environment observation are available.
- Chat: use authorized tools actually exposed in the session; local stdio MCP, local hooks and local transcript access must not be assumed. A separately connected remote Core tool may report only its actual capabilities.
- Mobile: verify skill and connector availability separately; do not assume desktop hooks, local tools, transcripts or environment access.

## Original branding

Use repository branding: white dog, dark outlines, cyan/blue collar and accents, minimalist style. The owner requested the previously created README-style square dog icon instead of the legacy green check. The replacement PNG was visually compared with the README logo and hero before adoption; actual Directory rendering still requires a platform check.

## Binary evidence and image inspection

Treat **retrieval**, **integrity**, and **visual inspection** as three separate claims. A successful Buddie `snap` records URL, HTTP status, byte count and content digest; it does **not** decode, display, or understand an image. `source_text` is for text, not a substitute for image viewing.

When a user asks to inspect a PNG, JPEG, GIF, WebP, screenshot or other visual artifact:

1. Identify the exact source (repository path and pinned commit/tag, attached file, or authorized URL) and what needs comparison. Prefer already provided attachments and original brand assets over an image search or generation.
2. If available and authorized, fetch or snapshot source bytes and record response status, size, hash, and revision. Check that the content is actually of the expected format; URLs and extensions alone are insufficient.
3. **Open the actual binary** with a client-supported image viewer, attachment viewer, or visual-analysis tool, where available. Check the rendered pixels against the requested characteristics and, for brand work, the known source art. Do not route binary PNG bytes into a UTF-8-only source reader or claim that a file hash proves appearance.
4. Distinguish findings: `fetched (integrity observed)`, `visually inspected (rendered content observed)`, and `not visually inspected (viewer unavailable)`. Report each precisely. If viewing is impossible, provide the direct original source link or request that the user attach the image; do not substitute an unrelated search-result image as the original.
5. For edits, preserve the user's original art and obtain an actual modified asset through an available image-editing capability. Do not claim a new icon has been uploaded, packaged, or adopted unless the exact changed file and build are verified.
6. Never transmit private screenshots or local binary files to an unapproved third-party service. Respect permission scope and distinguish independent visual analysis from a deterministic Buddie Core receipt.

**Capability boundary:** This skill describes a conditional workflow. Current Buddie Core's `snap` and `source_text` do not themselves provide an image-decoding/visual-understanding tool. A future image-inspection MCP capability requires a separately reviewed runtime design, MIME/size limits, secure storage, permission gates and tests. Do not advertise it as shipped.

