# Privacy

The Claude Code plugin starts a local process. It needs no Buddie account and makes no model or telemetry calls.
It fetches cited sources and can ask GitHub for evidence. Buddie does not configure a developer data-collection
endpoint. If you choose a developer-controlled URL as a source, that host receives the request like any other host.
The optional HTTP deployment is a separate mode: its operator receives the reports clients send to it.

## What it reads on your machine

- **The text that leaves the session.** At `PreToolUse` on a tool that sends a message (`SendMessage` and the matchers
  you add) the hook reads the text in that tool call. At `Stop` it reads the last assistant message, which Claude Code
  sends with the event (`last_assistant_message`).
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

  **To turn transcript reading off:** the plugin setting "Read the session transcript" (`read_transcript`),
  `BUDDIE_TRANSCRIPT=0`, or `[transcript] read = false` in `buddie.toml`. The hook then never opens the session log:
  the final answer comes from the `Stop` event, `run:` anchors are reported as unchecked, and the context gate,
  ready `run:` anchors and choice cards are off.
- **Your repositories** (git repos around the working directory, or `BUDDIE_REPOS`): files and commits named by
  `path@commit` and `path#sha256` anchors, and `buddie.toml`.

## What leaves your machine

- **Cited pages.** To check a quote the hook downloads the page the quote cites, as a plain HTTP GET of that URL
  (`BUDDIE_FETCH=0`: stored snapshots only, no requests). Only `--access default` in the CLI or MCP server also asks
  archive.org, Common Crawl and open-access copies by DOI. No text of your session is sent with these requests.
- **GitHub API.** `pr:` and `ci:` anchors call `api.github.com` (or the GitHub Enterprise API an administrator's
  protected policy names, [policy.md](docs/policy.md)) for the state of the named PR or commit, with
  the token you gave buddie (the plugin's `github_token` setting or `BUDDIE_GITHUB_TOKEN`; an ambient `GITHUB_TOKEN`
  is not used) (`BUDDIE_GITHUB=0`: no calls). The request carries the owner, repo
  and PR number or commit from the anchor, nothing else.

The optional access methods and deployment modes below have additional destinations. URLs can themselves contain
sensitive information; avoid putting secrets in cited URLs. A host, proxy or certificate authority you trust may
observe requests. These controls do not protect against a compromised interpreter, plugin files or operating system.

## Credentials, endpoints and consent

| Setting | Purpose and recipient | Optional / avoid or revoke |
|---|---|---|
| Claude Code `userConfig.github_token` (`sensitive: true`, `required: false`), exported as `CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN` | User-provided token for authenticated GitHub evidence. Takes precedence over `BUDDIE_GITHUB_TOKEN`. Bearer header only to `https://api.github.com` or the HTTPS API explicitly named in an administrator's protected policy. The Desktop bundle's explicit token setting uses `BUDDIE_GITHUB_TOKEN` with the same destination restriction. | Leave blank for anonymous public evidence. Remove the saved plugin option and revoke the token in GitHub settings to invalidate existing copies. Use a fine-grained read-only token limited to required repositories. |
| `BUDDIE_GITHUB_TOKEN` | Explicit Buddie CLI/CI/deployment credential; same permitted destinations. No lookup of ambient `GITHUB_TOKEN`, `GH_TOKEN`, credential helpers or keychain. | Unset it, remove it from your CI/deployment secret configuration, and revoke it at GitHub. |
| `BUDDIE_GITHUB_API` | Selects an alternative evidence API, **without either token**. Its answers are caller-supplied evidence. It does not authorize a credential destination. | Unset it for GitHub.com. For authenticated Enterprise, use protected `[evidence] github_api` instead. |
| `BUDDIE_HTTP_TOKEN` | Only in optional `serve --http`: expected inbound bearer token, compared locally. It is not an outbound token or a GitHub credential. It is unused by the plugin's stdio command. | Unset in stdio mode. Rotate the server setting and client token together; do not expose an unauthenticated HTTP server to untrusted clients. |
| `HTTP_PROXY`, `HTTPS_PROXY`, lowercase variants, `ALL_PROXY`, `NO_PROXY` and system proxy settings | urllib may route requests through the configured proxy. A proxy URL can contain proxy credentials. The optional browser uses `HTTPS_PROXY`/`https_proxy`. | Clear proxy configuration or ask the administrator to use the isolated collector. A trusted TLS-intercepting proxy can see HTTPS credentials and content. |
| `SSL_CERT_FILE`, `SSL_CERT_DIR`, `VERBATIM_BROWSER_CA` | Trust configuration, not an API secret. urllib uses its configured CA store. Optional browser mode can read the explicit PEM certificate and use `certutil` to add it to the local NSS database; it does not upload that file as a credential. | Leave unset. Remove the added NSS certificate separately if you enabled browser CA import. The isolated collector ignores the environment's proxy/CA overrides; it does not govern Chromium. |
| `VERBATIM_EMAIL` | Optional contact address placed in the query to `api.unpaywall.org` during open-access DOI lookup. Defaults to a placeholder; it is not read from your account or address book. | Leave unset, or avoid the `open_access` access method. The recipient may log the address and DOI. |

Both GitHub tokens are withheld from an environment-selected API, even when another environment variable supplied
the token. An invalid protected policy disables GitHub requests. A protected Enterprise destination must have a
valid HTTPS host/port and no URL credentials, query, fragment or traversal. GitHub redirects to another origin
(scheme, host or port), or outside the API path, are refused before that hop. Same-origin redirects omit the token;
one authenticated retry on a 404 is permitted within the API. Transport errors omit third-party exception text.

The administrator must control the policy file and its parent directories, choose an API they trust to receive the
token and return evidence, and protect its DNS/TLS and any proxy. Buddie validates configuration, not that an
Enterprise host really runs GitHub. See [protected policy and its trust limits](docs/policy.md).

The optional browser starts a fresh browser context and runs the source site's JavaScript; it does not import your
normal browser profile or saved login cookies. `VERBATIM_CHROMIUM` selects a local executable and must be trusted.
Archive lookup sends the cited URL to archive.org and Common Crawl; DOI lookup sends the DOI to OpenAlex and
Unpaywall and may fetch an open-copy host. Explicit `relay` mode sends the cited URL to `r.jina.ai` for rendering.
These services apply their own retention policies. The ordinary plugin hook does not enable this access cascade.

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

Authenticated GitHub source evidence can also be retained in the snapshot store, including private repository
content; protect that folder and delete it to remove cached evidence. Revoking a token does not delete snapshots.
Environment diagnostics require local grants; their local reports describe the selected categories, and stdio MCP
returns requested results to the client. Repo checks, transcript checks and diagnostics collection are local;
the host client can retain or transmit tool results under its own policy. An HTTP deployment has a separate,
operator-controlled store shared by its callers; it must not reuse a local authenticated store. In remote mode,
GitHub evidence is restricted to public repositories. Buddie does not set automatic expiry for these local files.

## Contact

Questions and reports: open an issue at https://github.com/tsyyan/buddie/issues.
