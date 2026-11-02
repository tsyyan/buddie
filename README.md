# buddie usage stats

Weekly public adoption counters for buddie, appended by a scheduled task. This branch holds data only (no product code).

- `usage.csv`: one row per run. PyPI from pypistats.org (includes mirrors/bots); release downloads = sum of asset download_count; traffic = GitHub 14-day windows (clones inflated by CI checkouts); referrers as `name:uniques`.
- `release_downloads_mcpb` (Claude Desktop), `release_downloads_wheel_sdist` (.whl + .tar.gz), `release_downloads_plugin_zip`: install assets only, summed over all releases; `release_downloads_total` also counts notes, manifests and checksums.
- `ci_runs_14d`: GitHub Actions runs created in the last 14 days. Context for clones only: Claude Code and Codex marketplace installs clone this repo and are mixed with CI checkouts; there is no way to separate them.
- Claude Code / Codex marketplace installs have no public counter.
