# Catalog listings

Where buddie can be listed, what is ready in this repository, and what only the owner can do: accounts, forms and the
data-handling answers. Nothing here is submitted automatically, except PyPI and the MCP Registry, which follow a
release tag ([release.md](release.md)).

| Catalog | Ready here | Owner's step | Needs a hosted server |
|---|---|---|---|
| PyPI (`buddie`) | `pyproject.toml`, `release.yml` | one-time trusted publisher, then a tag | no |
| MCP Registry (`io.github.tsyyan/buddie`) | `server.json`, `mcp-name` line in README, job in `release.yml` | none: GitHub OIDC proves the namespace | no |
| Anthropic's directory: plugin for Claude Code and Cowork | `.claude-plugin/`, README, LICENSE, `claude plugin validate` in CI | submit at claude.ai/directory/manage | no |
| Anthropic's directory: MCP connector for claude.ai | `buddie serve --http`, Docker image | deploy, then submit the URL | **yes** |
| Claude Desktop | `.mcpb` attached to each GitHub Release | share the release link; check the portal for a desktop-extension listing | no |
| Codex marketplace (this repository) | `.claude-plugin/marketplace.json`, `.codex-plugin/plugin.json` | none: `codex plugin marketplace add tsyyan/buddie` works once the repo is public | no |
| OpenAI's plugin directory (ChatGPT and Codex) | template in `integrations/chatgpt/` | deploy, put the URL in `mcp.json`, submit in the portal | **yes** |

## PyPI and the MCP Registry

Set up once as [release.md](release.md) describes, then push the tag `v1.0.0`. The workflow publishes to PyPI. The
`mcp-registry` job then publishes `server.json`: the registry checks that the PyPI README contains
`mcp-name: io.github.tsyyan/buddie`. That line is an HTML comment at the top of `README.md`, so it does not show.
`tests/test_version.py` keeps `server.json` at the code's version.

## Anthropic's directory: the plugin

1. Connect your GitHub account on claude.ai (the portal checks that it can push to `tsyyan/buddie`).
2. At [claude.ai/directory/manage](https://claude.ai/directory/manage) → **Submit new** → **Plugin bundle**.
   Repository `tsyyan/buddie`, plugin path empty (the plugin is the repository root), tracked branch `main` or a
   release tag.
3. **Validate**, fix anything marked *Blocking*, validate again.
4. Answer the data-handling questions, then submit.

What the checks will find, as far as the published checklist says:

- **Should pass:** name `buddie` (lowercase, distinctive), `version`, `description`, `author`, `license`, a README
  well over 40 words, `LICENSE`, valid `hooks/hooks.json` and `.mcp.json`, the MCP server started by running a file
  in the plugin (`python3 ${CLAUDE_PLUGIN_ROOT}/run.py serve`), no launchers, no lockfiles, 223 files (limit 512).
  The GitHub token comes through `userConfig` with `sensitive: true`.
- **Likely held for a reviewer (not a rejection):**
  - two files over 256 KiB: `results/E008-drb2-fresh/results.json` and `sample_blind.json` (research data);
  - the CLI also reads `GITHUB_TOKEN` from the environment (for CI). The plugin itself uses its setting first, but
    a scan may flag the fallback as "uses a credential from the user's machine".
- **Policy questions a reviewer may ask:** the hook reads the Claude Code session transcript to find the final
  answer and to check `run:` anchors, and keeps a journal of receipts (hashes, verdicts, no conversation text by
  default). README's "The transcript and the journal" section and [PRIVACY.md](../PRIVACY.md) describe this. Point to
  them in the data-handling step.

Suggested data-handling answers (check them against what you know):

| Question | Answer |
|---|---|
| Reads personal data? | It reads the session transcript locally to check the answer. It does not extract or upload it. |
| Stores data? | A local journal (`~/.cache/buddie/hook.jsonl`) with hashes and verdicts; page snapshots of cited public pages. |
| Sends data to other services? | It fetches the pages a report cites, and calls `api.github.com` for `pr:`/`ci:` anchors (with the user's token if set). Nothing else. |
| Retention | Local files only, kept until the user deletes them. |
| Intended for under 18? | No. |

## Anthropic's directory: the MCP connector

Only for a hosted server ([deploy.md](deploy.md)). Once `https://<host>/mcp` is up, submit it in the same portal as
**MCP connector**. The remote server needs no auth, which suits claude.ai, but anyone with the URL can use it, so
put rate limits in front of it first. OAuth is not implemented.

## OpenAI's plugin directory (ChatGPT and Codex)

The public directory takes only plugins that reach a **remote HTTPS MCP server** and carry **no hooks**. The Codex
plugin in `.codex-plugin/` has a Stop hook, so it stays in this repository's marketplace. For the directory, use
the package in [`integrations/chatgpt/`](../integrations/chatgpt):

1. Deploy buddie ([deploy.md](deploy.md)) and replace `https://YOUR-BUDDIE-HOST/mcp` in `integrations/chatgpt/mcp.json`.
2. Copy `integrations/chatgpt/` together with `skills/` into a folder of its own (or a separate repository), so the
   package root holds `plugin.json`, `mcp.json` and `skills/`.
3. Test it locally: add that folder as a local marketplace, install it in the ChatGPT desktop app, run a check.
4. Submit it through OpenAI's plugin submission portal (developers.openai.com/plugins). Auth is `none`; the portal's
   connection form does not take API keys.

## Claude Desktop

Each GitHub Release carries `buddie-<version>.mcpb`; people install it by opening the file
([install-claude-desktop.md](install-claude-desktop.md)). If the developer portal offers a desktop-extension
listing, the bundle is ready for it: `manifest.json` validates with `@anthropic-ai/mcpb` in CI and declares its
privacy policy.
