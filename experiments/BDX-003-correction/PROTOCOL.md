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
