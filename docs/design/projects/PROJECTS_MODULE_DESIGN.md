# Buddie Projects — built-in module design (proposal)

Status: **PROPOSED / NOT IMPLEMENTED**. Baseline: `main` at `0bc048e` (Buddie 2.0.1, 2026-10-26). This document is a design, not a claim of shipped CLI/MCP functions.

## 1. Product boundary

`projects` is an **optional capability inside Buddie**, exposed through the existing installed plugin in supported environments (Claude Code first, Codex and other compatible MCP clients next). It is not a standalone SaaS, external dashboard, autonomous background agent, or separately installed Python package.

The user can register multiple projects and select one active project per session. The module tracks project workstreams and reconciles claimed states with evidence already available to Buddie (local Git, GitHub PR/CI, revisions, existing receipts and provenance). It must not claim to know unobserved project history merely because an agent remembered or wrote it.

Goals:
- List and focus projects without polluting a single session with every project’s context.
- Track features, research, decisions, blocking items, abandoned/on-hold work, and release criteria.
- Recheck volatile status before answering (with explicit checked-at, revision, source, and freshness).
- Recover a bounded, verifiable context summary in a new agent session.
- Reuse Buddie’s existing trust boundaries and verification terminology.

Non-goals for MVP: team SaaS, automatic release/merge, free-form autonomous agent scheduling, full issue tracker replacement, cross-user syncing, inference that a green CI alone proves release readiness, arbitrary third-party collectors/plugins.

## 2. Position in the existing architecture

The word “module” denotes a **user-facing capability**. Internally distinguish:

1. **Project Registry / Focus** — adapter-side local configuration and user-selected scope.
2. **Workstream / Decision Ledger** — adapter-side data store of claims, statuses and historical decisions, *not* independent evidence.
3. **State Reconciler** — bounded, permissioned evidence collection from known Git/GitHub sources; does not mint findings or policy decisions.
4. **Context Checker** — proposed verification module through Buddie Core, comparing precisely scoped claims to recognized evidence; never trusts a ledger record as proof.
5. **Release Readiness Projection** — combines explicitly configured acceptance criteria and existing checker outcomes. MVP has no new hook gate or policy class; any future action blocking needs separate policy/schema review.

Reuse `core.py`, `modules.py`, `verify.py`, `findings.py`, `receipts.py`, existing GitHub read client and the evidence/provenance controls. Do not build a second verification engine or receipt format.

PR #54 (`docs/architecture-audit`) is **proposed documentation**; its `Module.run` dispatch and R0–R9 are not implemented on baseline main. In particular, its review identifies incomplete journal call paths, import-cycle assumptions, and closed receipt-v1 enums that prohibit adding a check without an explicit schema-evolution step. No code may assume these proposals are available until landed and verified.

PR #51 proposes History/Lineage, with a separate hash-chained event-log problem. Projects must not silently inherit claims of tamper evidence from an agent-writable log. PR #55 extends GitHub literal citation verification and may change `verify.py`/findings, so recompute call sites and baselines after its merge. PR #56 BDX-001 is an experimental evaluation harness, not a prerequisite or proof of Projects correctness.

## 3. Core entities (logical schema, no storage implementation chosen yet)

- `Project`: immutable `project_id`, display name, explicit repo locators (owner/repo, local path with scope), enabled evidence sources, allowed actions, archival state.
- `Focus`: session-scoped `project_id`, explicitly chosen by user or from an unambiguous trusted repo mapping; **never silently changes authorization**.
- `Workstream`: immutable id, project id, type (`feature|bug|research|architecture|maintenance`), title, lifecycle, priority, blocking refs, expected version, evidence refs.
- `Decision`: immutable event id, project/workstream, author/origin, timestamp, rationale, alternatives and supersession link. Decisions are authored claims.
- `StateObservation`: provider, scoped locator, observed status, source revision/head, observed-at, collector identity, authorization record, integrity reference and limitations.
- `StateClaim`: subject, predicate, target value, as-of time, claimed origin and linked source (e.g. “PR #54 is merged”, “workstream ready for release”).
- `Finding`: compare a StateClaim with admissible StateObservation or report `UNKNOWN/UNCHECKABLE`, conflict or stale evidence using established Buddie vocabulary and the eventual approved receipt-v1 extension policy.

Each record has schema_version. Stable IDs do not depend on titles. Tombstones/supersession preserve provenance. No numeric “percent done” as a fact.

Lifecycle (suggested, not current Buddie enum): `idea → research → planned → in_progress → validation → release_ready → released`; orthogonal `blocked`, `on_hold`, `archived` with reason, last reviewed date and possible resumption criterion. Never derive “abandoned” solely from inactivity.

## 4. Verification and freshness rules

- **Merge/release status**: read from verified current GitHub source within the project’s granted repository scope; include `checked_at`, PR number, repo identity and head SHA where meaningful.
- **Tests and CI**: bind checks to exact commit and workflow/run; passed CI does not imply code merged, published or accepted.
- **Workstream completion**: require declared acceptance checklist; each item references direct evidence. Unknown items never become PASS.
- **Decisions**: confirm that the saved record exists and is attributed; verifying its storage does not establish the correctness of its rationale or truth of its content.
- **Conflict**: retain old snapshot; record observed transition or contradiction, never rewrite provenance.
- **Unreachable source**: show last known state labeled stale or unverified; no fabricated “current” status.
- **Scope**: `project_id`, repo identity, session and target revision are mandatory for checks; reject ambiguous repo/PR numbers and cross-project bleed.

Freshness/TTL is a policy per evidence type (PR and CI short-lived, immutable commit longer-lived, user decisions checked for supersession). TTL expiry is not the same as evidence being false. The reconciler must return a bounded evidence bundle; the checker recognizes trusted collector identity and admissible provenance using Buddie’s trust kernel, rather than accepting arbitrary agent-supplied flags.

## 5. Permissions and safety

Permission scopes per project: `project.read` (metadata), `source.git.read`, `source.github.read`, `ledger.write`, `project.configure`. Separate collection from disclosure to the current agent/client. Start read-only; no implicit cross-project access. A selected project is a filter, not a new grant.

Network and local filesystem reads obey existing evidence controls and protected policy; no shell scripts from repositories, no arbitrary hooks/collectors, no secret echo, no reuse of credentials across unrelated repos, no silent external sync. A stored ledger can be agent-writable and therefore must never independently establish observed provenance. Failure or unavailable collector must not result in PASS.

MVP storage contract is specified in §10. It remains single-user local state with no new dependency; SQLite and synchronization are deferred. No state file is a trust anchor.

## 6. Proposed user surface (not shipped)

Illustrative CLI (subject to interface review):
```
buddie projects list
buddie projects add --name Buddie --github tsyyan/buddie
buddie projects focus Buddie
buddie projects status --refresh
buddie projects workstreams
buddie projects release-check --target 2.x.y
```

MCP candidates: `project_list`, `project_focus`, `project_status`, `project_verify` (names TBD). Prefer bounded response sizes and predictable tool schemas. MCP clients with incompatible tool counts or permissions may use a smaller API. No new tool is assumed to exist today.

A status response must carry project id, scope, as-of time, collector provenance, per-claim result, current/last-known distinction and an explicit “not verified” section. Focus must be explicit in each call or safely bound to a session identity; no global mutable “current project” shared among concurrent clients.

## 7. Cross-project use

Portfolio mode returns short metadata with freshness labels; it does not load every project’s private detail or silently grant access. Cross-project comparisons require grants for **each** referenced project. A link between HAVEN and Buddie is a claim until repository revisions or other admitted evidence supports it. Partial access leads to partial/UNKNOWN coverage, not optimistic results.

## 8. Compatibility and release policy

MVP must not change existing CLI/MCP tools, receipt-v0, default module behavior, hook gating, exit codes, or protected-policy semantics. New verification module identifiers require a deliberate receipt-v1 schema and compatibility strategy (closed enums for checks/modules/reasons), plus tests and migration documentation. Do not overload existing check names or mark non-run checks PASS.

No separate distribution for MVP. A later independently installable extension requires an explicit trust and execution model; do not introduce dynamic Python entry points as a shortcut.

## 9. Decisions deferred beyond MVP

Section 10 is authoritative for MVP storage/concurrency, session binding, grant authority, full-head observation
and readiness projection. Those are implementation prerequisites, not deferred decisions. Post-MVP questions:
SQLite migration, cross-host sync, authenticated HTTP Projects, new Context Checker vocabulary after RX, optional
hook gate integration and any separately distributed extension. None is required or authorized by this docs PR.

## 10. MVP contract (design only, no implementation authorized here)

MVP is P1–P3 plus a read-only projection over **existing** `pr:` / `ci:` / local immutable file/commit findings.
It includes registry, explicit focus, workstreams, authored decisions and bounded revalidation. P4 new Context
Checker and new receipt words/tools are excluded until #54 R0/R1/R3/R6 and RX are accepted and implemented.
R2 is a transitive R6 prerequisite. Projects is enabled by an explicit feature setting, not by selecting an
unknown id in the current verification module registry. Turning it off means no Projects state reads or writes.

### Identity, session and authorization

Registry v1: project_id (opaque UUID), display_name, canonical owner/repo locators, optional approved local roots,
source allowlist, policy reference, archived, revision. Focus is keyed by authenticated transport principal and
session id, never by a shared process-global field or a model-provided session name alone. A CLI call carries
`--project ID` or an explicitly bound local session handle; stdio uses connection-local focus. Stateless HTTP
must carry project explicitly and authenticate its grant. The existing public HTTP server has no such identity:
**MVP does not expose Projects there**. A reconnect/new session has no focus until explicitly selected or bound by
a trusted client; repository auto-detection can suggest, but cannot silently choose among multiple matches.

Effective access = host policy ceiling ∩ configured project grant ∩ call/session scope. A focus change never
widens it. Registry/ledger are agent-writable metadata, so they cannot supply that ceiling or grant new roots,
repos or disclosure audiences. `project.configure` must be mediated by a trusted user/client configuration path;
an agent-writable field saying `allowed=true` is not authorization. Collection permission and disclosure permission
are checked separately for every record, including cached data, portfolio labels, errors and export. Revoke a grant
or archive/remove a mapping: invalidate session focus and deny cached disclosure immediately. No metadata or titles
from ungranted projects in listing results. IDs are not bearer capabilities.

These are requirements for compliant built-in code, not an in-process Python sandbox or confidentiality from a
malicious same-user process. Existing runner/network/protected-policy controls do not currently implement a
project ACL. That new authorization boundary must be independently reviewed before any runtime MVP claim.

### Persistence and concurrent clients

Design choice: per-user local `projects/registry.json` and per-project authored `ledger.jsonl` beneath Buddie's
user state/config location; adapters discover that location using existing platform conventions. Paths are
configuration details, never echoed into remote reports. Schema_version=1 and registry_revision are mandatory.
No SQLite/runtime dependency. Registry updates use atomic replacement with expected revision and exclusive writer
coordination; competing writes fail as conflict/retry, never silently overwrite. Ledger appends are serialized;
partial/truncated records are rejected and surfaced. Export is explicit and scope-filtered; secrets and raw API
bundles are excluded by default. A recoverable backup is not an integrity anchor. The exact file-lock primitive
and migration code are implementation review items. No arbitrary repository hook or executable is loaded.

### Workstreams and decisions

Workstream v1 requires project_id, immutable workstream_id, kind, title, authored lifecycle, acceptance items,
blocking refs, expected_version (optional), last_reviewed_at, revision and supersedes. Decision records contain
actor/source, timestamp and supersession, not model-inferred consent. `released` and `release_ready` entered in a
ledger remain authored assertions; verified readiness is a read-only derived projection with missing-evidence list.
`blocked`/`on_hold` require reason/resumption condition; inactivity cannot set abandoned. Project completion is
never inferred from a workstream title, elapsed time, a saved receipt or a green CI check alone.

### Independent current-state checks and freshness

Before returning a volatile claim as current, obtain a new admitted observation in that request, bound to
repo + PR/run + exact head SHA + observation time. Default cache reuse for mutable PR/CI state is **zero** in MVP;
a later TTL optimization requires a stated `observed_as_of`, configured maximum age and non-current cached label.
A timestamp or cached receipt is not fresh collection. Read PR head/state, then CI for that SHA, then re-read head;
if head changed, discard the combined readiness result and return unverified/raced, with bounded retry at most once.
This cannot eliminate changes after the final observation; always report as-of rather than permanent truth.
Merge claim requires `merged`/merge identity from the PR source, not successful checks or an editable PR description.

Existing verification outcomes remain exact: raw anchor HOLDS/BROKEN/UNCHECKABLE, Core SUPPORTED/CONTRADICTED/
UNDETERMINED and receipt-v1 PASS/FAIL/GAPS/UNKNOWN. UI conflict/stale/current labels are projections, never new
Finding.reason values. UNKNOWN provenance/offline hash-valid receipts cannot become fresh collector observations.
#55 proves literal presence in addressed file/body/diff; it does not prove PR merged, runtime correctness, authorship
or release readiness. A caller-supplied GitHub callback retains CALLER_SUPPLIED provenance. Reconciler metadata
cannot promote it by setting `collector_identity`. Only the trust kernel can attribute the actual collection.

Observation budget per project status: at most five existing source checks, one bounded retry after a head race,
no unbounded portfolio refresh. Denial/offline/partial budget gives explicitly incomplete coverage. Local Git may
support checkout/commit facts, GitHub supports hosted PR/CI facts; neither silently overrides the other's subject.
Release tags/publication/acceptance without a supported current collector remain unverified/manual requirements.
Preserve old observations as historical claims; #51 can later establish log-chain continuity only with its own
external anchor. Context Integrity compares present claims/evidence, while History/Lineage describes past records.

### MVP acceptance gate

All scenarios A01–A28 must have deterministic permissioned fixtures and explicit scope/revision/as-of assertions
before runtime work is called complete. Existing receipts, tools/list, default profiles and hook golden results
remain unchanged. No new checker may overload existing enum meanings. This PR supplies the design and test plan;
its scenarios have **not** been executed and no Projects runtime exists on this baseline.


### Finite MVP state predicates and exact comparisons

| Predicate | Evidence / rule |
| --- | --- |
| `pr.state` | Exact API projection: `draft` when state=open and draft=true; `open` when state=open and draft=false; `merged` only merged=true with merge identity/time; `closed_unmerged` when state=closed and merged=false; inconsistent/missing fields are uncheckable |
| `pr.head` | Full 40-character head SHA and canonical repo/PR identity from the same admitted response; compare exact SHA, no prefix matching |
| `ci.result` | Existing freshness/CI aggregation for that full SHA and configured required checks; missing/pending/unavailable is not success; no inferred merged state |
| `commit.exists` | Full immutable commit identity in an explicitly granted repository, independent of a branch name |
| `acceptance.complete` | Read-only projection: every declared criterion has admissible support for the target revision, no missing/conflicting/stale item; never a writable ledger fact |

No arbitrary natural-language StateClaim parser in MVP. Unsupported predicates stay authored/unchecked. Existing
`pr:...=open` also accepts draft, and `=closed` also accepts merged; do not reuse those coarser meanings as the exact
`pr.state` projection. Existing anchor rows abbreviate SHA; they alone do not satisfy `pr.head`. P2 needs an admitted
observation retaining the complete raw response/full SHA, approved at the collector boundary; if that boundary is
not available, exact-head status remains unverified rather than reconstructed from a prefix. This is new adapter
work, not an already shipped API. A mutable PR address is legitimate for a fresh state read; mutable file refs
remain inadmissible for an immutable code claim.

Observation time comes from the collector host's UTC clock at completion, with monotonic elapsed time for a
30-second operation budget; never from ledger/model-supplied timestamps. Future cache timestamps or detected clock
rollback invalidate freshness and require live collection; if clock confidence or live refresh is unavailable,
return unverified/last-known. MVP never lets an old timestamp suppress revalidation. Tombstones record project/id
revision, are access-filtered, invalidate focus, and cannot transfer the old grant to a recreated same-title project.

The trusted host must supply a versioned project-scope ceiling through OS-protected policy or an authenticated
client authorization service that the agent cannot edit. Until that integration has an exact enforcement and
revocation contract with tests, P1–P3 runtime is blocked. A user-state JSON file by itself is not such a service.
New optional MCP tools require capability negotiation plus exact tools/list/catalog tests for each supported client;
legacy/default surfaces remain unchanged. No Projects tools on the anonymous public MCP endpoint in MVP.
