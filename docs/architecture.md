# Architecture: modules and evidence

buddie checks what an agent's text claims against evidence, and blocks or flags it at a gate. This page describes
how the checking is divided (modules), where its evidence comes from (selection and provenance), and who may
decide either (the protected policy, [policy.md](policy.md)).

## Layers

| Layer | Files | Knows about |
|---|---|---|
| Core contract | `buddie/core.py` | typed findings, facts, decisions, provenance; no checker, no transport |
| Modules | `buddie/modules.py` | which checks exist, grouped by the evidence they need |
| Profiles | `buddie/profiles.py` | named presets of modules and checks, resolved to an explicit set |
| Checkers | `buddie/verbatim/`, `anchors.py`, `effects.py`, `mandate.py` | one kind of claim each, in its own words |
| Translation | `buddie/findings.py` | checker verdicts into core findings (exhaustive tables) |
| Verification | `buddie/verify.py` | one text in, a receipt-v0 and typed findings out |
| Evidence | `buddie/evidence.py`, `stores.py`, `logbook.py` | which repos, stores and journal a check uses, who named them |
| Policy | `buddie/policy.py`, `resolved.py`, `config.py` | who may decide what, per event |
| Transports | `hook.py`, `cli.py`, `mcp.py`, `remote.py` | how a text arrives and what is done with the receipt |

The core, the modules, the checkers, `findings.py`, `verify.py` and `evidence.py` import no transport and name no
agent provider (`tests/test_modules.py`). Provider-specific parts are inside a checker and named as such: `run:` reads
a Claude Code session transcript (`effects.py`), and the hook reads Claude Code's and Codex's event shapes
(`hook.py`). A future adapter for another agent platform is a transport that builds a text and calls
`verify.assess_selected`; it adds nothing to the core.

## Modules

| Id | Checks | Reads |
|---|---|---|
| `sources` | quotations, numbers of cited sentences | a snapshot store, fetching |
| `github` | `path#sha256`, `path@commit`, `fact=`, `pr:`, `ci:` (and text in an anchor's place) | repos, a GitHub GET function |
| `execution` | `run:`, `choice:`, work claims | the session transcript, the journal, the `[mandate]` queue |

The contract (`buddie/modules.py`):
- **Identity.** An id is stable and never reused. `buddie modules` lists them.
- **Capabilities.** Each module declares its `core.Check` kinds; every kind belongs to exactly one module.
- **Order.** Results come in registry order, whatever order the ids were asked in.
- **Configuration.** Selection is explicit: `buddie verify --modules sources,github`, MCP `verify_report`'s
  `modules`, `verify.assess_selected(text, ["github"])`. An unknown id is an error (CLI exit 2, MCP tool error),
  never ignored. No selection means every module, exactly what verify did before modules existed: `verify.verify`
  and `verify.assess` keep their signatures and always run every module.
- **Results.** A module left out does not run; Coverage names it (`module:<id>`, a capability off), so the core
  outcome of a smaller check is GAPS, never PASS. `modules.results` gives each module's findings and outcome.
- **Lifecycle.** Modules are part of buddie: there is no loading from paths, entry points or config, and no
  third-party code. Adding one means a new entry in `REGISTRY` with its checks moved there in the same change.

Without a profile the hook runs every module. A profile ([profiles.md](profiles.md)) turns off default gate levels, and the hook then runs only the checks whose class is still on after every explicit level and the protected policy's floors. What blocks there is set per gate class (`buddie.toml`, `BUDDIE_GATES`) under the
protected policy's floors, so switching a module off is not a way around a floor. The remote HTTP server does not
take `modules` (its argument contract is unchanged).

## Evidence

Five questions, kept in five places:

1. **Selection**: which repos and stores a check reads, and where the journal goes: `evidence.repos`,
   `evidence.store_for` (with `stores.session_sources`), `logbook.log_targets`.
2. **Provenance**: who named each place (`evidence.Origin`: environment, transcript, event, repo, policy, observed)
   and how far a finding's bytes are known (`core.Provenance`, set in `findings.py`).
3. **Collection authorization**: whether the hook may fetch or ask GitHub at all (`network`, `BUDDIE_FETCH`,
   `BUDDIE_GITHUB`) and through what network (`evidence.collector`).
4. **Verification results**: `verify.py`, unchanged by any of the above.
5. **Policy enforcement**: the protected policy's `[evidence]` table ([policy.md](policy.md#evidence)), read once
   per event through `policy.current()` and journaled as refused by `resolved.limited`. No second resolver: the
   same file, the same snapshot, the same refusal list as every other policy key.

An origin says who chose a place, never that it is true. Every local place is the agent's to write; the only
evidence the agent cannot write is what the hook fetches itself during the check, over a network the environment
does not route, which is what `stores = "observed"` and `collector = "isolated"` are for.

## Compatibility

- receipt-v0 is unchanged: the same keys, the same outcome words. Provenance and module results are internal.
- The 819 gate scenarios of `tests/data/gate_golden.json` give the same decisions.
- A protected policy without `[evidence]` decides as it did in #28.
- CLI and MCP: new optional `--modules` / `modules`; `buddie modules` is a new command. Nothing existing changed.
