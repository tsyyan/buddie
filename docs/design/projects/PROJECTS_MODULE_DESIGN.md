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
5. **Release Gate** — uses explicitly configured acceptance criteria and checker outcomes. Whether to block an agent action remains protected-policy responsibility.

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

MVP storage choice remains an implementation decision. Prefer existing Buddie user configuration/state conventions and single-user local storage before adding dependencies. SQLite is a candidate, **not** a committed prerequisite. Document data location, export, conflict behavior and privacy before implementation.

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

## 9. Open design decisions

1. Storage format and conflict resolution for multiple local clients.
2. Binding project focus to Claude Code/Codex/MCP sessions without leaking state.
3. Which evidence is safe to refresh automatically vs requiring user approval.
4. How to extend receipt-v1 check/module/reason enums compatibly and whether a new schema version is required.
5. Where trusted collector identity is established for new GitHub/state collectors.
6. Whether release readiness belongs to new findings or a projection over existing findings and user acceptance criteria.
7. Whether user-authored decisions are shared across hosts and under which privacy controls.

Every decision should be recorded with rationale before runtime changes.
