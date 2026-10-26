# MCPB build dependency review, 2026-10-26

The existing workflow pins `@anthropic-ai/mcpb@2.1.2`. npm reports 2.1.2 as the current version. A fresh
`npm install --package-lock-only --ignore-scripts` and `npm audit --json` found seven affected package nodes:
four high and three low (including inherited parent effects, not seven independent vulnerabilities).
The audit was performed outside the repository and did not change the project's dependencies.

| Dependency | Advisory | Assessment before authorization |
|---|---|---|
| node-forge | [GHSA-86w9-cpqp-85rv](https://github.com/advisories/GHSA-86w9-cpqp-85rv), affected through 1.4.0 | Audit reports no compatible fix. Do not claim signatures are safe based on this CLI. Obtain an upstream fix and retest signing/verification before using those functions. |
| tmp through external-editor / inquirer | [GHSA-ph9p-34f9-6g65](https://github.com/advisories/GHSA-ph9p-34f9-6g65), below 0.2.6; [GHSA-52f5-9888-hmc6](https://github.com/advisories/GHSA-52f5-9888-hmc6), through 0.2.3 | Prefer a lockfile resolving tmp >=0.2.6; validate CLI noninteractive pack/unpack and all platforms. |
| zod | [GHSA-mrhx-c7xc-m3w5](https://github.com/advisories/GHSA-mrhx-c7xc-m3w5), below 4.6.6 | MCPB declares Zod 3; overriding to major version 4 without upstream compatibility tests is unsafe. Track the upstream migration or backport. |

The candidate build currently validates and packs repository-controlled files and unpacks its own freshly
built bundle; it does not ingest arbitrary third-party bundles or use MCPB certificate signing. This limits
the reviewed exposure but is not proof that every vulnerable dependency path is unreachable. Python runtime
packages do not install npm/MCPB dependencies; the advisories concern build tooling.

Release authorization remains blocked pending an owner decision accepting these bounded residual build
risks or a reviewed dependency update with a reproducible lockfile and successful CLI/clean-install tests.
Do not apply `npm audit fix --force` or silently replace the pinned tool in a release run. Candidate creation
can continue for review; it does not authorize publication or distribution-branch promotion.

## Verification incident

During this task a regression test mistakenly changed a synthetic fixture's remote to the real repository.
It created `plugin-stable` at `ad433741279857a65d653ac50789d5464d8ee973`, outside the authorization boundary.
The branch was immediately removed using an exact-head lease for that commit; a subsequent remote listing
confirmed absence. No release tag, package publication or Directory change was made. The corrected test
keeps the actual remote a local bare repository and substitutes only the remote-URL query. Future review
must inspect test network destinations before exercising a refusal path. This incident is not an approved
promotion or evidence that branch protections are configured.
