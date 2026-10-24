# Publication authorization: confirmed gap and unapplied proposal

> **Status, 2026-10-24, later:** the workflow part of this proposal is applied, exactly as reviewed, by the follow-up
> pull request on branch `release-unified-approval-gate`: `authorize` names environment `pypi`, nothing else in
> `release.yml` changed. `tests/test_maintenance.py` proves the live workflow is the reviewed base
> (`workflow_sha256_lf` in [source.json](proposals/source.json)) plus that one line, and
> `tests/test_release_authorization.py` evaluates every run mode. **The environment settings below are still not
> applied**: until the owner configures reviewers, bypass and the tag rule, naming the environment approves nothing.
> The rest of this page is the record of the proposal as it was reviewed; its "NOT APPLIED" wording describes main at
> `0f29c19`.

## Verified final implementation

Inspected merged main `0f29c19430b764884eb057a16a3c84676b066698`:
[release.yml](../../.github/workflows/release.yml), [release_publish.py](../../scripts/release_publish.py)
and [release_manifest.py](../../scripts/release_manifest.py). These files are unchanged by PR #39.

`authorize` runs only for a manual dispatch with a candidate run ID. It validates the release tag, version,
main ancestry, exact confirmation text, successful candidate run identity and the artifact manifest/digests.
Every publishing job depends on its success. This is a candidate-integrity gate, not a human-approval gate:
the job currently names no environment and the script does not verify a human deployment review.

Only the `pypi` job names environment `pypi`. The registry and GitHub jobs explicitly allow
`needs.pypi.result == 'skipped'`. With `only=mcp-registry` or `only=github-release`, valid authorization inputs and
matching files already on PyPI, that recovery path can write without passing a protected environment.
Current `pypi` protection rules are empty, so even the normal PyPI path has no reviewer today.
Typing `confirm` is useful intentional input, but is not an independent approval boundary.

## Smallest proposed change (NOT APPLIED)

Add one property to the existing job:

```yaml
  authorize:
    environment: pypi
```

The [reviewable patch](proposals/authorize-environment.patch) inserts only that line; it introduces no job,
script, permission, new environment or duplicated authorization implementation. The existing `pypi` job keeps
its environment, preserving the PyPI trusted-publisher binding. Candidate-only builds remain unprotected and
nonpublishing. Manifest checks, candidate identity checks, SHA-256 verification and idempotent recovery stay intact.

Configure and verify the `pypi` reviewer and tag policy first. Adding an environment name by itself is not a
protection: without required reviewers it still allows automatic execution. Keep administrator bypass disabled.
Use the already proposed tag-only `v*` deployment policy, not protected-branches-only.

| Run mode | Existing behavior | With patch AND configured environment |
|---|---|---|
| Tag push / manual candidate only | Builds candidate, publishes nothing | Unchanged; no authorization job runs |
| `only=all` | authorize, then PyPI; registry/GitHub after PyPI | authorize waits for approval; PyPI may prompt again |
| `only=pypi` | authorize, then PyPI | authorize waits for approval; PyPI may prompt again |
| `only=mcp-registry` | PyPI skipped; registry can publish | authorize must be approved and succeed before recovery |
| `only=github-release` | PyPI skipped; GitHub can publish | authorize must be approved and succeed before recovery |

If authorization is rejected, cancelled, skipped or fails, no publishing stage satisfies its dependency and
success condition. The `always()` recovery conditions explicitly require `needs.authorize.result == 'success'`.
Rerunning a failed job within the same approved run can rely on its earlier approved authorization; this proposal
does not promise a fresh human review for every individual retry. Each new publishing workflow dispatch must pass
the gate. It also does not retrofit workflow YAML in existing immutable tags: inspect the workflow at the selected
tag before approving any historical rerun.

## Consequences and owner choices

- Solo maintainer: reviewer `tsyyan`, self-review allowed, administrator bypass off. This is an explicit manual
  checkpoint under the owner's identity, not two-person approval. An agent using that same identity cannot be
  distinguished from the person by this setting alone.
- Independent reviewer: select an actual other user with access and enable prevention of self-review. Do not
  select only the deploying owner with self-review forbidden: that configuration locks out publication.
- Normal publication may require two approvals because both jobs use the environment. That small operational cost
  avoids changing the PyPI OIDC binding or introducing a new gate environment. If one prompt is required, design a
  dedicated shared approval environment separately; do not silently remove the PyPI environment.
- GitHub enforces environment reviewers/ref restrictions, dispatch permissions, dependency scheduling and tag/main
  rules. Buddie's scripts enforce candidate and artifact identity, digests, version/tag consistency and safe recovery.
  Administrators can still edit the rules themselves; no proposal protects against a malicious account owner.

## Offline validation and approval sequence

`tests/test_maintenance.py` applies the patch only to a temporary copy and proves it changes exactly one property,
keeps the candidate and publishing jobs unchanged, and routes all three publishers through the protected authorizer.
Existing release/manifest tests exercise invalid candidates, artifact tampering and partial-publication recovery
without real publication. These are structural/offline checks; they cannot prove a GitHub reviewer is configured
or that the hosted approval UI rejects an unapproved run.

1. Review this proposal and its duplicate-prompt consequence independently.
2. Separately approve and apply reviewer, ref and bypass settings; read the values back from GitHub.
3. Separately authorize a narrowly scoped workflow follow-up applying this patch and its checks. No such change is
   applied in PR #39. No automatic workflow dispatch is part of proposal validation.
4. Before any future tag or publication, verify the reviewed workflow commit and environment settings. Exercise
   approval during the owner-approved release process, not by publishing a test release from this maintenance task.
