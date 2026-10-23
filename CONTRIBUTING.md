# Contributing

For installation and usage, see the [documentation index](docs/README.md). Report ordinary bugs and request
features in [Issues](https://github.com/tsyyan/buddie/issues); use synthetic reproductions and redact private data.
For vulnerabilities, follow the [security policy](SECURITY.md) before sharing details.

This repository is the source of buddie. Until 0.8.2 it was exported from a private lab repository, so older history
arrives in "Sync from lab" commits; from now on issues and pull requests here are where changes are made.

```bash
pip install -e . pytest
pytest            # bare pytest, as CI runs it; tests that need the lab's snapshots skip (set VERBATIM_LAB to run them)
                  # Windows: `python -m pytest`; the Python install manager's pytest.exe shim can leave the test
                  # process without a usable stdin (docs/release-hardening.md, RH-1)
```

- One change per pull request, with a test that fails without it.
- Add a line to the `Unreleased` section of `CHANGELOG.md`.
- The version lives in `buddie/__init__.py`; `pyproject.toml`, `CITATION.cff` and `.claude-plugin/plugin.json`
  carry the same number (`tests/test_version.py`).
- buddie checks claims without a model. A change that adds a model call to a verdict needs its own discussion first.
- Claude Code opened in a clone of this repository loads its `.mcp.json` as a project MCP server. That file is the
  plugin's: `${CLAUDE_PLUGIN_ROOT}` is set only for an installed plugin, so in a clone the server starts `/run.py` and
  fails (`/mcp` shows it failed). Disable it for the project there, or add your own server with
  `python3 /path/to/clone/run.py serve`. The plugin itself is not affected (docs/integrations.md, finding 6).
