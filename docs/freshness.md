# Evidence freshness

Evidence can be genuine and still not apply to the claim it is offered for. CI passed on commit A; the agent pushed
commit B; "the PR passed CI" now rests on a result for A. buddie's `ci:` anchor checks that the checks on the SHA the
text names ended as it says, which they did. Freshness asks the other question: **is that evidence bound to the
revision the claim is about?**

## Design

Three separate answers, never folded into one:

| | Question | Where |
|---|---|---|
| validity | was the evidence obtained from an acceptable source, and is it well formed | provenance (`core.Provenance`), the checks themselves |
| **freshness** | is the evidence bound to the target revision being evaluated | `buddie/freshness.py` |
| age | how long ago it was observed or produced | timestamps, reported, never used to decide freshness |

### States

| State | Means |
|---|---|
| `CURRENT` | the evidence is bound, by an immutable identifier buddie observed, to the target's revision |
| `STALE` | the evidence is bound to a different revision of the same target: it may be genuine, it does not apply |
| `UNKNOWN` | the target's revision or the evidence's could not be established from trustworthy information |
| `NOT_APPLICABLE` | revision binding means nothing for this evidence (reserved; no supported kind returns it today) |

`CURRENT` does not mean the CI passed, and `STALE` does not mean it failed: the CI outcome is reported beside the
freshness state, as its own answer. `UNKNOWN` is never treated as `CURRENT`. Old evidence is not `STALE` for being
old, and recent evidence is not `CURRENT` for being recent.

### The comparison (pure)

`freshness.assess(target, evidence)` takes two bindings, each a repository, a revision (or none, with the reason)
and how the revision is known, and returns the state with one reason code:

1. The target's revision is missing: `UNKNOWN` (`target_unresolved`).
2. The evidence's revision is missing: `UNKNOWN` (`evidence_unresolved`).
3. Either revision is not a full commit id (40 or 64 hex): `UNKNOWN` (`not_immutable`). A branch, a PR number or an
   abbreviated SHA is not an identity.
4. The repositories differ: `UNKNOWN` (`different_repository`). The same SHA string in two repositories is not one
   revision.
5. The evidence's revision was not observed by buddie (handed in by the caller, or a binding buddie did not make):
   `UNKNOWN` (`evidence_not_observed`). A PR head target must be resolved by buddie too (`target_not_resolved`);
   a commit target may be the caller's: it is the claim being evaluated (a historical claim about A).
6. Equal: `CURRENT` (`same_revision`). Different: `STALE` (`different_revision`).

Bindings buddie makes are recognised by identity (as `effects.own_get` recognises buddie's GitHub GET), not by a
field: an object a caller builds with `provenance="collector_observed"` is a caller's statement.

### Supported evidence

| Target | Evidence | Revision identity used |
|---|---|---|
| a commit (`--commit SHA`), including a historical one | GitHub CI on a commit | the target: the claim's full SHA. The evidence: the full SHA GitHub resolves the evidence ref to (`/commits/{ref}`), checked against every check run's `head_sha` and the combined status's `sha` |
| a PR's current head (`--pr N`) | GitHub CI on a commit | the target: `head.sha` of `/pulls/N` now, from the repository asked for (`base.repo.full_name`) |
| a commit | the local repository now | `git rev-parse HEAD` (buddie/runner.py), with the working tree: a clean tree at that commit is `CURRENT`, another commit `STALE`, a dirty or unreadable tree `UNKNOWN` |
| a recorded artifact digest | the file now | the sha256 buddie reads now (environment.artifact) |

The local repository and its files are the agent's to write: their bindings are buddie's observations of
agent-writable state (`basis: agent_writable`), as in environment snapshots, not attestations.

### Trust boundaries

- **What buddie observed.** A binding counts as buddie's observation only when `freshness.py` made it
  (`observed()`, by identity). This is a boundary for data, not a sandbox, and it is not cryptographic: whatever
  arrives as data (a Binding built from fields, a copy, a pickle, a JSON document, the CLI's arguments and files)
  is never taken for an observation, but Python code running in the same interpreter can register a Binding of its
  own (`freshness._observed`) as it can replace `github_get`. The guarantee holds at the CLI and for callers who hand
  buddie data, not code. Its `provenance` then says how far its source is known: `collector_observed` for
  buddie's own GitHub GET to the default API or the protected policy's `github_api`, over a network nothing in the
  environment stood in; `unknown` for an API the environment named (`BUDDIE_GITHUB_API`, which a project can set)
  or a GET function a caller handed in; `agent_writable` for the local repository and its files.
- **What the caller says.** A commit target is the claim itself, so it may come from the caller (`claimed()`).
  Evidence may not: a caller cannot vouch for which revision its evidence is bound to. A PR head may not either:
  it must be resolved now.
- **GitHub's answers are checked against each other.** The evidence ref must resolve to a commit that starts with
  it (a branch or tag named like a SHA prefix and pointing elsewhere is `ambiguous_reference`); every check run's
  `head_sha` and the combined status's `sha` must be that commit (`inconsistent_answer` otherwise); the PR's
  `base.repo.full_name` must be the repository asked for. Anything malformed resolves nothing (`malformed_answer`).
- **The protected policy.** `network = "forbidden"` asks GitHub nothing (`network_forbidden`); `collector =
  "isolated"` applies to its requests as to the hook's; `github_api` chooses the API. No policy key was added.
- **No relabelling, no editing.** Results and bindings are frozen, and so are a binding's `details`, all the way
  down (read-only mappings and tuples, copied when the binding is made). `render()` computes every state again from
  its bindings and every CI summary again from its runs and statuses, refuses a result or summary set by hand, and
  returns new plain objects: a document shares nothing with the evidence it was made from.

## Which CI results count

GitHub is asked for the latest run of each check in each check suite (`filter=latest`, said explicitly), so a re-run
replaces the attempt before it, and for the combined status, which is the latest per context. Check runs and
statuses stay apart, even under one name. What GitHub does not say is which of two check suites on one commit counts
(two workflows that both run `test`, one workflow on `push` and on `pull_request`, an older run cancelled when a
newer one started). buddie does not guess:

| Outcome | When |
|---|---|
| `pending` | a run or status is not done |
| `ambiguous` | one check name (or status context) has a run that ended well and one that did not: which counts cannot be told |
| `success` | every run ended success, neutral or skipped, and every status success |
| `failure` | otherwise (cancelled, timed out, action required, error) |
| `none` | no run and no status: no evidence (`no_ci_results`), never a success |

Names found in more than one suite are listed (`duplicates`) and printed, also when their results agree.

## Using it

```bash
buddie freshness ci --repo OWNER/REPO --pr 34 --evidence f2ab90e
buddie freshness ci --repo OWNER/REPO --commit FULL_SHA --evidence f2ab90e --check "test (3.11)"
buddie freshness repo --commit FULL_SHA [--root DIR] [--artifact dist/app.whl=SHA256 ...] [--snapshot snap.json]
```

`--json FILE` writes the freshness document (`freshness-v0`: each result's state, reason, and both bindings with
their revision, provenance, whether buddie observed them, why one is missing, when it was observed, and for CI the
check runs, statuses and outcome).

| Exit | Means |
|---|---|
| 0 | every result `CURRENT` |
| 1 | a result `STALE`: the evidence is for another revision |
| 3 | a result `UNKNOWN` (or `NOT_APPLICABLE`): the target or the evidence could not be established |
| 2 | the input cannot be used: no repository, a branch for `--commit`, `--pr` and `--commit` together, an inconsistent snapshot |

The exit code is about freshness only. A CI result that failed on the right commit is `CURRENT` and exits 0: its
outcome is printed beside it ("CI on the evidence's commit: failure (not a freshness answer)"). `buddie verify`'s
exit codes are unchanged.

Python: `freshness.assess(freshness.resolve_pr_head(repo, n, github_get), freshness.ci_evidence(repo, sha,
github_get))`, `freshness.claimed("commit", repo, sha)` for a commit target, `repository_now(root)`,
`artifact_now(root, path)` with `assess_artifact(recorded, now)`, and `render`, `dumps`, `line`.

## Examples

**CI passed on A, the PR now points to B.**

```
$ buddie freshness ci --repo acme/app --pr 7 --evidence aaaaaaa
freshness STALE (different_revision): the evidence is for aaaaaaaaaaaa, the target is bbbbbbbbbbbb; CI on the evidence's commit: success (not a freshness answer)
```

Exit 1. The green result is genuine and was for A; it says nothing about B.

**Historical CI evidence for A.** "Commit A passed CI" is a claim about A, and CI for A applies to it, however far the
branch has moved since:

```
$ buddie freshness ci --repo acme/app --commit aaaa…aaaa --evidence aaaaaaa
freshness CURRENT (same_revision): both aaaaaaaaaaaa; CI on the evidence's commit: success (not a freshness answer)
```

**Current CI with a failing conclusion.** `freshness CURRENT (same_revision) …; CI on the evidence's commit: failure`:
exit 0. The evidence applies, and what it says is a failure.

**Missing GitHub evidence.** No check run or status on the commit: `freshness UNKNOWN (evidence_unresolved):
no_ci_results`, exit 3. GitHub unreachable: `github_unavailable`; no such commit or PR: `not_found`; the policy forbids
the network: `network_forbidden`. None of them is a success, and none is a mismatch.

**A dirty tree.** `buddie freshness repo --commit A` in a checkout at A with an edited file: `UNKNOWN
(evidence_unresolved): dirty_worktree`. The same HEAD with other files beside it is not A's state.

## Relation to receipts and the hook

Receipts are unchanged. Freshness is a separate document, not a receipt-v1 outcome (`STALE` is not added to its
enum), no receipt rendering computes it, and choosing receipt-v1 asks GitHub nothing more. A `ci:` anchor in a
receipt still says whether the checks on the SHA it names ended as it says; freshness says whether that SHA is the
one a claim needs. The hook is unchanged: it does not know which revision an answer's claim is about unless the
answer says so, and the anchor grammar was not extended.

## Outside the threat model

- GitHub's own answers: buddie checks them against each other, not against GitHub.
- An API the environment names: its answers are taken and marked `unknown`; under a protected policy, `github_api`
  decides the API.
- The local repository and its files: the agent can write them; a `CURRENT` there means buddie saw that commit,
  clean by git's view, and those bytes, at that time.
- What happened between two observations, and whether a commit's code is right.
- No expiry by age: nothing here justifies one. Not on MCP: a freshness check asks GitHub about a repository the
  caller names, and local repository state is not handed to an agent's tools without its own review.
