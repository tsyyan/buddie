# Discovery 2.0.3 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans in this session. Follow the approved scope in the user conversation.

**Goal:** Ship one canonical Discovery skill through Claude compact packaging and Agensi, with honest surface support and a validated 2.0.3 release.

**Architecture:** Preserve integrations/agensi as the canonical source. The compact builder maps its two Git blobs to skills/buddie-discovery in the ZIP and records this mapping. No second maintained implementation. Preserve existing Core; use the previously created README-style dog icon per the owner's updated instruction.

**Tech Stack:** Python standard library, pytest, GitHub Actions, official Claude validators.

**Spec:** User-approved six-point scope in this conversation; docs/design/claude-directory-cross-surface.md supplies surface boundaries.

## Global Constraints
- Identity remains buddie; display title is Buddie — AI Agent Reliability Toolkit.
- Discovery distinguishes Core, independent checks, and unavailable tools; no fabricated receipts.
- Projects/Context and hosted remote MCP are not introduced.
- Use the original white dog / cyan collar branding in assets/icon.png. Claim cross-surface support only after actual tests.
- Required full CI and gate must pass on final PR revisions; never bypass protection.
- Use the release workflow's candidate, authorization, publication and plugin-stable promotion stages.

## Review Focus
- Missing reporting reference must fail packaging rather than leave a broken skill.
- A second Discovery implementation must not silently override canonical bytes.
- ZIP transforms must remain reproducible and reject unapproved files.
- No-tools and no-Core clients must not pretend to call Core or local hooks.
- Untested mobile/Cowork behavior must remain explicitly unverified.

## Tasks
- [ ] 1. Update #69 from current main, retain worker diagnostics, run full CI, merge only with successful gate.
- [ ] 2. Add packaging tests for canonical Discovery byte equality, dependency presence, missing source and competing destination. Observe failure, implement explicit mapping and archive policy; run package/security tests. Update #70 with Toolkit positioning and surface guidance.
- [ ] 3. Build committed ZIP, strict/Directory validation, clean install and MCP/hook smoke. Inspect original icon pixels and hashes. Attempt actual Claude surfaces and record exact limits.
- [ ] 4. Build text-only Agensi ZIP from the same canonical blobs. Validate one SKILL.md and references. Submit via authenticated official flow, recording pending/approval truthfully.
- [ ] 5. Align version fields, date, changelog and releases/2.0.3.json; regenerate public metadata. Run final full CI on release PR and main. Tag exact approved merge SHA, keep candidate bytes and checksums, publish via existing protected workflow, then separately promote plugin-stable. Verify live outputs.

## Execution ledger
- 2026-10-28 owner update: include merged PR77, close issue73, and run the new candidate through the actual Claude Directory submission validator. The pending 2.0.3 publication was cancelled before authorization; its immutable tag is retained. Prepare 2.0.4 from main d7a29899f1e699f0fd37edfa928eb08543a8ecc4.
- Replacement release tasks: align current version fields and release record; describe Linux worker guards, liveness observation, Stop-only correction guidance and CI changes accurately; run version/package/hook checks and full CI; build a new candidate; run the actual Directory validator against its exact compact source. Never claim the historical worker failure's cause was proven.
- User authorized implementation, merges, submission and the repository release process after reviewing the scope.
- Existing linked worktree reused; no changes to other worktrees.
- #69 updated to bcf1c0f by merging main 55cc23d; full CI started by push.
- Ruling: map canonical blobs at build time, keeping source under integrations/agensi, to avoid duplicate same-name skills.
- Owner correction: replace the legacy green check icon with previously created README-style dog art. Visually compared the existing square dog icon, README logo and hero; copied the square PNG unchanged from outputs/github-readme-ready/assets/brand/buddie-icon.png.
