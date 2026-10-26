# GitHub citations: implementation validation (2026-10-26)

Base: `0bc048e7439ac283409fdfd05f763a506a95888a`. Runtime: Linux container, CPython 3.12.14, uid 0.

## Automated checks

- `python -m pytest tests/test_github_sources.py tests/test_github_report.py -q`: **60 passed**.
- Final `python -m pytest -q`: **1411 passed, 52 skipped, 2 failed**. The two failures also occurred in the baseline
  run before production changes; they are not hidden or counted as passes:
  - `tests/test_environment.py::test_no_environment_variable_user_or_local_path_is_in_a_snapshot`: the current user
    is named `root`, so the assertion mistakes the JSON schema key `"root"` for disclosure of the username.
  - `tests/test_policy.py::test_a_file_of_this_user_is_not_protected_even_read_only`: the test expects a file owned
    by this user not to be root-owned; in this container the user is root, so protection validation instead reports
    a writable `/tmp` ancestor. The container denied `runuser`'s attempt to set groups, so no non-root rerun is claimed.
- `git diff --check`: clean. Python compilation of the new modules succeeded.

The suite includes regression tests for modified code extraction, literal punctuation/case/indentation, CRLF versus
lone CR, source scope, wrong diff sides/kinds, gaps across hunks, incomplete patches, missing description fields,
offline snapshot hash/scope checks, supplied callback/store provenance, remote endpoint allowlists and private
repository rejection. These tests do not establish completeness over arbitrary Markdown or all GitHub diff formats.

## Live API smoke checks

Using the implemented resolver and existing GitHub GET client (not the deployed MCP plugin):

1. File at the base revision, `buddie/core.py`: inline excerpt `class Fact(str, Enum):` returned FOUND at line 44.
2. PR #54, first added line of `docs/design/modularity/ARCHITECTURE_AUDIT.md`: diff fence returned FOUND on R1,
   kind added, base/merge-base `0bc048e7439ac283409fdfd05f763a506a95888a`,
   head `5978facc19312bf0c792a8a1324feaa0d7439dcd`.

These checks establish source-resolution smoke behavior at observation time, not semantic correctness of PR #54.

## Independent review and decisions

A separate reviewer examined the adapter, extraction, receipt integration, remote paths and new tests. Three
Important findings were reproduced RED and then fixed GREEN: adjacent preceding citations losing ambiguity,
lone CR becoming LF, and fence source binding crossing a heading without a blank line. No minor findings were
reported. The CR fix also covers literal prose quotes. No second independent review is claimed after these fixes.

The review's mechanical receipt was `buddie EMPTY: nothing to check`: it had no source anchors and cannot itself
prove a code review correct. Acceptance rests on the examined code and reproducing regression tests.

An additional privacy test reproduced local private-bundle replay through a remote request. The public server now
disables saved GitHub-source replay; it requires a live public-repository check instead. Local replay remains
available. This restriction is documented in the design and user guide.

Engineering choices: full-SHA files only; syntactic citation binding; no interpretation of prose verbs; unsupported
or incomplete source shapes flag gaps. Expanding these choices later requires new tests, not a broader PASS claim.
No semantic-verification, general Markdown completeness, release, deployment or merge is claimed by this change.
