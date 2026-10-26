# Changelog

## Unreleased

- MCP and Python API: the hand-in boundary for verification feedback, `feedback_accept` / `repair.accept` (local
  servers only). A chain's `verified` covers its last independently accepted text only. A final report is accepted
  when the chain is `verified` and the report is byte for byte that text; otherwise it is refused (`artifact_mismatch`,
  `not_verified`). It is read-only: no trace record, schema, disposition or existing tool changes. It was found by the
  Feedback E2E benchmark (F3): a chain verified at start, an edit refused, and the edited text still read as verified.
  docs/feedback.md also records the evidence-attribution limit (F1) and today's scope and disclosure behaviour (F2, F4).
- Experiment, not shipped (`experiments/feedback-e2e-v1`, excluded from the sdist and the Desktop bundle): an
  offline benchmark of Verification Feedback through the local MCP tools against verification only. It has 8
  scenarios on a fixed world, hand-written ground truth, the ten protocol safety checks, run records with exact k/n
  metrics, and replay. A live pilot runner (`live.py`) with per-request cost enforcement and a
  completed manifest is prepared but needs a person's final authorization, and it was not run. No
  production behavior changes.
- MCP: the local stdio server offers verification feedback as `feedback_start` and `feedback_resolve`
  (docs/feedback.md#mcp). The server runs every check itself, keeps each chain's trace and check options in its state
  dir and re-verifies a correction with the chain's own options; no tool takes a receipt. Not on the remote server.
  A chain is started whole or not at all and committed under an OS lock only if unchanged since read (one
  submission per feedback across processes); a failed write leaves it as it was; damaged state is refused
  (`state_corrupt`), a change outside a running server too (`state_tampered`), and every result says whether it
  rests on the server's memory or on the agent-writable files (`basis`). Chains idle for 30 days are removed, at
  most 256 are kept (`buddie/chains.py`).
- Verification feedback v1 (docs/feedback.md, ADR-001): `buddie/feedback.py` turns a receipt-v1 into advisory,
  machine-readable feedback (a condition per finding, at most one bounded action, the receipt's evidence references
  unchanged); `buddie/repair.py` takes one corrected text per feedback within the actions' line scope, judges it only
  by a new receipt-v1 of no weaker scope, and ends within the repair budget (1 by default, at most 3);
  `buddie/trace.py` records each iteration as append-only, hash-chained records that replay. New command
  `buddie feedback RECEIPT.json`. Nothing existing changes: receipts, outcomes, the hook, MCP and the CLI's other
  commands are as before; no dependency is added. A chain is started and decided only on a `verify.Assessment` made
  in the caller's process (a receipt dict is refused: receipts are unsigned); a repair may not add lines but
  `buddie:` disclosures, and a verified claim must stay where it was; task requirements stated by the orchestrator
  keep a corrected report apart from a finished task (`requirements_unmet`).

- Automatically verify literal GitHub citations in ordinary Markdown reports through the existing `quote` check:
  full-SHA file links, PR description bodies and file/side/line-addressed PR diffs. Inline and fenced code are
  extracted; matching preserves code characters and indentation (CRLF → LF only). Ambiguous bindings and incomplete
  patches flag gaps. GitHub evidence bundles retain revisions, locations and snapshot hashes, support offline
  replay, and follow existing provenance/public-only remote access boundaries. No new dependency or MCP tool.
  Existing non-GitHub reports keep their behavior. See `docs/github-citations.md` for supported forms and limits.

## buddie 2.0.1 (2026-10-26)

Upgrading from 2.0.0: nothing to change. The MCP tools and their arguments, receipt-v0 and receipt-v1, outcomes,
the CLI's exit codes, the hooks, permissions and grants are the same; no dependency is added.

- `buddie serve` (stdio) reads MCP messages as UTF-8 on every OS. 2.0.0 decoded stdin with the locale's code page,
  so on Windows with a cp1251 or cp1252 code page a report's `⚓`, `«»` and Cyrillic arrived garbled and its anchors
  went unchecked (a false `pr:` claim was reported as a line with no anchor instead of broken); clients that set
  `PYTHONIOENCODING=utf-8` (the `.mcpb`) were not affected. A line that is not UTF-8 now gets the JSON-RPC parse
  error `-32700` "Invalid UTF-8 in JSON-RPC request" instead of stopping the server. Nothing else in the protocol,
  the tools or the receipts changes. With 2.0.1 a plain `uvx buddie@2.0.1 serve` needs no `PYTHONIOENCODING` or
  `-X utf8` on such systems.
- Documentation: reusable local MCP listing copy and a dated post-release distribution check (clarifying restricted
  OpenAI local submissions); the Cline, Kilo and Smithery check; Glama and MCPRush listing badges in the README.

## buddie 2.0.0 (2026-10-24)

Upgrading from 1.1.1: nothing to change for a 1.x setup. receipt-v0 stays the default with the same keys, outcome
words and statuses; the CLI's exit codes, the MCP tools' arguments, the hooks' registration and existing `buddie.toml`
files keep working. What can differ, each said where it happens:
- `buddie.toml` `[mandate]` patterns that backtrack exponentially, or `refs[].doc` templates with more than `{name}`
  fields, now make the file unusable (every answer returned with the reason) instead of holding the hook.
- A git that does not answer, a `ci:` ref that resolves to another commit, or check suites that disagree give
  `UNCHECKABLE`, not `HOLDS` or `BROKEN`.
- buddie's git reads no system or global git configuration but `safe.directory`, and runs nothing a repository's
  config names.
- A `fact=` anchor is always `UNCHECKABLE` (1.1.1 ran the checked repo's `tools/anchors.py` to compute it), and a
  file anchor whose path leads out of the repo (`../x#sha`) is `UNCHECKABLE` and not read (1.1.1 hashed the file).
  Where 1.1.1 said `HOLDS` for these, 2.0.0 says `UNCHECKABLE`, and the outcome can go from `PASS` to `GAPS`; their
  receipt-v0 reasons in `why` and `gaps` read differently (commit 8cb7273, audit R1 and R2). This is intended and
  stays; docs/release-hardening.md, RH-5, records the decision.

Environment diagnostics (docs/environment.md, "Diagnostics"; docs/design/environment-diagnostics.md):
- `buddie snapshot --category ...` and the local MCP tool `environment_snapshot` observe the parts of this machine a
  task needs: OS, shells, privilege level, CPU, memory, GPU, storage, Python interpreters, runtimes, package managers,
  GPU driver and CUDA/ROCm stack, catalog tools, Docker/Podman, a project's manifests, a repository. Only what the
  person granted in `environment.toml` (their user configuration directory) and an ACTIVE protected policy's new
  `[environment] allow` (and `roots`, for the path-scoped categories) permits is collected; a request grants nothing, and an MCP argument outside the schema (a
  `consent`) is an error. Each category uses only its declared, fixed methods (OS interfaces, fixed files, programs at
  fixed places or on PATH with fixed arguments, an allowlisted environment, timeouts and output limits), adapts within
  itself (nvidia-smi after an NVIDIA adapter) and records every attempt. The environment-diagnostics-v1 document keeps
  observed values with their basis, unavailable reasons and the caller's task apart; network, proxy, port and
  application categories are answered as unsupported. environment-v0, `buddie snapshot` without `--category` and
  freshness are unchanged; freshness also reads the v0 snapshot inside a diagnostics document. The remote server
  does not offer the tool. `buddie snapshot --list`, `--grants`, `--grant-template`.

Publication approval:
- `release.yml`'s `authorize` job runs in the protected environment `pypi`, so every publishing run, the recovery
  runs `only: mcp-registry` and `only: github-release` included, waits for the environment's reviewers before any
  stage. It protects only while the environment has required reviewers (docs/release.md, "Who approves a
  publication").
- docs/release.md: checking a published release's files (the flat assets put back where `release-manifest.json`
  says, then `sha256sum -c` and the manifest check); recovery after a partial publication uses only the approved
  candidate, a rebuild never (its bytes differ), and stops for the owner when that candidate is gone; recovery is a
  new, approved dispatch; a final pre-release checklist. CITATION.cff leaves `date-released` out until the release
  commit dates the release.

Release candidate and distribution (PR #38):
- The release workflow publishes nothing on a tag push. A pushed tag `vX.Y.Z` builds a candidate (sdist, wheel and
  the Claude Desktop bundle from that commit, validated, installed into clean venvs and run) and records it in
  `release-manifest.json` and `SHA256SUMS`. Publishing is a manual run on the tag that names the candidate run and
  types `publish buddie X.Y.Z`; it checks the tag, the version, that the commit is on `main` and the candidate's
  files byte for byte, then sends those same files to PyPI (trusted publishing), the MCP Registry and a GitHub
  Release, each stage repeatable and completing only what is missing. CI builds the same candidate on every pull
  request. The TestPyPI target is gone: the candidate is the dry run. docs/release.md.
- The publish run's decisions live in scripts/release_publish.py, tested against a fake GitHub API and recorded
  PyPI and registry answers: `authorize` also checks the candidate run's repository, tag, status and the artifact's
  own record; PyPI is checked before uploading (identical files: done; any other file: stop); an existing registry
  entry must match server.json; the GitHub Release is found by tag or as the single draft, re-read by id, completed
  with only missing files, never changed once published, and stops on an asset that differs, did not finish
  uploading, or cannot be checked. docs/release.md: partial publication, recovery per stage, the owner's checklist.
- README rewritten as the landing page: what buddie verifies and what it does not, the outcomes, installs per client,
  enforcement versus advice, the protected policy, receipts, security and privacy, research results, with badges for
  CI, PyPI, Python, license, release and the MCP Registry. Its examples are run by `tests/test_readme.py`. The detail
  moved to docs/claude-code.md, docs/configuration.md and docs/research.md. The old README said a `GITHUB_TOKEN`
  in the environment was used for GitHub; buddie has not read it since 1.1.
- docs/distribution.md: every channel's public version, source, update path and review, with the MCPRush, Glama and
  Anthropic directory audits. The repository's plugin marketplace follows `main`, so it serves 2.0.0 already.
- The MCP tools `snap` and `source_text` describe each parameter. `scripts/make_icon.py` takes its output path.

Remote verification, the landing page and release finalization (PRs #42, #44 and the release commit):
- Fix remote public GitHub `ci:` verification: allow commit resolution and explicit latest check-run pagination,
  with strict route/query validation and the existing public-repository checks.
- README rewritten as the 2.0 landing page: verify, catch mismatches and observe, a real verification run and a real
  diagnostics run (assets/demo), one recommended start, a short statement of limits; badges for CI, Python and
  license. Its detail moved word for word to docs/verification.md, docs/getting-started.md and docs/limitations.md;
  `tests/test_readme.py` runs the examples there and the diagnostics demo with the README's grants file.
- The README's images and links point at the `v2.0.0` tag, so the PyPI page (which resolves no relative path)
  shows them; `tests/test_readme.py` maps each pinned URL back to the file in the checkout. The GitHub Actions
  that build and publish a release are pinned to full commit SHAs.

Release hardening (docs/release-hardening.md):
- RH-1 (the intermittent Windows test failures): by experiment, the failure depends on the launcher. It reproduces
  without buddie under the Python install manager's command shim (`%LOCALAPPDATA%\Python\bin\pytest.exe`), and not
  under pip's launcher or `python -m pytest`. What inside the shim invalidates the test process's standard input
  handle is not proven (a late close of a handle it duplicated in is the working hypothesis; it reproduces the
  signature, but was not observed). buddie's own child processes never inherit standard
  input (`pdftotext` and `certutil` now get it explicitly, and a test keeps every call site so); the suite names a
  recurrence (`BUDDIE_RH1_STRICT=1` fails the run). Run the suite with `python -m pytest`.
- A test that the pattern worker ends with buddie's process mid-match (Windows, Linux; macOS recorded).
- Version 2.0.0 in every manifest.

- Adversarial verification suite (`tests/test_adversarial.py`, docs/adversarial.md): attacks an agent can mount
  with what it controls, run through the hook, the CLI, MCP and the collectors, in a threat matrix with the test
  that holds each. Found and fixed:
  - A `ci:` anchor whose ref is a branch or tag named like the SHA (`ci:o/r@deadbee=success` with a branch
    `deadbee`) held on another commit's checks. When GitHub's check runs or combined status name another commit,
    the anchor is now UNCHECKABLE.
  - `ci:` anchors go through `freshness.ci_evidence`: the SHA resolved to its full commit, the latest runs and
    status fetched once for that id, each naming it, GitHub's count read in full; a run without `head_sha`, on
    another commit, a missing page or disagreeing suites are UNCHECKABLE.
  - The pattern worker is bounded in every step, not only while it matches: its start (within the event's budget),
    writing the request (a worker that stops reading cannot block on a full pipe), and a whole, well-formed answer;
    past any of them it is killed and reaped, one worker at a time. Linux and Windows end it with buddie's process.
    Texts over 64 K characters are not matched.
  - `buddie.toml` `[mandate]` patterns run in a worker process within 1 s per match and 10 s per hook event; past
    that the worker is stopped and the answer returned (`PatternTimeout`; the CLI exits 2).
  - `buddie.toml` `[mandate]` patterns could backtrack exponentially on the queue's text (`(a+)+$`: hours in
    Python's `re`), holding the hook until the host let the answer out unchecked. Patterns with a backreference, a
    repeat over alternatives or an unseparated repeat inside a repeat, or over 512 characters, and `refs[].doc`
    templates with anything but `{name}` fields, now make the file unusable: every answer is returned with the
    reason.
- docs/release-hardening.md: the intermittent Windows full-suite failures, with the first captured signature
  (`WinError 6` duplicating the test process's standard input handle); classified in RH-1 above.
- Evidence freshness (`buddie/freshness.py`, docs/freshness.md): whether evidence is bound to the revision a claim
  is about, apart from whether it is valid and how old it is. `CURRENT`, `STALE`, `UNKNOWN` (`NOT_APPLICABLE`
  reserved), each with a reason; only full commit ids compare, the same SHA in two repositories is not one revision,
  and evidence counts only when buddie observed its revision (by identity, not a field). `buddie freshness ci
  --repo R (--pr N | --commit SHA) --evidence SHA [--check NAME]`: a PR's head resolved now, the commit GitHub's
  check runs and statuses are for (each must name it), the CI outcome reported beside the state (`CURRENT` is not
  "passed"). `buddie freshness repo --commit SHA [--artifact PATH=SHA256] [--snapshot FILE]`: the checkout now (a dirty
  tree is `UNKNOWN`) and files' bytes. Exit 0 CURRENT, 1 STALE, 3 UNKNOWN, 2 unusable input. The protected policy's
  network and API apply. Receipts, the hook and `buddie verify` are unchanged; not on MCP.
  A binding's details are read-only all the way down and rendered as new objects; `render()` recomputes each CI
  summary from its runs and statuses. Check runs are asked for with `filter=latest`; a check name whose runs in
  different check suites disagree is `ambiguous`, not a success or failure, and names in several suites are listed.
  The identity registry is a boundary for data, not a sandbox: code in the same interpreter can register a binding.
- Remote server: an answer given before the request body is read (401, 403, 404, 411, 413) reads and drops up to 64
  KiB of the declared body and closes the connection. Before, Windows reset the socket over the unread bytes and the
  client lost the answer (`WinError 10053`, about one call in forty: the flaky `test_remote` tests).
- Security (docs/security.md): every program buddie starts goes through `buddie/runner.py`: a fixed argument list,
  a timeout, output bounded whether kept or streamed, the whole process tree stopped (a process group on Linux and
  macOS, a job object on Windows), and one 40-second budget for all of a hook event's git and free command. git gets
  an environment of its own (`PATH`, git's own settings; no token, no `GIT_DIR`, no `GIT_CONFIG_*`, no proxy, no
  protocol), reads no system or global configuration but the person's `safe.directory` entries, and runs with
  `core.fsmonitor`, signature display and, for `git status`, every filter driver the repository's config names
  switched off.
  - SEC-01 (high): the hook's `git status` for the session's `sources/` stores ran the repository's filter and
    fsmonitor commands in the hook's environment, where the plugin's GitHub token is. They no longer run. When the
    stores cannot all be listed safely, the hook says so and journals `stores_unavailable`.
  - SEC-09 (high): the launch gate's free command (`BUDDIE_FREE`, settable by a project, or the policy's
    `free_command`) ran with the plugin's token in its environment. It now runs without `CLAUDE_PLUGIN_OPTION_*`,
    `BUDDIE_GITHUB_TOKEN` and `BUDDIE_HTTP_TOKEN`, and cannot hold the hook past its timeout on Windows.
  - SEC-08: `GIT_DIR` and the like in the environment no longer choose the repository an anchor is checked in.
  - A git that does not answer is `UNCHECKABLE`, never `BROKEN` (`path@commit`, a queue at a commit).
  - Snapshots: `git ls-files` output is bounded when streamed; `environment.problems()` takes only plain JSON data.
  - Behaviour: system and global git configuration (but `safe.directory`) no longer apply to buddie's git; git status
    for the session's stores leaves out submodules and rename detection; one more git call per Stop in a repository.
- Environment snapshots (`buddie/environment.py`, docs/environment.md): `buddie snapshot` and
  `environment.collect()` record what buddie observes itself of the place a check ran in: the interpreter (Python,
  OS, architecture), the git repository (the commit HEAD names; whether the tree is clean or dirty, and how many
  entries git status lists; the origin remote without credentials) and named files under a root (sha256 and length,
  read once with stat compared before, after and by path). Each fact names what it rests on (`buddie` or
  `agent_writable`); one buddie cannot observe is `unavailable` with a reason and no value; what the caller states
  (`--supply`) is kept apart as `caller_supplied` and never checked. Paths that lead out of the root are refused and
  not repeated; no environment variable, user, host or absolute path is recorded. git runs without a shell, with a
  timeout, bounded output, an environment of its own and every command the repository's config can name switched
  off (`core.fsmonitor`, filter drivers); an index with assume-unchanged or skip-worktree entries is not shown clean.
  No network. `--report` gives the digest a receipt names as its subject. Not signed, not exposed over MCP, read by
  no check; receipt-v0, receipt-v1 and its schema are unchanged. `environment.problems()` checks a snapshot for
  consistency, not authenticity.
- Security: the Claude Code plugin's MCP server receives the GitHub token setting as
  `CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN` (`.mcp.json`), as the hook does, so it goes only to api.github.com or the
  protected policy's `github_api`; under `BUDDIE_GITHUB_TOKEN` it could go to an API a project's environment named.
- `buddie verify` on a directory or a non-UTF-8 report exits 2 with the reason instead of a traceback with exit 1
  (the code of a FAIL). `buddie status` names an active or invalid protected policy. MCP's instructions no longer say
  PASS means every quote and anchor holds. docs/integrations.md: every shipped surface, the PR #32 audit, setup,
  reading results, troubleshooting.
- receipt-v1 (`buddie/receipts.py`, docs/receipts.md, docs/receipt-v1.schema.json), given only when asked for:
  `buddie verify --receipt v1`, MCP `verify_report` `receipt: "v1"`, `receipts.render(verify.assessment(...),
  "v1")`. It keeps apart the outcome of what ran (PASS, FAIL, GAPS, UNKNOWN, EMPTY, NOT_RUN), the scope (requested,
  effective, executed, excluded with a reason and the claims of that kind in the text), the coverage (FULL, PARTIAL,
  UNKNOWN, NONE) and the evidence's provenance. The version is the predicateType. One check, rendered as either
  contract: `verify.assessment()` runs once, rendering never checks again. receipt-v0 stays the default everywhere
  and is unchanged; the hook, the journal and the remote server stay on v0. `buddie receipt-schema`;
  `receipts.problems()` checks a receipt-v1 for consistency (not authenticity), exclusion reasons
  against the requested and effective selections included.
- Verification profiles (`buddie/profiles.py`, docs/profiles.md): `developer` (github, execution), `research`
  (sources), `complete` (everything) and `custom` (listed modules and/or checks), resolved to an explicit,
  deterministic set of checks run by the same core. `buddie profiles`; `buddie verify --profile/--checks`, MCP
  `verify_report` `profile`/`checks`, `verify.assess_selected(profile=, checks=)`; `buddie.toml` `[verify]` for the
  hook, where a profile turns off the default level of each class none of its checks feed, below `[gates]`,
  `BUDDIE_GATES` and the protected policy's floors. What a profile leaves out is named in Coverage with the claims
  of that kind the text holds, and printed as a note; an unknown name is an error (a `buddie.toml` with one is
  unusable). Without a profile nothing changes.
- The final rule reads whether an answer carries an anchor from its text, not from the anchors that were checked
  (the same thing without a profile).
- A profile whose effective selection is empty (every class it feeds turned off) runs no check: no fetch, no GitHub
  call, an EMPTY receipt, a journal line with `"checks": []` and an explicit note in `buddie status`. Only "no
  profile" means every check.
- Verification modules (`buddie/modules.py`, docs/architecture.md): `sources` (quotes, numbers), `github` (repo
  anchors, `pr:`, `ci:`) and `execution` (`run:`, `choice:`, work claims), each with a stable id and its checks.
  `buddie modules`; `buddie verify --modules`, MCP `verify_report` `modules`, `verify.assess_selected`. An unknown
  id is an error; a module left out shows in Coverage. With no selection everything runs as before; the hook always
  runs every module.
- Security: the protected policy's `[evidence]` table (docs/policy.md, "Evidence"): `repos = "event"` sets
  `BUDDIE_REPOS` aside, `stores = "observed"` judges quotes and numbers only on pages the hook fetches in the check
  (forged snapshots no longer count), `journal = "fixed"` keeps `BUDDIE_LOG`/`BUDDIE_SHARED_LOG` from moving or
  turning off the journal, `collector = "isolated"` keeps proxies and CA overrides of the environment off the hook's
  fetches, `github_api` fixes the GitHub API and where the token goes. Keys left out keep the legacy behaviour, so a
  policy without `[evidence]` decides as before.
- Findings record their evidence's provenance more exactly (internal; receipt-v0 unchanged): a snapshot this check
  fetched itself is observed, another is of unknown origin; a `pr:`/`ci:` answer from `BUDDIE_GITHUB_API` or
  through an environment proxy is caller supplied, not observed from GitHub.
- Security: the GitHub token goes only where it belongs. The plugin's token setting is no longer sent to an API
  named by `BUDDIE_GITHUB_API` (the agent could name its own server), only to `api.github.com` or the policy's
  `github_api`; the token is an unredirected header, so a redirect never carries it to another host, and an answer
  from another origin is not taken (the anchor stays unchecked).
- Provenance says what buddie observed: a snapshot is collector observed only when this check fetched the cited
  https URL itself (not bytes added to the store, not plain http, not archive or browser copies), and a `pr:`/`ci:`
  answer only when buddie's own GitHub GET asked the default or the policy's API. "Own" is by identity
  (`effects.github_get`, the remote server's wrapper of it; `Store`/`UnionStore` and only what they fetched during
  the check), never an attribute or a set a caller can fill. The network is judged before and
  after a check, and the isolated collector nests and overlaps across threads without leaving its opener behind;
  it no longer touches `os.environ`. docs/policy.md, "Provenance" and "The collector's scope".
- Security: the Codex Stop hook runs `python3 -I` / `python -I`, so `PYTHONPATH` from the environment loads nothing.
- Windows: a `[mandate]` queue read at a commit (`git show`) is decoded as UTF-8, as the file in the tree is, not in
  the locale's encoding (cp1251 misread a Russian queue's words). The same for the repo path git prints (a checkout
  under `C:\Users\Иван` was not found), a merge commit's subject (cp1251 cannot decode «И»; the launch gate failed
  on it) and the snapshot store's `index.json` (written as UTF-8; an index an older version wrote in the locale's
  encoding is still read). Test fixtures write and read UTF-8 explicitly, so the suite passes without UTF-8 mode.
- Security: a protected policy (`buddie/policy.py`, docs/policy.md). A file only an administrator can write
  (`/etc/buddie/policy.toml`; `<ProgramData>\buddie\policy.toml` on Windows) sets floors for each gate class and
  what buddie.toml and the hook's environment may still decide: the intro mode, the final mark, transcript reading,
  conversation words in the journal, turning return tracking off, the launch free command, the network, and whether
  a `buddie:` line may let a returned answer out. Lower sources may tighten, never weaken; each refusal is journaled.
  With no policy nothing changes; a policy that is there but unprotected or invalid makes buddie run on its strictest
  limits and return each answer with the reason. `buddie policy show|check|template`; buddie never writes the file.
- Security: on Windows the policy counts as protected only when the file and every directory above it are owned by
  SYSTEM, Administrators or TrustedInstaller, no ACE lets a low-privilege principal or this user change or replace
  them, and AccessCheck with the hook's token agrees (`buddie/winacl.py`, ctypes only). An applicable allow ACE the
  check does not read (object, callback/conditional, compound) makes the policy invalid instead of being skipped.
- Security: the hook launcher runs Python isolated (`-I`, also for its version probe), so PYTHONPATH and friends from
  a project's settings load nothing into it; with no Python 3.11+ a Stop's answer goes back once with the reason
  instead of passing (the re-entered Stop goes on with a systemMessage). docs/policy.md, "A trusted launcher".
- The hook reads the protected policy once per event (`policy.snapshot()`).
- Security: a buddie.toml that cannot be used (not TOML, not UTF-8, unreadable) no longer turns the gate off. It
  used to make the check raise and the hook let the answer out unchecked (exit 0). Now none of its settings apply,
  buddie's full defaults do, and the gate returns the answer with the file and the reason until the file is fixed
  or a `buddie:` line tells the reader. `buddie status` says so too.
- Security: a `buddie:` line the agent wrote before buddie returned the text no longer lets out an answer buddie
  could not check (a broken buddie.toml, an error in the check, findings that do not line up): it counts only on
  the attempt after that return. The Stop Claude Code re-enters after such a return is never held (no loop), and
  buddie tells the person, as a systemMessage, that the answer went out unchecked. The journal marks these lines
  `status`: `internal_error`, or `unchecked_disclosed` with `by` agent or buddie; a checked answer's line is as before.
- Security: an error inside the check of a text the gate guards (a final answer at Stop, a text tool's message) no
  longer lets it out as checked: it goes back once with the error (exit 2). A re-entered Stop, a `buddie:` line and
  every other event (SessionStart, PostToolUse, launches) are let through as before.
- The typed gate no longer falls back to the items' words when the findings do not line up with them: each item
  then blocks whatever its level, and the journal line says `typed_mismatch`.
- Internal: the Stop and PreToolUse gate takes each blocking item's class from the finding behind it
  (`verify.blocking_findings`, `config.CLASS_OF_CHECK`) instead of from the item's words; `config.classify` stays
  for compatibility and as the fallback. The hook resolves an event once (`buddie/resolved.py`,
  ResolvedEventContext: repos, buddie.toml, settings with their sources): a Stop now runs `git rev-parse` once and
  reads buddie.toml once, where it ran 6 to 8 git commands and read the file 4 to 6 times. The gate's output on 819
  recorded scenarios is unchanged (`tests/data/gate_golden.json`).
- Internal: the journal writer (`buddie/logbook.py`) and the event helpers (`buddie/event.py`: a tool's text, the
  repos of a session) moved out of `hook.py` and `promises.py`; the summary, decision cards, promises, context gate
  and config no longer import the hook. `config` names each setting's source (`Source`, `resolve_levels`,
  `resolve_transcript`) and lists what a repo's buddie.toml weakens (`influence`); values are unchanged.
- Internal: a typed contract for what a check found (`buddie/core.py`: Finding, Fact, Sufficiency, Decision, Policy,
  Outcome, ReasonCode, EvidenceRef with Provenance, Coverage) and its adapter from the checkers' rows
  (`buddie/findings.py`). verify's outcome now comes from the findings; receipt-v0, the CLI, MCP, the hooks and
  exit codes are unchanged (the same receipts, byte for byte, on the comparison set). One edge: an anchor or work
  claim status no checker returns used to fall through to PASS and is now a gap.
- Security: a `[launch] free` command in `buddie.toml` is ignored. buddie.toml belongs to the repo under check, and
  the launch gate ran that command with a shell. The free command now comes from `BUDDIE_FREE` only.
- Security: the files `buddie.toml` names (`queue`, `accepted`, `messages`) are held to the repo by the same rule as
  file anchors, and are not read past 16 MiB.
- Security: the remote server answers `pr:`/`ci:` anchors only for public repositories. Its token may see private
  ones, and a stranger's anchor would have learned their PR states, commits and check names. A GitHub anchor whose
  owner or repo is `.` or `..` is not looked up.
- Limits: a file anchor is hashed in chunks and not past 256 MiB; a fetched page is not read past 32 MiB; a
  compressed body is not inflated past 64 MiB; a report given to `verify_report` is at most 16 MiB; a remote report
  may make the server fetch at most 100 distinct links.
- Remote: each tool call runs under a budget of 60 connections, 64 MiB of bodies and 90 s, spent where sockets
  are opened (so retries, redirects, alternative sources and GitHub calls all count) and where bodies are read;
  past it a fetch fails (source unavailable) and the check's long loops stop with an error. brotli bodies are not
  decompressed there, and pdftotext's text is capped by `ulimit -f` on Linux and macOS.
- Remote: `pr:`/`ci:` look-ups pass only the API paths buddie asks for, with ASCII names, and only when the repo
  answers `private: false` under the very name asked for (a renamed repo is not followed) and a PR's base repo
  says the same.
- Windows: a file anchor's file is accepted only when the path of the opened handle (GetFinalPathNameByHandleW) is
  inside the repo, which closes the gap between the check and the open that #23 left there.
- Security: checking a report no longer runs code from the repository it names. A `fact=` anchor used to import and
  run that repo's `tools/anchors.py`; it is now always `UNCHECKABLE` (audit R1).
- Security: a file anchor `path#sha256` reads only a plain file inside the repo. An absolute path, a drive, `..`
  (with `/` or `\`), a symlink whose target is outside the repo, or a hard link is `UNCHECKABLE` and is not read.
  Before, `../x#sha` or `/etc/x#sha` hashed the file outside the repo, and a wrong hash printed 12 hex characters of
  the real one. On Linux and macOS each path part is opened without following symlinks, so a part swapped after
  the check is refused (audit R2).
- A number whose source could not be read (`SOURCE_UNAVAILABLE`) or whose value stood apart from the sentence's words
  (`NO_CONTEXT`) made a receipt `PASS` ("buddie PASS: numbers 0/1 found"). Both are now gaps and are listed under
  `gaps`. A quote or number verdict that verify does not know, for example from a newer verbatim, is a gap too,
  never a pass. Each verdict's meaning now sits in one table in `buddie/verify.py`, and a test keeps that table equal
  to the verdicts verbatim returns. Exit codes and blocking are unchanged: gaps never block.

## buddie 1.1.1 (2026-10-20)

- The `verbatim` skill no longer tells Claude to `pip install` buddie from git: inside the plugin it uses the plugin's
  own MCP tools (`snap`, `source_text`, `verify_report`), and outside it names one pinned PyPI release. Flagged by
  the plugin directory's listing check. A test keeps skills, commands and hooks free of unpinned installs and
  download-and-run launchers.

## buddie 1.1.0 (2026-10-20)

Ready for Anthropic's plugin directory. A fresh install now returns an answer only for what is false, the plugin has
listing fields, commands and a transcript switch, and an eval suite measures what the gate adds.

Measured with `claude plugin eval` (evals/, 2 runs per arm, Claude Opus 5.5): with the plugin the person got the truth
in every trap run (altered quote, `pr:` open-but-merged, `ci:` green-but-failed), without it in none of 6; the honest
control passed in both arms. The gate costs turns: 3.7 to 5 turns per run against 1, about twice the cost.

- **A `buddie:` line written before any check no longer covers what buddie finds false.** For a quote not on its
  page, an anchor or a number that does not hold, the line counts only after the hook has returned the text once,
  with what it found. Found by the plugin evals: an altered quote went out under "buddie: unverified" in 2 of 2 runs.
  An up-front line about what cannot be checked (a count made by hand, a missing anchor) works as before, and so
  does everything with `BUDDIE_STATE=0`.
- The skill and the MCP instructions say never to write a receipt line by hand; in the evals a model without the tool
  wrote one.
- **Safe defaults for a fresh install.** Without `buddie.toml` the hook returns an answer only for what is false: a
  quote not on its page, an anchor that does not hold. Before, every final answer without an anchor went back
  ("final answer has no anchor"), and the intro mode only came with `buddie init`. `final`, `prose` and the new
  `context` class (the 200k context rule) are off without `buddie.toml`; a project with `buddie.toml` keeps the
  full defaults, so existing setups behave as before.
- Slash commands: `/buddie:check [file or text]` checks a text now (the last answer by default), `/buddie:status`
  shows what is checked in this project and what the journal says, `/buddie:init` turns on the full checks. New CLI
  command `buddie status`.
- The final answer at `Stop` comes from the event's `last_assistant_message` first: Claude Code's docs say the
  transcript is written asynchronously and may not hold the turn's last message yet.
- Transcript reading can be turned off: the plugin option "Read the session transcript", `BUDDIE_TRANSCRIPT=0` or
  `[transcript] read = false`. Answers are still checked; `run:` anchors are then reported as unchecked.
- **Changed:** an ambient `GITHUB_TOKEN` is no longer picked up. buddie uses only a token given to it by name, the
  plugin's `github_token` setting or `BUDDIE_GITHUB_TOKEN` (in CI: `BUDDIE_GITHUB_TOKEN: ${{ github.token }}`).
- Listing fields for Anthropic's plugin directory in `plugin.json` (display name, icon, documentation, support and
  privacy links), a description by task, and a README that opens with what the plugin does and an example.
- A returned text starts with one plain line saying what buddie is and that only the listed items were judged, and
  ends with clearer fix instructions.

## buddie 1.0.1 (2026-10-20), verbatim 0.3.8

- Numbers in Russian sentences get their context: Russian words count, cut to a stem so case endings still match
  («постановления» finds «постановлением»), with Russian stop words. Before, only Latin words counted and every
  number of a Russian sentence came out `NO_CONTEXT`. English context words are unchanged.
- Clients without the skill get the quote and anchor format in the MCP instructions and tool descriptions; `EMPTY`
  is said not to be a pass.
- Pages in windows-1251 and other non-UTF-8 encodings are read in their own encoding: the Content-Type charset,
  `<meta charset>` / http-equiv, the XML declaration or a byte-order mark. Before, garant.ru's text became U+FFFD,
  and a page with Cyrillic in its first 4 KB was rejected as "binary body, not text", so no quote could be found.

## buddie 1.0.0 (2026-10-19)

First stable release: the receipt, the CLI, the MCP tools and `buddie.toml` follow semantic versioning from here on.

New places to run:
- Claude Desktop: an MCP Bundle (`manifest.json`, `.mcpb` built and attached to each release),
  `docs/install-claude-desktop.md`.
- Codex: plugin manifest `.codex-plugin/plugin.json` with the MCP server, the skills and a Stop hook; this repository
  is a Codex marketplace too. `docs/install-codex.md`.
- ChatGPT, claude.ai and the Claude API: a remote MCP server over Streamable HTTP (`buddie serve --http`) with a
  narrower tool set and a fetch guard (public addresses only, every redirect checked), a Docker image,
  `docs/deploy.md`.
- PyPI: `pip install buddie`, `uvx buddie serve`; release workflow with trusted publishing, MCP Registry entry
  `io.github.tsyyan/buddie` (`server.json`).

Changes:
- **Breaking:** the quote module is `buddie.verbatim` and its command `buddie-verbatim`. The top-level `verbatim`
  package and command clashed with an unrelated `verbatim` on PyPI.
- The final answer at `Stop` comes from the event's `last_assistant_message` when the transcript has none (Codex).
- `run:` against a transcript that is not Claude Code's is `UNCHECKABLE`, not a false `BROKEN`.
- `BUDDIE_DEFAULT_REPOS=none` stops `verify_report` from defaulting to the repo around the server's cwd.
- The Claude Code plugin asks for an optional GitHub token (`userConfig`, stored as a secret) instead of relying on
  `GITHUB_TOKEN` in the environment; an unset option is never sent.
- MCP tool annotations (read-only, non-destructive) for clients and directories.
- Development moved here from the private lab repository: this repository is the source of buddie, no longer an
  export. `PROVENANCE.json` moved to `results/` as the record of the last export (`lab@ed8d971`).
- CI: `apt-get update` before installing poppler-utils; tests import their sibling modules directly, so bare
  `pytest` collects them; jobs for the package, the bundle, the Docker image and the catalog manifests.

- Development moved here from the private lab repository: this repository is the source of buddie, no longer an
  export. `PROVENANCE.json` moved to `results/` as the record of the last export (`lab@ed8d971`).
- CI: `apt-get update` before installing poppler-utils; tests import their sibling modules directly, so bare
  `pytest` collects them.

## buddie 0.8.2 (2026-10-08)

- Fewer false returns for work claimed in prose. A word in a clause opened by once, as soon as, after, when, if,
  until, unless or before (Russian «когда», «если», «как только», «после того как», «пока не», «до того как»), within
  three words and no punctuation, is a condition or a plan, not a claim: «Once automerge has merged it, start the
  next row». «merged» after an article or possessive and before a noun is an adjective: «the merged code».
- At Stop, the last message is not checked for prose when the same turn already sent a final answer through a text
  tool (reply, post_message, send_message) that the gate let out: that text reaches no one. A reply the gate
  returned, or one sent in an earlier turn, does not count.
- In lab's journal since prose started blocking, these were 2 of 8 prose returns read from transcripts (false) and
  3 of 8 on Stop text after the reply had gone out.

## buddie 0.8.1 (2026-10-04)

- A bare anchor counts: after the anchor sign, without backticks, `path#sha`, `path@commit`, `fact=value`, `pr:…`,
  `ci:…`, `choice:…` up to the first space, `run:CMD => OUT` up to the end of the line, the next sign or a table cell
  border; before, only an anchor in backticks was found, and a report anchored the way the SKILL.md table shows was
  returned as "final answer has no anchor". Placeholders (`<…>`, `…`, `OWNER/REPO`, `CMD => OUT`) and a sign with no
  anchor after it are not anchors. On the 43 E017 gate rounds, offline: rounds with the sign returned for no anchor
  14 → 0.
- The return no longer offers a ready anchor from a call that has nothing to do with the claim: a command that opens by
  writing a file (a heredoc into `>` or `tee`, `sed -i`, `perl -pi`) or the `SubagentHandback` call itself.

## buddie 0.8.0 (2026-10-04)

- `buddie.toml` `[gates]`: each class of claims (`anchors`, `quotes`, `final`, `prose`, `numbers`, `work`, `summary`,
  `promises`) is `block`, `warn` or `off`. A warning lets the text out with a `systemMessage` naming what the gate
  found. `BUDDIE_GATES` overrides the file. Defaults change: work claimed in prose and numbers missing from their
  source warn instead of blocking or being only a gap; the subagent summary and the promise check are off.
- `buddie init` writes `buddie.toml` with the defaults and the intro mode: until 20 final answers have passed with no
  false return reported (`buddie intro --false`), nothing is returned, each would-be return is a warning.
  `buddie enforce` ends it.
- Windows: the hooks start through `hooks/run.sh` (`python3`, else `python`, else `py -3`); the hook reads its event
  as UTF-8 and writes UTF-8. CI runs the tests and a smoke run of the hook on recorded events on Linux, macOS and
  Windows, from a clone and from `pip install`.

## buddie 0.7.4 (2026-10-04)

- Defaults for other projects. Without a configured mark the final answer is the last assistant message at `Stop`,
  in any language; before, only text carrying the Russian mark `Следующий шаг:` was final, so the final-answer rules
  (an anchor required, no count or work claim in prose without one) never ran for anyone else. A project that hands
  in results through a tool names its mark as `final_mark` in `buddie.toml` `[mandate]` or in `BUDDIE_FINAL`; then
  text carrying it is final at any event. An empty `BUDDIE_FINAL` turns the rules off.
- The plugin's hook matches Claude Code's own tools only (`SendMessage`; `Agent` and `Task` for launches).
  Matchers for a project's reply and post tools and for cloud sessions moved to
  [`examples/hooks/projects.json`](examples/hooks/projects.json).
- The version in `pyproject.toml` and `CITATION.cff` is written from the code at export: the public tree carried
  0.6.0 under 0.7.3 code, and `test_one_version_everywhere` failed.

## buddie 0.7.3 (2026-10-04)

- The launch gate and the summary judge a row's verdict at the time of the check: a "not before <date>" condition
  comes due then, and a delay ("a day after the merge of №M") counts from the commit that brought the row's text.
  Without history (uncommitted edit, the bottom of a shallow clone) a delay does not come due.

## buddie 0.7.2 (2026-10-04)

- A launch with a basis is still returned (exit 2, outcome `taken`) when the row is already taken: `free: false` in
  the row's verdict of the merge comment on the PR merged as the anchor's commit, or the command `[launch] free`
  (`{n}` is the row) answering `free: false` now. Its reasons are printed. `BUDDIE_FREE=<command>` sets the command,
  `0` turns it off; without a comment and a command the gate lets the launch through (`free: null` in the journal).
- The launch hook's timeout is 60 s instead of 30 s.

## buddie 0.7.0 (2026-10-04)

- Launch gate (`buddie.toml` `[launch] tools`, off without the section): a launch of queue row N passes only with
  `⚓ NEXT.md@<commit>` whose queue gives N the verdict `auto`, or with `⚓ choice:<id>=№N`, the person's pick in the
  journal; otherwise exit 2 with a ready anchor when one holds. A launch with no row number passes.
- Promises: a text the gate let out is read for promises to launch a row (with a condition: a PR merged, a row done)
  and to send a summary; `SessionStart` prints the open ones, `Stop` returns the turn once per promise whose
  condition holds. A `buddie:` line drops a promise; promises expire after 48 hours.

## verbatim 0.3.7 (2026-10-04)

- `numbers` reads "млн", "млрд", "тыс.", "трлн" and the full Russian words after a number as million, billion,
  thousand, trillion: "$35.0 млн" is found on a page with "$35.0 million".
- A year the sentence itself calls absent ("not on the page", "не упоминается") is not looked up (`ABSENT`).
- A report on one's own work is not a claim about the page: numbers inside a `run:` anchor (command and output) and a
  snapshot timestamp next to its sha256 or a word like "snapshot" are not looked up.

## verbatim 0.3.6 (2026-10-04)

- `numbers`: a number missing from an abstract page (arXiv `/abs/`, an OpenAlex abstract) is `UNCERTAIN`
  (`abstract_only`); one missing from a market report whose forecast period on the page is later than the sentence's
  is `UNCERTAIN` (`rewritten`). buddie counts both as gaps, not blocks.

## verbatim 0.3.5 (2026-10-03)

- `check.readable` no longer takes for a document an Anubis check, a login page, an encoded payload or a redirect to a
  local address.
- `numbers` reads "2024 Jan 5", "10/09/2018" (both orders), thin-space thousands and tables "in thousands"/"in
  millions"; "from 12.3 million in 2020 to 16.2 million" is no longer a range.

## verbatim 0.3.4 (2026-10-03)

- `check.readable` no longer takes for a document a "Client Challenge", a captcha at the head of a long page, a
  JavaScript shell, or a redirect to the home page, to a section above the requested page or to a short page of
  another site; the `--access` cascade then goes on to the real page.
- `numbers`: a year counts as found only next to a word of its own clause; `cited_sentences` reads Gemini-style
  footnotes.

## buddie 0.7.1 (2026-10-04)

- A final answer that claims work in prose (merged, CI green, tests passed, ran) with no `pr:`, `ci:` or `run:`
  anchor on the same line is returned, with the ready anchors that hold now; a `buddie:` line does not let it
  through, only an anchor or dropping the claim does. Other messages only count such lines (`prose_work`); the
  receipt now also lists their numbers (`prose_lines`). A negated claim ("not merged yet", «ещё не слит») is not a
  claim. Found in our own dogfood: a thread answer stated four merges with no anchor and left.

## buddie 0.6.1 (2026-10-03)

- A line whose quote is FOUND on the page at a URL written on that same line carries its source: its numbers are no
  longer listed under `unanchored`, and a final answer is not returned for them as "number without anchor". The
  receipt lists such lines under `quote_backed`. A number without the URL on its line is still returned. Found on a
  correct report of the E016 pilot (three quoted revenue figures, quotes 3/3 found, returned anyway).

## buddie 0.6.0 (2026-10-03)

- Summary with a choice card: the hook counts live subagents (`SubagentStart`/`SubagentStop`), checks each
  subagent's last message, and on the orchestrator's `Stop` with none left asks once for a summary.
- `buddie summary` (CLI) and the MCP tool `summary`: what was done (receipt outcome), lost subagents, next steps with
  `auto`/`ask` verdicts, open PRs and red CI, and a ready `AskUserQuestion` card with at most three steps.
- The person's pick (`PostToolUse` on `AskUserQuestion`) goes to the journal; the anchor `choice:<id>=<step>` is
  checked against it and counts as consent in work claims.

## buddie 0.5.1 (2026-10-03)

- An anchor with the sign before the backticks (⚓ `path@commit`, as the skill used to show it) is now read like
  `⚓ path@commit`. Before, it was not parsed at all: a correct report counted as unanchored and was returned, and a
  broken `pr:`, `ci:` or `run:` anchor in that form went through unchecked. The skill and README show the sign inside
  the backticks.

## buddie 0.5.0 (2026-10-03)

The public tree had carried 0.4 and 0.5 code under the 0.3.0 version since the daily sync; this release names it.

- Numbers (0.4): numbers and dates in a sentence with a link are looked up in the snapshot of that link
  (`verbatim.numbers`). A number missing from its readable source is a gap by default; `--numbers fail` or
  `BUDDIE_NUMBERS=fail` makes it block, `off` turns it off.
- Closed loop (0.5): a returned message logs `reasons`; the next attempt logs `gate`, how it got through (proof,
  removal, disclosure, returned again). `SessionStart` prints the lessons of past sessions' journal (at most ten lines,
  `BUDDIE_LESSONS=0` turns it off). A return offers ready `pr:`, `ci:` and `run:` anchors that already hold.
  `buddie journal measure` and `buddie journal lessons`.
- Context gate: past `BUDDIE_CONTEXT_LIMIT` tokens (default 200000) a non-final reply is returned with a reminder to
  hand the result over and start the next step in a new thread.
- Snapshot stores: the hook judges web quotes against the snapshots the session took (`BUDDIE_STORES`,
  `VERBATIM_STORE`, stores named in the session's tool calls, `./.verbatim`), and fetches only URLs in none of them.
- A `buddie:` disclosure line no longer lets a broken `pr:`, `ci:` or `run:` anchor through: such an anchor states work
  that did not happen, so it must be corrected or removed.

## buddie 0.3.0 (2026-10-03), first public release

The repository `tsyyan/verbatim` became `tsyyan/buddie`; verbatim is buddie's quote module.

- Effect anchors `pr:`, `ci:` (GitHub API) and `run:` (session transcript); output the agent typed itself does not count.
- Work and mandate claims against a task queue (`buddie.toml`, opt-in).
- Repo anchors `path#sha256`, `path@commit`, `fact=value`.
- Receipt v0 (in-toto Statement), CLI, MCP server over stdio, Claude Code hook, plugin and marketplace.
- Results E009 (numbers) and E014 (Search Arena) added.

## verbatim

Each version was measured on reports it was not tuned on. Experiment folders are in `results/`.

## 0.3.3 (2026-10-02)

- Footnote markers inside quotation marks (`[1](url)`, `[2]`) are dropped before search.
- A truncated response body (`IncompleteRead`) is a failed fetch, not a crash of `check`.
- E014 in-sample recount: false `NOT_FOUND` 26 of 423 instead of 29; no agent error became a find.

## 0.3.2 (2026-10-02)

- Two replies of one speaker joined across the page's speech tag are found (`note: "speech_tag"`).
- The page's `[A]t` brackets and `___` blanks are normalized. Mojibake in the text layer is repaired before search.
- E012: none of 200 labelled agent errors became a find.

## 0.3.1

- New hints that mark an example before the quote marks: `like “`, `something like: “`, `might include: “`,
  `questions (“`. E011: 2 hits in 249 checked quotes, both correct.

## 0.3.0

- `NOT_A_QUOTE` verdict for words the report itself shows are not a quotation (`boilerplate`, `title`, `example`).
- Punctuation between words is ignored at the last normalization level.
- E010: false `NOT_FOUND` 5 of 147 (3.4 %).

## 0.2

- A quote is checked against its own link. A find under another link of the paragraph is `UNCERTAIN`.
- `UNCERTAIN` doubts and the access cascade (`--access`: browser, Wayback / Common Crawl, open access, copies).
- PDF via `pdftotext`, compressed bodies, cookie and bot gates are reported as `SOURCE_UNAVAILABLE`.

## 0.1

- `snap`, `text`, `check`: the content-addressed store, the visible-text layer and the quote search.
