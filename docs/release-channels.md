# Public release delivery and promotion governance

Candidate creation, manual publication approval and distribution-branch promotion are separate operations.
`plugin-stable` is generated output, never a source for development. Do not merge fixes onto it.

## Before the first plugin-stable promotion

The owner must configure two active branch rulesets targeting exactly `refs/heads/plugin-stable`:

1. Deletion and non-fast-forward restrictions with **no bypass actors**.
2. Creation and update restrictions whose sole bypass actor is the GitHub Actions integration (app 15368,
   `always`). This limits writes to the workflow; the workflow separately validates the approved candidate.

The `pypi` environment must have required human reviewers and disable administrator bypass. Configure these
settings separately from this code change. A read-only check runs in `plugin_promote.py` before any GitHub
promotion; missing settings or API access stop it. The workflow token needs read access to rulesets and the
environment as well as its existing publication permissions. Do not weaken the policy to bypass a 403.

An explicit Git lease guards the exact previous head (including absence); the constructed commit is a direct
child of that head, so the lease does not authorize rewriting history. Multiple push destinations are refused.
The package is rebuilt from the source revision before promotion. The idempotent path verifies both the tree
and all provenance trailers. Existing installed-plugin validation and smoke checks still follow the push.

Observed on 2026-10-26: no applicable plugin-stable branch rules were returned by GitHub. The pypi environment
had a required reviewer and administrator bypass disabled. **Promotion remains blocked** until the branch
rules and workflow token access are independently confirmed. This change does not configure settings.

## MCPRush

Read endpoints: [listing JSON](https://mcprush.com/api/servers/buddie-mcp),
[listing versions](https://mcprush.com/tsyyan/buddie-mcp#versions),
[documentation](https://mcprush.com/docs), [discovery index](https://mcprush.com/llms.txt).

Prior investigation observed a local/direct PyPI source (`buddie`) and empty release notes for 2.0.1.
The current read attempt returned HTTP 403; those earlier observations are historical, not a fresh delivery
claim. No verified writer API or automatic import of GitHub release descriptions has been established for
this listing. No writer API is implemented.

Manual update process, after separate release authorization:

1. Publish the approved candidate through existing channel gates. Do not replace PyPI 2.0.1.
2. Open the owner's existing MCPRush Studio listing. Confirm it remains local/direct and points to PyPI
   `buddie`; do not create a duplicate listing or change its source.
3. If Studio offers version-specific release text for this listing, paste the candidate's exact public
   release notes for the corresponding version. If it does not, stop and ask MCPRush support to confirm the
   supported update procedure. Do not assume gateway publishing controls apply to direct PyPI imports.
4. Observe the public page and API again. Save the response with observation time and candidate digest;
   distinguish generated, packaged, published, observed, missing, different and unknown.

`python scripts/check_release_channels.py --version VERSION --notes rc/metadata/release-notes.md` only sends
a public GET. It exits nonzero for unavailable, unrecognized, stale, missing or changed metadata. Saved JSON
can be checked using `--snapshot FILE`; this is explicitly labeled historical evidence. A transformed notes
format requires a reviewed adapter, not silent success. No account messages or updates are sent by this check.
