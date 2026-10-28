# BDX-001 Lite — retained methodological record

Status: closed, inconclusive research; **not** product efficacy evidence or a production feature.

## Question
Whether permission-controlled structured environment observations from Buddie improve AI-agent system-specific recommendations relative to (A) no diagnostics and (B) a bounded diagnostic shell.

## What was done
A three-arm smoke experiment with nine recorded runs (three per arm), a deterministic evaluation harness, stored evidence and manual adjudication. The host/model execution path injected host-environment information into every experimental arm, so treatment and control were confounded. No conclusions about superiority or H1–H3 can be drawn. This record deliberately retains no raw results, system snapshots, profile paths, prompts or personal identifiers.

## Lessons for future work
- Isolate agent execution from ambient system prompts, host settings, hidden tools and account context; prove parity and absence of cross-arm contamination before spending on runs.
- Pre-register criteria, ground truth, outcome labels, sampling and failure exclusions.
- Separate deterministic evaluator findings from blinded manual review; audit false positives.
- Include provenance for tool outputs and their age; distinguish reported, observed and inferred facts.
- Conduct privacy review *before* any public experiment commits; sanitize both current files and full git history where necessary.
- Treat pilot counts as descriptive; do not advertise an effect size or reliability benefit from this experiment.

## Historical privacy caution
The original PR #56 branch history included personal profile-path material in earlier commits even after later redaction. Closing a PR or deleting a branch does not guarantee remote Git objects, PR refs, caches, forks or clones are purged. A separately reviewed cleanup strategy and GitHub support may be required; no claim of historical erasure is made.

Future experiments require an explicit fresh protocol and approval for paid runs. This document is the intentionally minimal retained summary.
