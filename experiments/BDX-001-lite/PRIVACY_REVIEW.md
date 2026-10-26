# BDX-001 privacy review — 2026-10-26

Scope: all data artifacts in the seven original PR commits, including `b3d3b41aab56d8fd1815f1cf1071993f119cb2bb`,
raw fixtures, run JSON, event JSONL, blind packet and automatic evaluations. Matched values are not reproduced here.
The model host-context injection also included account context; absence of an email in saved outputs does not
prove the model did not receive it. The original leak probe explicitly records that confound.

At original head `35545e362bfd01d840d085d598ef685b354ac5cf`, profile paths in result data have generic placeholders.
Heuristic scan found personal profile-path matches in 17 files in `b3d3b41`, and none in data at the other six
original PR commit trees. Common email/token patterns found no matches. These bounded checks are not a complete
secret audit; `evaluation/privacy_scan.py` reproduces the scan without printing values. `you` paths are synthetic
examples in model answers, distinct from the recorded host profile. Code/test regex examples are outside that scan.

Safe forward changes: the writer now scrubs profile segments independently of the current host name, nested JSON,
email and common credential patterns plus actual credential-like environment values before saving and status
printing. Regression tests use synthetic values. Existing sanitized run evidence and historical digests are
retained. No additional live model calls or collection was performed.

## Public-history risk and plan requiring separate approval

The original commit remains reachable in this PR's ancestry. A forward redaction does not erase old blobs.
**Squash merge does not remove them from GitHub**: commit URLs, PR refs, cached diffs, forks and existing clones may
retain the original data. No public history, remote branch or artifact was rewritten/deleted in this audit.

If the owner wants removal beyond the safe current tree: inventory affected commits/PR refs, preserve an access-
restricted forensic record, prepare a cleaned branch/history in a separate local copy, review exact affected refs,
obtain explicit approval, then coordinate the rewrite and GitHub cached-view/PR-ref removal with GitHub Support.
Notify collaborators to avoid reintroducing old objects. Purging copies outside the owner's control cannot be
guaranteed. Credential rotation is required if a later audit finds credentials; this scan found profile paths,
not confirmed credentials. Do not describe a squash, branch deletion or successful rewrite as complete erasure.

This residual historical privacy risk must be accepted explicitly in the merge decision; passing CI does not
resolve it. Do not block safe forward sanitation while awaiting that separate decision.
