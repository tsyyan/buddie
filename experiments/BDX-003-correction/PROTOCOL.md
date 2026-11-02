# BDX-003 protocol: does buddie's feedback leave fewer false quotations reaching a reader?

Pre-registered on 2026-10-30, before any model call. Changes after the first paid or free run are recorded at the
end of this file with their date and reason; nothing above that line is edited after data exists.

## Question

When a model prepares a report paragraph for a reader and a quotation in it is false, does buddie's feedback (the
Stop hook's words, outside Claude Code) leave fewer false quotations in the final paragraph than the same model
told to check its quotations itself with the same access to the source? At what cost to correct quotations and in
requests and tokens?

What it does not answer: how often agents make such errors on their own (the paragraphs carry errors already: E008,
E011), or whether the Claude Code plugin as installed behaves the same (a separate confirmation run, below).

## Material

Units: the blind-labelled quotations of E008 (DeepResearch Bench II) and E011 (DeepResearch Bench I, both
labellers agreeing), labels IN_SOURCE (OK), AGENT_ALTERED and AGENT_ABSENT (ERROR): 251 units, 172 ERROR and 79
OK (`units.py`). E010 is out: its report text may not be redistributed.

Sources are fetched again (`refetch.py`): the original snapshots are not redistributed. A unit is used only when an
independent matcher agrees with its label on the snapshot used (SAME bytes as labelled, or STABLE: other bytes,
label still holds). Every arm, buddie in arm C and the judge read that one snapshot.

## Arms (same model, system prompt, paragraph; order randomized per unit, seed recorded)

- **A** pass-through: "return the paragraph ready to send".
- **B** self-check: check every quotation against its source with `source_text` (passages of the snapshot), fix it
  or turn it into a paraphrase.
- **C** B plus buddie: after each answer buddie checks the paragraph against the snapshot; when a quotation does not
  hold, the hook's own text (`buddie/hook.py` RETURNED, FIX) with the failing items goes back, at most 2 rounds.
- **D** (added after pilot 1) A's instruction, the tool, buddie's feedback as in C.
- **E** (added after the gpt-oss main run) C with the improved feedback: each failing quote carries the page's
  sentence around the near match (`closest.passage`, buddie after 2.0.6).

## Outcomes (judged without buddie: `common.in_text`, `judge.py`)

For the target quotation in the final paragraph: CORRECT (in the source), WRONG (not in the source), REMOVED (no
quoted span at least 0.6 similar: dropped or paraphrased).

- **Primary:** on ERROR units, the share WRONG, C minus B, paired by unit (95 % bootstrap interval).
- **Secondary:** on OK units, the share not CORRECT, C minus B (what the check costs good quotations); A against B
  and C; requests, tool calls, tokens, seconds per unit; failed runs (API errors) per arm, never dropped.
- Audit: a person labels a random 20 % of rows from `audit_sheet.csv` without the arm; the auto judge's agreement is
  reported. Disagreements are reported, not used to rewrite the auto labels.

## Models and runs

Free tiers through OpenAI-compatible APIs (`arms.py`): GitHub Models (`openai/gpt-4.1-mini` first), then one open
model (Groq or OpenRouter) and one Gemini Flash model (see the change of 2026-10-30 below). Temperature 0 where accepted. One repetition per unit, arm and
model in the main run.

Pilot: 40 units fetched, 16 eligible units run on one model. The pilot is for plumbing, the eligible share and the
base rate of B; its numbers are reported as a pilot and not pooled with the main run.

Main run: every eligible unit on each model. Stop rules: a model with more than 20 % failed runs in any arm is
reported and excluded from the pooled table.

## Analysis

Per model, the cells and paired differences of `judge.py`; no pooling across models in the primary table. With n
paired ERROR units the interval shows what the data support; no significance claim from the pilot. A difference in
the primary endpoint with an interval excluding 0 is reported as "buddie's feedback reduced false quotations for
this model on this material", nothing broader.

## Confirmation in the product (separate, after the main run)

20 to 30 full reports in Claude Code (subscription), plugin on versus a clean configuration with no plugin, the same
judge. It checks that the effect holds with the real Stop hook; it is reported apart.

## Changes after data

- 2026-10-30, before any model answer was recorded: GitHub Models is not usable from this repository's Actions
  (`models.github.ai` answers every request, including its model catalog, with a plain-text `OK`; three pilot runs
  recorded only failed calls, no model output). The first model moves to Groq (`llama-3.3-70b-versatile`, key as the
  repository secret `GROQ_API_KEY`); GitHub Models stays a provider for when it answers. Nothing else changes.
  Later the same day, still before any model output: `llama-3.3-70b-versatile` is no longer offered by Groq; the
  pilot model is `openai/gpt-oss-120b` (Groq), the second model `gemini-3.8-flash` (Gemini free tier), names taken
  from the providers' model lists. Answer limit raised to 4,000 tokens (gpt-oss reasons before answering).
- 2026-10-30: the source refetch uses the web archive only when the live page does not bear the label out (a full
  archive search took minutes per page), searching the newest 3 Common Crawl crawls. Eligibility of the 40-unit pilot
  pool: 34 eligible (ERROR 25, OK 9).
- 2026-10-30, after pilot 1 (run 40996423234) and before the main run, decided by the owner. Read by hand, the 13
  REMOVED rows of pilot 1 were: 6 paraphrases where the source lacks the words (what B and C are asked to do), 3
  paraphrases where the source has near words, 2 with the false words kept and only the quotation marks dropped,
  2 with no paragraph at all (the model asked for the link), none a correct replacement quote. Three changes:
  1. **Arm D**: A's instruction (no request to check), the `source_text` tool available, buddie's feedback as in C.
     D against A is what the hook alone fixes; D against B is the hook against asking the model to check itself.
     Reported as secondary comparisons (D−A, D−B on paired ERROR and OK units); the primary endpoint stays C−B.
  2. **Units without their link**: a unit whose paragraph does not contain its URL (55 of 251, mostly footnote
     references such as `[^30]`) is excluded before fetching (`no_link_in_paragraph`): a model checking the
     paragraph cannot reach that source.
  3. **REMOVED split** (secondary only; CORRECT/WRONG/REMOVED and the primary endpoint unchanged): NO_PARAGRAPH (under
     30 % of the paragraph's words left), UNQUOTED_KEPT (a run of words at least 0.85 like the target, without
     quotation marks), REPLACED_CORRECT (a new quoted span of 4+ words that is in the source), PARAPHRASED. The two
     thresholds were set after reading pilot 1 and reproduce the hand reading of its 13 rows; one row (similarity
     0.85, "every groundhog looks different") sits on the UNQUOTED_KEPT boundary. The audit (20 %) checks them.
  Pilot 2 (arms A–D, same model) checks the plumbing of these changes and is not pooled either.
- 2026-10-30, before the main run: `openai/gpt-oss-120b` is served by several free providers (PROVIDERS.md: OVHcloud
  anonymous tier, Groq, Cloudflare Workers AI), because one free tier allows only about 8 units a day. Every arm of a
  unit runs at one provider: a unit begun at a provider waits for it when its limit is reached, it is never split.
  Rows record the provider; the per-model tables pool providers, and `judge.py` reports the cells per provider next
  to them. Gemini Flash stays the second model, from Google only.
- 2026-10-31, during the main run (60 of 146 units done): the judge's quoted-span pattern stopped at 600 characters,
  so a quotation longer than that was never found and its run counted REMOVED in every arm, arm A included. Two
  eligible units have such quotes (E011:F044 OK, 779 characters; E011:F053 ERROR, 996). The limit is now 2,000. Found
  from arm A's rows (pass-through, so arm-neutral), not from a difference between arms; the judge re-reads every run,
  no model answer is redone, and eligibility (which does not use this pattern) is unchanged.
- 2026-10-31, after the `openai/gpt-oss-120b` main run (146 units, arms A–D), decided by the owner. That run's
  primary result stands as recorded (main-log.txt). Two changes for what follows:
  1. **Arm E**: arm C with buddie's improved feedback. The failing quote line now shows the page's whole sentence
     around the near match (from similarity 0.75), instead of the near match cut to the quote's length, and FIX
     points to it. Arms C and D keep the 2.0.6 words exactly (`arms.FIX_206`, `arms._as_206`), so their rows stay
     comparable with the finished run. Secondary comparisons E−C (does the passage help; and its cost in requests
     and tokens) and E−B on paired units; the primary endpoint stays C−B. Arm E runs on gpt-oss-120b over the same
     146 units, the A–D rows are not redone.
  2. **Second model**: `gemini-3.1-pro-preview` on a paid Gemini key replaces `gemini-3.8-flash` on the free tier
     (whose daily quota did not allow the run). First a 5-unit measurement of tokens per unit, then the run over the
     146 units within the key's token budget; which arms it runs is recorded here before it starts.
- 2026-10-31, decided by the owner before any answer of it was recorded: the second model is `claude-opus-5`
  (Anthropic Messages API, key `ANTHROPIC_API_KEY`; `arms.to_anthropic` / `from_anthropic` translate the requests),
  instead of `gemini-3.1-pro-preview`. Arms A, B, C and E (D is not repeated). First a 5-unit measurement of tokens
  per unit, then the 146 units within the key's budget of about 15M tokens.
- 2026-10-31, decided by the owner before any `claude-opus-5` answer is pooled (the 5-unit measurement of the pilot
  job is not). The design is read as what it is, a 2×2: asked to check (no: A, D; yes: B, C) × buddie's feedback
  (no: A, B; yes: C, D); E is C with the improved feedback. For `claude-opus-5` all five arms run, and:
  1. **Endpoints for `claude-opus-5`** (the gpt-oss endpoints stay as they were):
     - *harm*: share WRONG on ERROR units, D − A (buddie as a user meets it, against nothing);
     - *cost*: mean input tokens (`sent_chars` where the provider's usage is empty) on OK units, D − B, with
       non-inferiority of D against B on WRONG (margin +0.05);
     - *damage*: share of OK units not CORRECT, D − A;
     - C − B stays reported, for comparison with gpt-oss; the factorial main effects and their interaction
       (logistic, unit as random effect) are secondary.
  2. **Seeded errors** (a separate set, reported apart, never pooled with the natural errors): correct quotations of
     eligible OK units altered in four ways (a number, one word, an invented clause, the link to another unit's
     source), about 150, built by a script before any model sees them, judged as ERROR units.
  3. **The product run** (`product.py`, `product_judge.py`, job `product`): Claude Code itself, headless
     (`claude -p`, the version pinned in the workflow), model `claude-opus-5`, without and with buddie installed from
     its marketplace (the release on `plugin-stable`, recorded per chunk). Permissions are not skipped: `WebFetch`
     is allowed in both, buddie's `snap`, `source_text`, `verify_report` in `with`; at most 12 turns. Tasks:
     *paragraph* (a unit's paragraph with arm A's words, about 100 ERROR and 50 OK units) and *summary* (an OK
     unit's source page, "summarize with at least two exact quotations", about 50 pages). Judged from what the reader
     saw, every assistant message in order: paragraph CORRECT / WRONG / FLAGGED / REMOVED by the last statement of the
     target quote, and whether a wrong one was ever shown; summary, false quotations shown and left at the end.
     Primary product endpoint: share WRONG on ERROR paragraphs, with − without, paired by unit. Secondary: shown
     wrong, damage on OK, false quotations left in summaries, turns and tokens per run. A first chunk of 9 sources
     calibrates turns and tokens; the rest is sized to the remaining budget, which is recorded here before it runs.
  4. **Audit**: a blind 20 % sample of judged rows (judge.blind_sheet) is read by the owner before the report.
- 2026-10-31, decided by the owner after the product run's calibration chunk (18 runs, main-log.txt), before the
  rest of it. With buddie, Claude Code followed buddie's skills before answering (ToolSearch, snap, source_text,
  verify_report: about 6 turns and 73-79k input tokens a paragraph, against 1 turn and 11k without), and the Stop
  hook never had to return anything. The summary task gave no exact quotation without buddie (WebFetch returns a
  digest of the page), so it measures nothing comparable and is dropped. Changes:
  1. **A third condition, `hook`**: the same release with its skills taken out of the installed copy (the workflow
     removes the plugin's `skills/` directories and reports it), MCP tools and hooks unchanged. Whether the Stop hook
     alone keeps the benefit at a fraction of the cost decides whether the skills should stop asking for a check
     before answering when the hook is installed.
  2. **Size**: paragraphs only, 50 ERROR and 25 OK units, three conditions, one run each (the calibration chunk's
     runs are part of it). Paired comparisons with−without (primary on ERROR: share WRONG), hook−without and
     hook−with (secondary), damage on OK, turns and input tokens per run.
- 2026-10-31, after the product run's chunk 2 (run 41226361810), before its numbers are read as results: (a) many
  rows are not runs of the model: Claude Code printed an API failure, or used no tokens, as its answer (OK
  paragraphs "removed" in 1 turn with under 1k tokens). `product.bad` now marks such a row failed, it is redone in the
  next chunk, and the judge counts it as failed with the reason. (b) Without its skills (`hook`), the model still
  called ToolSearch, snap, source_text and verify_report before answering (the MCP tools invite it), so `hook` did
  not test the hook alone. It stays as an exploratory variant; the planned comparison moves to **`hookonly`**: skills
  and the MCP server (`.mcp.json`) taken out of the installed copy, hooks kept, only WebFetch allowed.
- 2026-11-01, decided by the owner before any `hookonly` run held (the chunk of run 41236533623 failed at the API in
  2 s a run and is redone; its judge step failed on a name clash, fixed): a fourth condition, **`hookdisc`**:
  `hookonly` plus the plugin's `buddie-discovery` skill, the one written for a client without buddie's MCP tools
  (the other skills and `.mcp.json` taken out of the installed copy, WebFetch allowed). Compared with `hookonly`
  (what the skill adds to the hook alone) and with `with` (the release as it ships), on the same units.
- 2026-11-01, after the key's balance ran out and was topped up, before the rest of the product run: its size is
  25 ERROR and 15 OK paragraphs (the first of the seeded plan's 50 and 25, so every run kept so far is in it), in four
  conditions (without, with, hookonly, hookdisc). Smaller than planned because a run with buddie costs about 104k
  input tokens, not the 53-79k the calibration chunk suggested.
- 2026-11-02, decided by the owner before the remaining runs (claude-opus-5 API, about 110 units; product OK
  paragraphs to 15 per condition) and before any audit:
  1. **Audit sample** instead of a flat 20 %: the owner reads, blind to arm and condition, up to 7 rows per model and
     arm of the API runs (gpt-oss A-E, claude-opus-5 A-E; about 70 rows) and up to 7 rows per product condition (at
     most 35), each cell taken round-robin across the judge's outcomes so a rare outcome is read too (seed 11;
     `judge.py` and `product_judge.py` write `audit_sample.csv` beside the full sheets, with the same row numbers).
     Reported: agreement per outcome; a cell where the judge is wrong in more than 1 row of 7 is named in the report
     with its rows. The audit is read after the last run and before any conclusion is published.
  2. **What closes the run**: claude-opus-5 on all 146 units in arms A-E; product OK paragraphs 15 per condition
     (without, with, hookonly, hookdisc). Then the report; no further arms or conditions are added to BDX-003 (cost
     variants go to a separate experiment).
- 2026-11-02, decided by the owner: **BDX-003 is closed** with what was run. Deviation from the plan of 2026-11-02:
  `claude-opus-5` covers 84 of the 146 units in arms A-E (51 ERROR, 33 OK; the first 84 in the seeded order, the same
  units in every arm), not 146, because the key's balance ran out twice and the gateway counted about four times the
  tokens the answers reported. The `openai/gpt-oss-120b` run (146 units, A-E) and the product run (25 ERROR, 14-15 OK
  paragraphs per condition) are complete. Nothing more is run; the audit sample is read from the last judged data,
  then the report.
