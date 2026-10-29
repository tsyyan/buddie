# Reporting and integration reference

## Recommended response shape

For each claim, provide:
- Claim (exactly what was asserted)
- Method (`Buddie Core` / `independent tool check` / `not checked`)
- Evidence (link, revision, timestamp, or recorded command output when available)
- Finding (Core's actual result if used; otherwise plain-language observation)
- Scope and limitations (what the evidence does and does not establish)
- Next action, if any

Do not translate an independent observation into Buddie's formal PASS/FAIL/GAPS/EMPTY vocabulary.

## Known 2.0.2 integrations (verify against current release before proposing)

Claude Code: plugin marketplace installation and Stop hook; supports transcript-based `run:` checks.
Codex: plugin and Stop hook; `run:` checks remain unchecked in this integration.
General MCP clients: local stdio `uvx buddie serve` provides tools but no automatic answer gate.
CLI/CI: Python package provides `buddie verify`; CI requiring a PASS must inspect the receipt outcome rather than relying only on process exit status.
Environment: local permissioned diagnostics; do not assume remote MCP exposes environment_snapshot.

The official repository is authoritative for installation and updates. Never assume one update command applies to all clients. Obtain user approval before changes to software or configuration.

## Standalone example

Claim: "PR #123 was merged and CI passed."
Method: independent tool check, if authorized GitHub tools are available.
Evidence: inspect PR merge state, exact head or merge commit, and check runs tied to the relevant commit.
Finding: state only what was observed. CI passing does not prove the implementation is correct.
If tools are unavailable: mark not checked; suggest connecting the official verifier.
