# Changelog

## buddie 0.8.2 (2026-10-08)

- Fewer false returns for work claimed in prose. A word in a clause opened by once, as soon as, after, when, if,
  until, unless or before (Russian «когда», «если», «как только», «после того как», «пока не», «до того как»), within
  three words and no punctuation, is a condition or a plan, not a claim: «Once automerge has merged it, start the
  next row». «merged» after an article or possessive and before a noun is an adjective: «the merged code».
- At Stop, the last message is not checked for prose when the same turn already sent a final answer through a text
  tool (reply, post_message, send_message) that the gate let out: that text reaches no one. A reply the gate
  returned, or one sent in an earlier turn, does not count.
- In lab's journal since prose started blocking, these were 2 of 8 prose returns read from transcripts (false) and
  3 of 8 on Stop text after the reply had gone out.

## buddie 0.8.1 (2026-10-04)

- A bare anchor counts: after the anchor sign, without backticks, `path#sha`, `path@commit`, `fact=value`, `pr:…`,
  `ci:…`, `choice:…` up to the first space, `run:CMD => OUT` up to the end of the line, the next sign or a table cell
  border; before, only an anchor in backticks was found, and a report anchored the way the SKILL.md table shows was
  returned as "final answer has no anchor". Placeholders (`<…>`, `…`, `OWNER/REPO`, `CMD => OUT`) and a sign with no
  anchor after it are not anchors. On the 43 E017 gate rounds, offline: rounds with the sign returned for no anchor
  14 → 0.
- The return no longer offers a ready anchor from a call that has nothing to do with the claim: a command that opens by
  writing a file (a heredoc into `>` or `tee`, `sed -i`, `perl -pi`) or the `SubagentHandback` call itself.

## buddie 0.8.0 (2026-10-04)

- `buddie.toml` `[gates]`: each class of claims (`anchors`, `quotes`, `final`, `prose`, `numbers`, `work`, `summary`,
  `promises`) is `block`, `warn` or `off`. A warning lets the text out with a `systemMessage` naming what the gate
  found. `BUDDIE_GATES` overrides the file. Defaults change: work claimed in prose and numbers missing from their
  source warn instead of blocking or being only a gap; the subagent summary and the promise check are off.
- `buddie init` writes `buddie.toml` with the defaults and the intro mode: until 20 final answers have passed with no
  false return reported (`buddie intro --false`), nothing is returned, each would-be return is a warning.
  `buddie enforce` ends it.
- Windows: the hooks start through `hooks/run.sh` (`python3`, else `python`, else `py -3`); the hook reads its event
  as UTF-8 and writes UTF-8. CI runs the tests and a smoke run of the hook on recorded events on Linux, macOS and
  Windows, from a clone and from `pip install`.

## buddie 0.7.4 (2026-10-04)

- Defaults for other projects. Without a configured mark the final answer is the last assistant message at `Stop`,
  in any language; before, only text carrying the Russian mark `Следующий шаг:` was final, so the final-answer rules
  (an anchor required, no count or work claim in prose without one) never ran for anyone else. A project that hands
  in results through a tool names its mark as `final_mark` in `buddie.toml` `[mandate]` or in `BUDDIE_FINAL`; then
  text carrying it is final at any event. An empty `BUDDIE_FINAL` turns the rules off.
- The plugin's hook matches Claude Code's own tools only (`SendMessage`; `Agent` and `Task` for launches).
  Matchers for a project's reply and post tools and for cloud sessions moved to
  [`examples/hooks/projects.json`](examples/hooks/projects.json).
- The version in `pyproject.toml` and `CITATION.cff` is written from the code at export: the public tree carried
  0.6.0 under 0.7.3 code, and `test_one_version_everywhere` failed.

## buddie 0.7.3 (2026-10-04)

- The launch gate and the summary judge a row's verdict at the time of the check: a "not before <date>" condition
  comes due then, and a delay ("a day after the merge of №M") counts from the commit that brought the row's text.
  Without history (uncommitted edit, the bottom of a shallow clone) a delay does not come due.

## buddie 0.7.2 (2026-10-04)

- A launch with a basis is still returned (exit 2, outcome `taken`) when the row is already taken: `free: false` in
  the row's verdict of the merge comment on the PR merged as the anchor's commit, or the command `[launch] free`
  (`{n}` is the row) answering `free: false` now. Its reasons are printed. `BUDDIE_FREE=<command>` sets the command,
  `0` turns it off; without a comment and a command the gate lets the launch through (`free: null` in the journal).
- The launch hook's timeout is 60 s instead of 30 s.

## buddie 0.7.0 (2026-10-04)

- Launch gate (`buddie.toml` `[launch] tools`, off without the section): a launch of queue row N passes only with
  `⚓ NEXT.md@<commit>` whose queue gives N the verdict `auto`, or with `⚓ choice:<id>=№N`, the person's pick in the
  journal; otherwise exit 2 with a ready anchor when one holds. A launch with no row number passes.
- Promises: a text the gate let out is read for promises to launch a row (with a condition: a PR merged, a row done)
  and to send a summary; `SessionStart` prints the open ones, `Stop` returns the turn once per promise whose
  condition holds. A `buddie:` line drops a promise; promises expire after 48 hours.

## verbatim 0.3.7 (2026-10-04)

- `numbers` reads "млн", "млрд", "тыс.", "трлн" and the full Russian words after a number as million, billion,
  thousand, trillion: "$35.0 млн" is found on a page with "$35.0 million".
- A year the sentence itself calls absent ("not on the page", "не упоминается") is not looked up (`ABSENT`).
- A report on one's own work is not a claim about the page: numbers inside a `run:` anchor (command and output) and a
  snapshot timestamp next to its sha256 or a word like "snapshot" are not looked up.

## verbatim 0.3.6 (2026-10-04)

- `numbers`: a number missing from an abstract page (arXiv `/abs/`, an OpenAlex abstract) is `UNCERTAIN`
  (`abstract_only`); one missing from a market report whose forecast period on the page is later than the sentence's
  is `UNCERTAIN` (`rewritten`). buddie counts both as gaps, not blocks.

## verbatim 0.3.5 (2026-10-03)

- `check.readable` no longer takes for a document an Anubis check, a login page, an encoded payload or a redirect to a
  local address.
- `numbers` reads "2024 Jan 5", "10/09/2018" (both orders), thin-space thousands and tables "in thousands"/"in
  millions"; "from 12.3 million in 2020 to 16.2 million" is no longer a range.

## verbatim 0.3.4 (2026-10-03)

- `check.readable` no longer takes for a document a "Client Challenge", a captcha at the head of a long page, a
  JavaScript shell, or a redirect to the home page, to a section above the requested page or to a short page of
  another site; the `--access` cascade then goes on to the real page.
- `numbers`: a year counts as found only next to a word of its own clause; `cited_sentences` reads Gemini-style
  footnotes.

## buddie 0.7.1 (2026-10-04)

- A final answer that claims work in prose (merged, CI green, tests passed, ran) with no `pr:`, `ci:` or `run:`
  anchor on the same line is returned, with the ready anchors that hold now; a `buddie:` line does not let it
  through, only an anchor or dropping the claim does. Other messages only count such lines (`prose_work`); the
  receipt now also lists their numbers (`prose_lines`). A negated claim ("not merged yet", «ещё не слит») is not a
  claim. Found in our own dogfood: a thread answer stated four merges with no anchor and left.

## buddie 0.6.1 (2026-10-03)

- A line whose quote is FOUND on the page at a URL written on that same line carries its source: its numbers are no
  longer listed under `unanchored`, and a final answer is not returned for them as "number without anchor". The
  receipt lists such lines under `quote_backed`. A number without the URL on its line is still returned. Found on a
  correct report of the E016 pilot (three quoted revenue figures, quotes 3/3 found, returned anyway).

## buddie 0.6.0 (2026-10-03)

- Summary with a choice card: the hook counts live subagents (`SubagentStart`/`SubagentStop`), checks each
  subagent's last message, and on the orchestrator's `Stop` with none left asks once for a summary.
- `buddie summary` (CLI) and the MCP tool `summary`: what was done (receipt outcome), lost subagents, next steps with
  `auto`/`ask` verdicts, open PRs and red CI, and a ready `AskUserQuestion` card with at most three steps.
- The person's pick (`PostToolUse` on `AskUserQuestion`) goes to the journal; the anchor `choice:<id>=<step>` is
  checked against it and counts as consent in work claims.

## buddie 0.5.1 (2026-10-03)

- An anchor with the sign before the backticks (⚓ `path@commit`, as the skill used to show it) is now read like
  `⚓ path@commit`. Before, it was not parsed at all: a correct report counted as unanchored and was returned, and a
  broken `pr:`, `ci:` or `run:` anchor in that form went through unchecked. The skill and README show the sign inside
  the backticks.

## buddie 0.5.0 (2026-10-03)

The public tree had carried 0.4 and 0.5 code under the 0.3.0 version since the daily sync; this release names it.

- Numbers (0.4): numbers and dates in a sentence with a link are looked up in the snapshot of that link
  (`verbatim.numbers`). A number missing from its readable source is a gap by default; `--numbers fail` or
  `BUDDIE_NUMBERS=fail` makes it block, `off` turns it off.
- Closed loop (0.5): a returned message logs `reasons`; the next attempt logs `gate`, how it got through (proof,
  removal, disclosure, returned again). `SessionStart` prints the lessons of past sessions' journal (at most ten lines,
  `BUDDIE_LESSONS=0` turns it off). A return offers ready `pr:`, `ci:` and `run:` anchors that already hold.
  `buddie journal measure` and `buddie journal lessons`.
- Context gate: past `BUDDIE_CONTEXT_LIMIT` tokens (default 200000) a non-final reply is returned with a reminder to
  hand the result over and start the next step in a new thread.
- Snapshot stores: the hook judges web quotes against the snapshots the session took (`BUDDIE_STORES`,
  `VERBATIM_STORE`, stores named in the session's tool calls, `./.verbatim`), and fetches only URLs in none of them.
- A `buddie:` disclosure line no longer lets a broken `pr:`, `ci:` or `run:` anchor through: such an anchor states work
  that did not happen, so it must be corrected or removed.

## buddie 0.3.0 (2026-10-03), first public release

The repository `tsyyan/verbatim` became `tsyyan/buddie`; verbatim is buddie's quote module.

- Effect anchors `pr:`, `ci:` (GitHub API) and `run:` (session transcript); output the agent typed itself does not count.
- Work and mandate claims against a task queue (`buddie.toml`, opt-in).
- Repo anchors `path#sha256`, `path@commit`, `fact=value`.
- Receipt v0 (in-toto Statement), CLI, MCP server over stdio, Claude Code hook, plugin and marketplace.
- Results E009 (numbers) and E014 (Search Arena) added.

## verbatim

Each version was measured on reports it was not tuned on. Experiment folders are in `results/`.

## 0.3.3 (2026-10-02)

- Footnote markers inside quotation marks (`[1](url)`, `[2]`) are dropped before search.
- A truncated response body (`IncompleteRead`) is a failed fetch, not a crash of `check`.
- E014 in-sample recount: false `NOT_FOUND` 26 of 423 instead of 29; no agent error became a find.

## 0.3.2 (2026-10-02)

- Two replies of one speaker joined across the page's speech tag are found (`note: "speech_tag"`).
- The page's `[A]t` brackets and `___` blanks are normalized. Mojibake in the text layer is repaired before search.
- E012: none of 200 labelled agent errors became a find.

## 0.3.1

- New hints that mark an example before the quote marks: `like “`, `something like: “`, `might include: “`,
  `questions (“`. E011: 2 hits in 249 checked quotes, both correct.

## 0.3.0

- `NOT_A_QUOTE` verdict for words the report itself shows are not a quotation (`boilerplate`, `title`, `example`).
- Punctuation between words is ignored at the last normalization level.
- E010: false `NOT_FOUND` 5 of 147 (3.4 %).

## 0.2

- A quote is checked against its own link. A find under another link of the paragraph is `UNCERTAIN`.
- `UNCERTAIN` doubts and the access cascade (`--access`: browser, Wayback / Common Crawl, open access, copies).
- PDF via `pdftotext`, compressed bodies, cookie and bot gates are reported as `SOURCE_UNAVAILABLE`.

## 0.1

- `snap`, `text`, `check`: the content-addressed store, the visible-text layer and the quote search.
