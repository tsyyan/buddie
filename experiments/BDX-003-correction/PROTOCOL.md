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
