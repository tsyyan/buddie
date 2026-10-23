# Configuration

Environment variables buddie reads, and the quote module's own commands. Per-project levels live in `buddie.toml`
([claude-code.md](claude-code.md)); an administrator's limits in the protected policy ([policy.md](policy.md)), which
no variable here can weaken.

## Environment variables

| Variable | Default | Effect |
|---|---|---|
| `VERBATIM_STORE` | `./.verbatim` | snapshot store |
| `BUDDIE_FETCH` | on | `0`: the hook uses stored snapshots only |
| `BUDDIE_GITHUB` | on | `0`: no GitHub calls, `pr:`/`ci:` become `UNCHECKABLE` |
| `BUDDIE_GITHUB_TOKEN` | none | token for the GitHub API (public repos work without one, within rate limits); an ambient `GITHUB_TOKEN` is never picked up |
| `BUDDIE_REPOS` | git repos around the working directory | `dir:dir` repos for anchors |
| `BUDDIE_FINAL` | `final_mark` in `[mandate]` of `buddie.toml`, else none | regex marking a final answer that must carry anchors at any event; with none, the last message at `Stop` is the final answer; empty turns the rule off |
| `BUDDIE_LOG` | `~/.cache/buddie/hook.jsonl` | hook run log; `0` turns it off |
| `BUDDIE_SHARED_LOG` | `/mnt/project-files/buddie/hook`, only if that folder exists | second log, one file per session; `0` turns it off |
| `BUDDIE_STORES` | none | `dir:dir` extra snapshot stores the hook reads with the session's own |
| `BUDDIE_GATES` | `[gates]` of `buddie.toml` | `class=level,...` overrides the levels above |
| `BUDDIE_INTRO` | `~/.cache/buddie/intro.json` | the intro mode's count per `buddie.toml`; `0` keeps none |
| `BUDDIE_NUMBERS` | from the `numbers` level | `gap`, `fail` or `off`: how the receipt judges a number missing from its source |
| `BUDDIE_JOURNAL_TEXT` | `[journal] text` of `buddie.toml`, else off | `1`: the journal also keeps promise sentences, choice and decision cards as text |
| `BUDDIE_LESSONS` | on | `0`: no lessons at `SessionStart` |
| `BUDDIE_CONTEXT_LIMIT` | `200000` | context tokens past which a non-final reply is returned; `0` turns it off |

## The quote module: verbatim

`verbatim` saves the bytes of every cited source under their SHA-256, extracts the text a reader would see, and
searches each quotation in it. Each quote is checked against **its own** link, the citation next to it in the same
sentence, not just any link in the paragraph.

| Command | Does |
|---|---|
| `buddie-verbatim snap URL…` | fetch and store the bytes (failures are recorded too) |
| `buddie-verbatim text URL --grep RE` | print the visible text of a snapshot: quote from this, not from a summary |
| `buddie-verbatim check REPORT [--fetch] [--access default]` | verdict for every quote in a Markdown or JSON report |
| `buddie-verbatim access METHOD URL…` / `buddie-verbatim merge DIR` | run one access method, or merge another store into yours |

Verdicts: `FOUND` / `FOUND_NORMALIZED`, `HIDDEN_ONLY` (only in markup the reader does not see), `FOUND_IN_COPY`,
`UNCERTAIN`, `NOT_A_QUOTE`, `NOT_FOUND`, `SOURCE_UNAVAILABLE` / `NO_SOURCE`; see
[verbatim-verdicts.md](verbatim-verdicts.md). `--access default` tries lawful routes for unreadable pages in
order: a headless browser (`pip install 'buddie[browser]'`), the Wayback Machine and Common Crawl, open-access copies
by DOI, known syndicated copies. `verbatim` never bypasses paywalls, captchas or bot protection.

What leaves your machine, and what is kept: [PRIVACY.md](../PRIVACY.md).
