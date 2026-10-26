# Buddie Projects — implementation roadmap

Status: **PROPOSED**, no runtime work authorized by this document. See [PROJECTS_MODULE_DESIGN.md](PROJECTS_MODULE_DESIGN.md). Baseline 2.0.1 (`main` `0bc048e`).

## Dependencies and sequencing

| Phase | Task | Deliverable | Merge gate |
| --- | --- | --- | --- |
| P0 | Agree minimal schema and source-of-truth rules | Project, focus, workstream, decision, observed state, claims | Threat-model and data-ownership review |
| P1 | Read-only registry and session focus | User-scoped projects with explicit repo links; no global focus | Two simultaneous sessions cannot cross-contaminate |
| P2 | GitHub reconciliation | Fresh PR/CI/release observations through existing authorized clients | Stale/denied/offline cases are not PASS |
| P3 | Workstreams and decisions | Scoped ledger with provenance and supersession | Agent-writable claims never become observed evidence |
| P4 | Context Checker | Scoped claim verification through Buddie Module API | Exact receipts and strict provenance, UNKNOWN on insufficient evidence |
| P5 | Plugin surfaces | Claude Code, then Codex and selected MCP clients | No regression to old tools, hooks or permissions |
| P6 | Release readiness | Criteria-driven verification report with explicit missing evidence | Green CI alone cannot mark release ready |
| P7 | Multi-project evaluation | Recovery across sessions; portfolio and cross-project scope tests | No cross-project leakage; reproducible baseline comparison |

P1–P3 can be prototyped behind an off-by-default feature boundary **without** claiming a new verification module is present. P4 depends on the approved modularization architecture.

### Relationship to PR #54 R0–R9

- **Prerequisites to add a new checker**: R0 golden receipts; R1 explicit journal pattern with all direct callers considered; R3 fail-closed regression test; R6 Module.run pilot or an accepted equivalent.
- **Missing prerequisite**: receipt-v1 extension/versioning policy for closed check/module/reason enums, with explicit migration/test updates; trusted collector provenance boundary for new source adapters.
- **Not inherently blockers for P1–P3**: R5, R7, R8; R9 required only if Projects findings get hook gate integration.
- Rebase architecture observations after PR #55 or subsequent verify/findings changes.
- PR #51 History/Lineage remains separate: reusing event logs is not a proof of integrity without an externally pinned head.

## Suggested initial vertical slice

Register **Buddie** and **HAVEN** explicitly. Focus Buddie. Read PR #54 and exact head SHA using existing GitHub authorization. Report “open at checked time” with source, compare with a deliberately stale saved “merged” claim, return conflict and last-known distinction. Start a fresh agent session; recover focus only when explicitly bound to that session and verify again. If GitHub unavailable, return UNKNOWN and old snapshot marked not current.

This first slice can use existing anchors without introducing a new check enum. Record which capabilities require a new checker and postpone them to P4.

## Definition of done (for each PR)

- Small atomic PR with verified baseline/HEAD, clean diff, independent review and revert path.
- Permissions and cross-project access tested; no surprise network or filesystem reads.
- Deterministic offline tests, missing evidence and adversarial cases.
- Existing gate golden scenarios and receipt-v0/v1 unchanged unless explicitly versioned.
- CI across supported platforms, not just a single local test.
- No merge, tag or publication without owner approval.

## Versioning recommendation

Do **not** include Projects in the 2.0.2 patch by default. Choose an appropriate minor version after public interfaces and compatibility changes are understood. A planning document or experiment is not released functionality.
