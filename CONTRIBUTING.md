# Contributing

This repository is the source of buddie. Until 0.8.2 it was exported from a private lab repository, so older history
arrives in "Sync from lab" commits; from now on issues and pull requests here are where changes are made.

```bash
pip install -e . pytest
pytest            # bare pytest, as CI runs it; tests that need the lab's snapshots skip (set VERBATIM_LAB to run them)
```

- One change per pull request, with a test that fails without it.
- Add a line to the `Unreleased` section of `CHANGELOG.md`.
- The version lives in `buddie/__init__.py`; `pyproject.toml`, `CITATION.cff` and `.claude-plugin/plugin.json`
  carry the same number (`tests/test_version.py`).
- buddie checks claims without a model. A change that adds a model call to a verdict needs its own discussion first.
