# buddie usage stats

Weekly public adoption counters for buddie, appended by a scheduled task. This branch holds data only (no product code).

- `usage.csv`: one row per run. PyPI from pypistats.org (includes mirrors/bots); release downloads = sum of asset download_count; traffic = GitHub 14-day windows (clones inflated by CI checkouts); referrers as `name:uniques`.
- Claude Code / Codex marketplace installs have no public counter.
