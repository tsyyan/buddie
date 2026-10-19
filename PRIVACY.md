# Privacy

buddie is a local tool. It has no server, no account, no telemetry and no model calls. The author receives no data from
it. This page lists everything it reads, everything it sends off your machine, and everything it keeps on disk.

## What it reads on your machine

- **The text that leaves the session.** At `PreToolUse` on a tool that sends a message (`SendMessage` and the matchers
  you add) the hook reads the text in that tool call. At `Stop` it reads the last assistant message of the session.
- **The session transcript** (`transcript_path`, the Claude Code jsonl file of the current session, and its subagents'
  files next to it). The hook reads it for these checks only:
  - the final answer at `Stop` (the last assistant message);
  - `run:` anchors: an anchor `run:CMD => OUTPUT` holds only if the transcript shows a call that ran `CMD` and
    printed `OUTPUT`;
  - ready anchors offered on a return (commands of this session whose output already matches);
  - snapshot stores the session named in its tool calls (where to look for a cited page it already saved);
  - the context gate: the token count of the last API call;
  - the choice card: the `metadata.source` of an `AskUserQuestion` call.

  It does not read other sessions' transcripts, Claude's memory or chat history. The transcript is read in place and
  never copied, stored or sent anywhere.
- **Your repositories** (git repos around the working directory, or `BUDDIE_REPOS`): files and commits named by
  `path@commit` and `path#sha256` anchors, and `buddie.toml`.

## What leaves your machine

- **Cited pages.** To check a quote the hook downloads the page the quote cites, as a plain HTTP GET of that URL
  (`BUDDIE_FETCH=0`: stored snapshots only, no requests). Only `--access default` in the CLI or MCP server also asks
  archive.org, Common Crawl and open-access copies by DOI. No text of your session is sent with these requests.
- **GitHub API.** `pr:` and `ci:` anchors call `api.github.com` for the state of the named PR or commit, with
  `BUDDIE_GITHUB_TOKEN` or `GITHUB_TOKEN` if set (`BUDDIE_GITHUB=0`: no calls). The request carries the owner, repo
  and PR number or commit from the anchor, nothing else.

Nothing else leaves your machine.

## What it keeps on your machine

| Where | What | Off |
|---|---|---|
| `BUDDIE_LOG` (`~/.cache/buddie/hook.jsonl`) | the journal: one line per check with time, session id, tool, counts, verdicts, exit code and the SHA-256 of the checked text. By default no words of the conversation: a promise line keeps its kind, queue row, condition and the sentence's SHA-256; a choice line keeps hashes of the picked steps and the numbers of a typed answer; a decision card line (`ask_decision`) keeps its options' label hashes and queue numbers | `BUDDIE_LOG=0` |
| `BUDDIE_SHARED_LOG` (`/mnt/project-files/buddie/hook`, only if that folder exists) | the same lines, one file per session | `BUDDIE_SHARED_LOG=0` |
| `BUDDIE_STATE` (`~/.cache/buddie/pending`) | the lines the gate just returned, until the next attempt of the same tool; used to tell whether a claim was proved or removed | `BUDDIE_STATE=0` |
| `BUDDIE_SESSIONS` (`~/.cache/buddie/sessions`) | per session: live subagents, each subagent result's first line, receipt and «Next step» lines, summary cards shown | — |
| `VERBATIM_STORE` (`./.verbatim`) | snapshots of the pages it fetched, with URL, time and SHA-256 | `BUDDIE_FETCH=0` |
| `BUDDIE_INTRO` (`~/.cache/buddie/intro.json`) | the intro mode's count of final answers per `buddie.toml` | `BUDDIE_INTRO=0` |

`[journal] text = true` in `buddie.toml` (or `BUDDIE_JOURNAL_TEXT=1`) makes the journal also keep promise sentences
and the questions, options and answers of choice and decision cards; it is off unless you turn it on.

Delete any of these files or folders at any time; buddie recreates what it needs.

## Contact

Questions and reports: open an issue at https://github.com/tsyyan/buddie/issues.
