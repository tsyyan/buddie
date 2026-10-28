# Buddie Projects — acceptance and adversarial scenarios

Status: **test plan / not executed**. Companion to [PROJECTS_MODULE_DESIGN.md](PROJECTS_MODULE_DESIGN.md) and [PROJECTS_ROADMAP.md](PROJECTS_ROADMAP.md).

| ID | Scenario | Expected result |
| --- | --- | --- |
| A01 | Saved claim says PR #54 is open; upstream now says merged | Detect transition, report fresh source/revision; retain prior claim |
| A02 | Saved claim says PR merged; GitHub inaccessible | UNKNOWN/unverified, not “still merged” |
| A03 | PR #54 and another project's #54 share number | Require repository identity; reject ambiguous identifier |
| A04 | Project Buddie selected; ungranted HAVEN data requested | Deny/omit HAVEN and mark partial scope, no silent escalation |
| A05 | Agent writes “release ready” to local ledger | Record authored assertion; do not promote to verified evidence |
| A06 | CI successful at SHA A; release based on SHA B | Do not count CI success as support for B |
| A07 | PR merged but tests not confirmed and release criteria incomplete | No release-ready PASS |
| A08 | An item on hold with old timestamp | Keep on_hold, not “abandoned” based on inactivity alone |
| A09 | Two sessions select different projects concurrently | No focus bleed or credential leakage |
| A10 | Collector returns wrong repo or mutable file ref for immutable code (live PR address is valid for fresh status) | Reject or mark provenance UNKNOWN |
| A11 | User denies refresh; cached status exists | Label last-known, include timestamp and reason |
| A12 | Reconcile outputs conflicting records from GitHub/local | Surface conflict and source hierarchy, never silently overwrite |
| A13 | Missing/unknown module verdict | Never convert to PASS; fail closed at gate when relevant |
| A14 | Ledger contains modified history without external checkpoint | Do not claim historical integrity |
| A15 | Restore a new session after upstream PR changed | Fetch current observation before calling status “current” |
| A16 | Explicit feature setting disables Projects | No Projects IO, imports with side effects, or hidden collection |
| A17 | Project path or URL attempts traversal/SSRF | Bound to approved roots and existing network restrictions |
| A18 | Read-only client attempts add/update project | Permission denial, no partial write |
| A19 | Render portfolio summary with one unavailable project | Explicit partial coverage, no universal “all current” claim |
| A20 | Compare checker before/after R6 | Golden receipts remain identical for existing checks |

Evaluation: count stale claims correctly flagged, false alerts, scope violations, incorrectly asserted current status, and recovery accuracy. Tests must distinguish an execution log showing a command from an independent observed outcome. No percentages of coverage or statistically significant effect claims from a single run per scenario.

### Evidence standard

For each accepted scenario keep: test input, trusted source locator, exact revision or response fixture, observed-at, permission context, expected verdict, actual output, CI SHA and any failure analysis. A passing harness alone is not proof that a broad natural-language claim is correct.


| ID | Additional MVP scenario | Expected result |
| --- | --- | --- |
| A21 | Public unauthenticated HTTP caller requests project status | Projects surface absent; no cached data disclosed |
| A22 | Model edits registry grants or supplies another session id | No expansion of trusted grant or session identity |
| A23 | Permission revoked after observation; cached receipt requested | Recheck disclosure grant; deny cached metadata/body |
| A24 | PR head changes between state and CI collection | Discard mixed-SHA readiness, bounded retry, otherwise unverified |
| A25 | Two writers update same registry revision | One succeeds, other reports conflict; no lost update |
| A26 | Ledger append truncated or valid self-consistent history rewritten | Reject partial data; no claim of authenticity from continuity |
| A27 | All CI green but publication/acceptance source unavailable | List missing criteria; no release-ready PASS |
| A28 | Receipt says literal PR body contains “merged”, actual PR open | Literal match does not support state; independently observe open |

A01–A28 remain a design acceptance plan, not a claim of passing runtime tests. Every privacy case must also assert
absence of ungranted titles/paths/values in errors, portfolio summaries and exported records. Test cache replay
under a new principal and a new session; source permission alone never implies permission to disclose.


Additional negative fixtures within A10/A15: draft versus open, closed_unmerged versus merged, abbreviated versus
full head SHA, future cache time, collector clock rollback and a refresh timeout. Expected: exact projection or
explicit unverified state, never a silent match under the coarser legacy anchor meanings.
