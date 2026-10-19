# Releasing buddie

A release is a pushed tag `vX.Y.Z` equal to `buddie.__version__`. [`release.yml`](../.github/workflows/release.yml)
then:

1. checks that the tag matches the code, builds the sdist and the wheel, runs `twine check --strict`, installs the
   wheel into a clean venv and runs `buddie --version` and `buddie-verbatim --help`;
2. packs the Claude Desktop bundle `buddie-X.Y.Z.mcpb` (when `manifest.json` is present);
3. publishes to PyPI by trusted publishing: GitHub proves to PyPI which workflow is asking, so no PyPI token is
   stored anywhere;
4. creates the GitHub Release `vX.Y.Z` with the `CHANGELOG.md` section `## buddie X.Y.Z` as notes and the sdist,
   wheel and `.mcpb` attached.

## One-time setup (the repository owner)

**PyPI.** Sign in at pypi.org → Your account → Publishing → *Add a new pending publisher* (the project does not exist
yet, so it is "pending"):

| Field | Value |
|---|---|
| PyPI Project Name | `buddie` |
| Owner | `tsyyan` |
| Repository name | `buddie` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

**TestPyPI** (optional, for a dry run): the same at test.pypi.org, with environment name `testpypi`.

**GitHub.** In tsyyan/buddie → Settings → Environments, create `pypi` and `testpypi`. Adding yourself as a required
reviewer on `pypi` makes every PyPI upload wait for your click.

## Cutting a release

1. Bump the version in `buddie/__init__.py`, `pyproject.toml`, `CITATION.cff`, `.claude-plugin/plugin.json` and
   `manifest.json` (`tests/test_version.py` and `tests/test_manifest.py` fail until they agree).
2. Rename `## Unreleased` in `CHANGELOG.md` to `## buddie X.Y.Z (YYYY-MM-DD)`.
3. Merge to `main` with CI green.
4. Optional dry run: Actions → release → Run workflow (target `testpypi`), then
   `pip install -i https://test.pypi.org/simple/ buddie==X.Y.Z`.
5. Tag and push:

   ```bash
   git tag vX.Y.Z
   ```

   ```bash
   git push origin vX.Y.Z
   ```

A version on PyPI can never be uploaded again, even after deleting it. If something is wrong after the upload,
release `X.Y.Z+1`.

## Installing from PyPI

```bash
pip install buddie
```

Without touching the current environment:

```bash
pipx install buddie
```

```bash
uvx buddie verify report.md
```

The MCP server for clients that start a command: `uvx buddie serve` (stdio). The package installs one module,
`buddie`, and two commands, `buddie` and `buddie-verbatim`.
