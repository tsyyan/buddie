# Limitations, security and privacy

What buddie does not guarantee, and what it reads, sends and keeps. The [README](../README.md#limitations)
carries the summary; execution boundaries and tested attacks are in [security.md](security.md) and
[adversarial.md](adversarial.md).

## Security and privacy

- **It runs locally.** Snapshots, the journal and settings stay on your machine. No telemetry, no model calls, no
  account; a remote server exists only if you host one.
- **It fetches the pages a report cites**, to snapshot them, whenever it checks a report with links (`BUDDIE_FETCH=0`
  or `--no-fetch`: stored snapshots only). No text of your session is sent with those requests.
- **It calls GitHub** for `pr:` and `ci:` anchors: `api.github.com`, or the GitHub Enterprise API a protected policy
  names (`BUDDIE_GITHUB=0` or `--no-github`: none).
- **Your GitHub token** is optional, taken from the plugin's setting or `BUDDIE_GITHUB_TOKEN`, and sent only to that
  API. buddie never reads an ambient `GITHUB_TOKEN`.
- **The Claude Code transcript** is read in place to check `run:` anchors; it is never copied or sent, and a plugin
  setting turns reading it off. The journal keeps hashes and verdicts, not your text.
- **What buddie cannot prevent:** code that already runs as your user, a replaced `python3` or `git` on `PATH`, an
  agent that rewrites the plugin's files or turns the plugin off in settings it can write, and an agent running as
  root or administrator. Without root, the protected policy is the one input the agent cannot change
  ([policy.md](policy.md#what-it-does-not-cover)).

Everything read, sent and kept: [PRIVACY.md](../PRIVACY.md). Execution boundaries and tested attacks:
[security.md](security.md), [adversarial.md](adversarial.md).

## Limitations

- **buddie is not a truth detector.** It checks claims written in the forms above against their evidence. A claim in
  any other form is not checked.
- **`PASS` is scoped.** It covers the quotations and anchors that were checked, against the evidence that was read;
  with a profile, only the checks the profile ran.
- **`GAPS` is not success.** It means something could not be checked; the receipt says what. The CLI exits 0 on it.
- **A real quote can still mislead.** buddie checks that the words are on the cited page, not that they support the
  sentence around them.
- **Evidence ages.** A verdict holds for the snapshot hash and time it names; `pr:` and `ci:` describe GitHub now
  unless pinned to a commit. `buddie freshness` *(2.0)* says when evidence is about another revision.
- **Advice is advice.** The MCP tools and the CLI change nothing unless something acts on their result.
- **The gate covers what the client sends it:** Claude Code's `Stop` and `SendMessage`, Codex's `Stop`. Desktop and
  other clients have no hook, and `run:` is checked only against a Claude Code transcript.
- **The gate is not a lock.** It returns an answer; the agent then fixes the claim or says, in a line starting with
  `buddie:`, what is unverified, and the answer goes out with that line. A broken `pr:`, `ci:` or `run:` anchor has
  to be fixed or removed, and a protected policy can require a fix for everything. If the check cannot run at all (no Python, a timeout), the answer goes back once and then out
  with a note that nothing was checked: it is never passed as checked.
- **Local evidence is local.** Repository anchors, `run:` and work claims are checked against files on your machine:
  the checkout, the transcript, the task queue. buddie shows what those files say; an agent that can write them can
  change what they say.
- **A receipt is an evidence record.** It says what was checked and found, not that code is correct: a green CI on
  weak tests stays weak, and a command that prints a prepared file passes `run:`.
- **Whether agents misstate less with buddie** is not yet measured ([research.md](research.md)).
