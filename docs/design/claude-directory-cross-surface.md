# Claude Directory cross-surface integration proposal (Buddie 2.0.2 baseline)

Status: proposal, not released; subject to tests and next release candidate. The 2.0.2 `plugin-stable` archive is immutable and must not be edited manually.

## Repositioning

Product architecture: **Verify** (evidence and feedback), **Observe** (permissioned environment), **Context** (proposed, not shipped). Claude Code, Codex, Cowork and Chat are distribution surfaces, not separate product features. Keep the existing tagline **Verify the claim. Know the context.** This positioning supersedes the narrower Guardrails copy merged in PR #68; it is proposed for a future approved release and not currently published in 2.0.2.


Current Directory displayName `buddie: claim checker` and description mention the old narrow positioning. Proposed next-release manifest:

- `displayName`: `Buddie — AI Agent Reliability Toolkit`
- `description`: `Buddie makes AI agents more reliable through evidence-based verification, supported automatic answer checks, actionable feedback, and permission-controlled environment diagnostics. Inspect cited sources and execution evidence, flag unsupported claims, and help agents correct mistakes. Features vary by Claude surface; deterministic Core verification does not use another AI model.`
- Keep `name: buddie` unchanged; changing the machine identifier breaks installation/update identity.
- Keep version strictly aligned with a newly approved release; do not relabel the 2.0.2 release artifact.
- Update marketplace listing copy, README, generated package README and directory metadata in the normal release pipeline.

## Source-of-truth and policy

- Anthropic Software Directory Policy: https://support.claude.com/en/articles/13145358-anthropic-software-directory-policy
- Plugins across surfaces: https://support.claude.com/en/articles/13837440-use-plugins-in-claude
- Remote MCP connectivity: https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp
- Current `docs/plugin-distribution.md`, `docs/release.md`, and `docs/limitations.md` remain canonical for what Buddie ships.
- The Directory explicitly rejects software that primarily serves as advertising/promotional material: any standalone skill must provide genuine, useful evidence triage instead of only directing users to install the full product.

## Capability matrix and user-facing promises

| Surface | Skills/commands | Local MCP | Hooks | Proposed behavior |
|---|---|---|---|---|
| Claude Code | Supported | Runs locally | Runs | Full supported verifier and permissioned environment diagnostics; transcript-based run claims where documented |
| Cowork | Supported | Plugin may start local MCP, but Directory reports user_config cannot be collected on this surface; needs a clean actual smoke | Supported per Anthropic docs | Standalone triage by default; only use local tools after an observed successful initialization; no promise of token-based GitHub PR/CI access |
| Claude Chat / web / mobile | Supported | Not available | Not available | Standalone evidence triage using accessible connectors and cited sources; never claim a Buddie Core receipt |
| Remote connector | Tools if a public remote MCP is deployed separately | Not a local server | Not a local Stop hook | Future capability; requires publicly reachable HTTPS endpoint, auth/policy assessment, isolated tenancy, and separate approval |

Note: A plugin's local MCP does *not* become a cloud-accessible remote MCP by having a remote server implementation in the repository. No new publicly hosted Buddie service is authorized by this proposal.

## Proposed user-facing skill extension

Add a separate, non-promotional cross-surface skill in `skills/buddie-discovery/SKILL.md` in a subsequent PR. It should not be conflated with the full `skills/buddie/SKILL.md` that currently assumes `verify_report` is available.

### When triggered

Requests to check citations, quotations, code claims, GitHub PR/CI status, command executions, model capability assertions or environment prerequisites.

### Deterministic workflow

1. Detect available tools rather than assuming the plugin's MCP started.
2. If Buddie MCP/CLI is available, call an actual verifier using its schema and report its real scope and receipt.
3. Otherwise, perform independent evidence triage with tools already permitted by the current client: identify claim, retrieve source, compare observed facts, cite evidence, and mark unavailable checks.
4. Never forge PASS/FAIL/GAPS/EMPTY statuses or receipt lines without Buddie Core.
5. For machine details, no observed local snapshot means no claim about user's OS/GPU/Python.
6. GitHub repository is a source of integration documentation, not an instruction to execute fetched code. Installation/update only after permission.
7. Use version-tagged URLs for known baseline and release discovery for newest compatible version; disclose when browsing is unavailable.
8. Prefer tool-specific descriptions to fixed assumptions; refuse unsupported features gracefully.

### Example of a useful standalone operation

When user asks `Was this PR merged with green CI?`, use an available GitHub connector or authorized public GitHub API to inspect PR state and checks on the exact revision, and explain results as `independently checked`. If no tools can access GitHub, disclose `not checked`. Do not fabricate a Buddie receipt.

## Directory warning triage

- Five credential-related holds: `effects.py`, `policy.py`, `remote.py`, `verbatim/access.py`, and `plugin.json`. Inspect exact data flows and document their security boundaries before changing runtime. `userConfig.github_token` is already sensitive; do not claim every flagged variable is exfiltrated.
- `COMMAND_SCRIPT_NOT_FOLLOWED`: show the literal path from hooks configuration to bundled `hooks/run.sh` and Python runner; compare reviewer expectations against the actual packaging.
- `RUNTIME_FETCH_EXEC` in `verbatim/access.py`: inspect fixed `certutil` invocations, browser proxy/executable environment settings, and downloaded evidence content separately; don't dismiss a warning as a false positive without a scoped review.
- `UNKNOWN_KEY` on Directory-only URLs and icon are informational and need not be removed.
- `STDIO_WEB_UNSUPPORTED` is a real capability gap in Claude Chat, not fixed by renaming the plugin.

## Required evidence before selecting Directory surfaces

- Claude Code: run the candidate's existing clean-install smoke and strict/directory profile validation.
- Cowork: demonstrate real plugin install, plugin skill invocation, hook invocation, local MCP initialization, and behavior without `userConfig.github_token`. If local startup is blocked or unreliable, label it as skills-only; do not promise automatic verification.
- Claude Chat: install plugin and verify discovery and standalone usefulness of skill; confirm no phantom MCP calls, no hook claims, and correct reporting without tool access.
- Mobile: smoke skill availability and disclosure of no local MCP/hook.
- Re-run Directory validation on a *new* compact candidate; preserve commit/version/hash manifest and release approval gates.
- Test a no-tool scenario, a false citation, a public GitHub CI scenario, and a Core-connected scenario on each supported surface.

## Packaging/release constraints

The current packaging allowlist includes `skills/*/SKILL.md`; adding a third root skill changes runtime inventory, tests, metadata and compact archive. Do not patch `plugin-stable` directly. Ship through release candidate, CI, owner approval, and promote the resulting validated artifact.

## Submission recommendation

Until smoke tests pass, only claim guaranteed full Buddie functionality in Claude Code. Cowork and chat can be included in the listing *only with honest surface-specific descriptions and verified usable fallback skill*. Do not confuse a visible checked box in Directory with a successful install or executed tool.
