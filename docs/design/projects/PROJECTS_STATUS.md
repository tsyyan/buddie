# Buddie Projects — architecture status and implementation gates

Status: **DESIGN ONLY / RUNTIME BLOCKED**. Reviewed 2026-10-28 against Projects
head `c545ff03be8b61e5cf6d2ce29d5df87f741deeb8` and fetched `main`
`1458b5b284b645e6555a065579baa8a5825b1c18`. This is a dated review snapshot;
recheck upstream before using it as current status. No Projects availability in
2.0.3 or any other release is established by this document.

The original [design](PROJECTS_MODULE_DESIGN.md), [roadmap](PROJECTS_ROADMAP.md)
and [acceptance plan](PROJECTS_ACCEPTANCE.md) remain unchanged, including their
2.0.1 baseline. Design §10 and the roadmap's final **MVP scope freeze** govern:
the earlier roadmap sentence about prototyping is conditional planning, not
authorization to start runtime work. This status document adds no new contract,
permission model, tool, schema vocabulary or implementation authorization.

## Architecture status

| Component | Reviewed status | Consequence |
| --- | --- | --- |
| Registry, focus, workstreams and decisions (P1–P3) | Proposed adapter-side metadata; no Projects runtime in either reviewed tree | Authored state cannot establish observed facts or grants |
| State reconciler (P2) | Proposed bounded collection; exact full-head observation and trusted project scope remain integration work | Existing anchor output alone cannot satisfy exact `pr.head` or project authorization |
| Context Checker (P4) | Proposed; existing registry remains `sources`, `github`, `execution`, with no `Module.run` | Do not select an unknown Projects module or overload existing check meanings |
| Plugin surfaces (P5) | Candidate CLI/MCP names only | Require client capability/catalog review; anonymous HTTP Projects excluded |
| Readiness projection (P6) | Proposed read-only composition of supported evidence and declared criteria | Missing publication/acceptance evidence stays explicit; CI alone is insufficient |
| Multi-project evaluation (P7) | A01–A28 are planned, not executed | No runtime completion or coverage percentage follows from this review |

## Dependency matrix

| Dependency | Observed evidence / limit | Required gate |
| --- | --- | --- |
| Architecture audit [PR #54](https://github.com/tsyyan/buddie/pull/54) | Merged documentation; `main` contains `docs/design/modularity/`, not proof its roadmap is implemented | Revalidate each task against code and tests |
| R0 | `tests/data/receipts_golden.json` and `tests/test_receipts_golden.py` absent from reviewed main | Freeze full receipt-v0/v1 baselines, including the literal GitHub paths added by #55 |
| R1 | `verify` entry points lack the proposed explicit journal input | Cover direct callers, hook and default behavior before checker dispatch changes |
| R2 | `verify.py` still imports mandate at module level; `_ci` imports freshness before its offline guard | Complete lazy-boundary work before R6 |
| R3 | Fail-closed behavior is a required regression gate; this review did not execute that regression | Require explicit exception-path evidence, never convert failure into PASS |
| R6 | `Module` remains metadata; no `Module.run` dispatch in reviewed main | R0/R1/R2, then pilot or separately accepted equivalent; R3 before new checker |
| RX | Merged architecture roadmap describes a design gate; receipt-v1 still uses closed check/module/reason enums | Accept version/compatibility and collector-provenance strategy before new vocabulary |
| Trusted project scope | Design §10 requires a host ceiling, authenticated session binding and immediate disclosure revocation | Independent enforcement/revocation review and tests block P1–P3 runtime; writable JSON is insufficient |
| Persistence | Atomic revision checks, serialized ledger appends and truncated-record handling are design requirements | Review platform locking, conflict/recovery and tombstones before runtime |
| Literal citations [PR #55](https://github.com/tsyyan/buddie/pull/55) | Merged; reviewed main has GitHub source/report paths | Recompute call sites and baselines; literal presence proves neither merged state nor readiness |
| History/Lineage [PR #51](https://github.com/tsyyan/buddie/pull/51) | Merged design, separate workstream | Log continuity is not historical authenticity; require an external anchor for that claim |
| BDX-001 [PR #56](https://github.com/tsyyan/buddie/pull/56) | Closed without merge | Experiment is neither dependency nor evidence of Projects correctness |
| R5/R7/R8/R9 | Not general P1–P3 prerequisites in the Projects roadmap | R9 matters only for separately reviewed future hook integration; avoid broad architecture work here |

Code evidence at the reviewed main revision:
[modules.py](https://github.com/tsyyan/buddie/blob/1458b5b284b645e6555a065579baa8a5825b1c18/buddie/modules.py),
[verify.py](https://github.com/tsyyan/buddie/blob/1458b5b284b645e6555a065579baa8a5825b1c18/buddie/verify.py),
[effects.py](https://github.com/tsyyan/buddie/blob/1458b5b284b645e6555a065579baa8a5825b1c18/buddie/effects.py),
[receipts.py](https://github.com/tsyyan/buddie/blob/1458b5b284b645e6555a065579baa8a5825b1c18/buddie/receipts.py),
[modularization roadmap](https://github.com/tsyyan/buddie/blob/1458b5b284b645e6555a065579baa8a5825b1c18/docs/design/modularity/MODULARIZATION_ROADMAP.md).

## Implementation milestones — future work, no dates or release promise

| Milestone | Scope | Evidence needed to leave the milestone |
| --- | --- | --- |
| M0: review P0 prerequisites | Confirm §10 scope, trusted host/session boundary and persistence approach in separate reviews | Explicit decisions and deterministic authorization/revocation/concurrency fixtures; runtime remains blocked until accepted |
| M1: scoped metadata (P1/P3) | Only after M0 and separate runtime authorization: off-by-default registry, focus and authored ledger | A04/A05/A08/A09/A14/A16–A18/A21–A23/A25/A26, including cache replay and absence of leaked metadata |
| M2: bounded current state (P2) | Only after collector boundary review: exact predicates, full SHA, UTC/monotonic budget and race handling | A01–A03/A06/A10–A12/A15/A24/A28 and negative freshness/state fixtures; denied/offline results stay unverified |
| M3: optional surfaces and projection (P5/P6) | Separate compatibility review and admitted evidence for each criterion | A07/A19/A27 plus unchanged legacy tools/catalogs, receipts, profiles and hooks; no inferred publication |
| M4: new checker (P4), if needed | After R0/R1/R2/R3/R6/RX and provenance review | Versioned compatibility evidence and A13/A20; no unknown enum promoted to success |
| M5: evaluation and release decision (P7) | Collect all acceptance evidence across supported clients/platforms | A01–A28 executed with input, source/revision, as-of, permissions, actual result and CI SHA; independent review and owner release decision |

Scenario groupings above are sequencing aids, not replacement tests. The full
acceptance plan, including privacy assertions and additional A10/A15 fixtures,
remains authoritative. **All 28 scenarios are still planned and unexecuted.**

Documentation review checked links, scenario IDs, diff scope and preservation of
the original three files. It did not run a Projects harness or establish runtime
security, implementation readiness, release readiness or distribution availability.
