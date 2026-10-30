# BDX-003: correction of false quotations, with and without buddie

Status 2026-10-30: built, tested without a model, one pilot run on Groq (below). No main-run results yet. The question, arms, outcomes and stop rules are fixed in [PROTOCOL.md](PROTOCOL.md).

| File | What it does |
|---|---|
| `units.py` | 251 units from the blind labels of E008 and E011 (a quotation, its paragraph, its link, ERROR or OK) |
| `refetch.py` | drops units whose paragraph lacks their link; fetches the sources again (direct, then web archive); keeps a unit only if its label still holds |
| `arms.py` | runs arms A (pass-through), B (self-check with a source tool), C (B plus buddie's feedback), D (A's instruction, the tool, buddie's feedback) |
| `judge.py` | judges the final paragraphs with an independent matcher (not buddie), splits REMOVED, pairs the arms, writes an audit sheet |
| `common.py` | the matcher, page text, file helpers |

## Run

Providers for the main run, and why these: [PROVIDERS.md](PROVIDERS.md). `--provider ovh,groq,cloudflare` uses them
in that order, each unit at one provider (OVH needs no key; Cloudflare needs `CLOUDFLARE_API_TOKEN` and
`CLOUDFLARE_ACCOUNT_ID`).

In GitHub Actions: put a free key in a repository secret (`GROQ_API_KEY`, `GEMINI_API_KEY` or `OPENROUTER_API_KEY`;
GitHub Models uses the workflow's own token but answers only `OK` from this repository's Actions), set the provider
and model in `pilot.env`, and push to `experiment/bdx-003-pilot`, or run the `bdx003` workflow by hand (its inputs
override `pilot.env`). The numbers appear as the run's annotations (`notices.py`). The run summary shows the table; the artifact
holds units, eligibility, runs and judgements. Page snapshots are not uploaded: they are other people's pages.

Locally, with another free provider:

```sh
pip install -e ../..
python units.py --out data/units.json
python refetch.py --units data/units.json --sample 40 --raw data/raw-store --store data/store --out data/eligible.json
GROQ_API_KEY=... python arms.py --units data/units.json --eligible data/eligible.json --store data/store \
    --provider groq --model llama-3.3-70b-versatile --n 16 --out data/runs.jsonl
python judge.py --units data/units.json --store data/store --runs data/runs.jsonl --out data/judged
python -m unittest discover -s tests -v
```

`arms.py` is resumable (finished rows are skipped) and stops cleanly at a daily limit; run it again the next day.
Free tiers: GitHub Models about 150 requests a day for mini models, Groq about 1,000, OpenRouter `:free` 50 (1,000
after a $10 top-up), Gemini per project. Gemini's free tier may use prompts to improve Google's products; the inputs
here are public benchmark reports.

## Limits known before running

- The matcher is plain (normalized substring with ellipsis gaps). Units where it disagrees with the human-style
  label on the fetched page are excluded, which removes some hard cases.
- Pages changed since labelling; only units whose label still holds are used, so the sample shifts toward stable pages.
- B and C share the source tool. A model that ignores the tool gets no source in B; C still gets buddie's feedback.
  That is the comparison intended: buddie's check against the model's own diligence.

## Main run in chunks

`main.env` sets the providers, model and arms; each push to `experiment/bdx-003-main` runs one chunk (job `main` of
`bdx003.yml`): it restores `data/` from the newest Actions cache of earlier chunks (the first chunk fetches every
unit's source), resumes `arms.py` until the providers' limits or `MINUTES`, judges every row so far and saves
`data/` again. The annotation "BDX-003 main progress" says how many eligible units have every arm. To switch to the
second model, change `MODEL` (and `PROVIDER=gemini`) in `main.env` and push: rows are keyed by model, the snapshots
are shared.

## Current state and next steps (handoff, 2026-10-30)

Written so a new session (Claude Code on the owner's machine) can pick this up without the previous chat.

### Where things are

- Code: branch `experiment/bdx-003-correction`, PR [#84](https://github.com/tsyyan/buddie/pull/84) (open, CI
  green, not merged). `experiment/bdx-003-pilot` is the same code; pushing to it runs the pilot job of
  `.github/workflows/bdx003.yml`. `experiment/bdx-003-report` re-reads an earlier pilot's artifact (run id in
  `REPORT_RUN`) and prints its numbers as annotations.
- Secrets in the repository: `GROQ_API_KEY`, `GEMINI_API_KEY` (added by the owner 2026-10-30).
  GitHub Models does not work from this repository's Actions: `models.github.ai` answers every request,
  even its model catalog, with a plain-text `OK`. Not diagnosed further.
- Model names that exist today (from the providers' model lists, 2026-10-30): Groq `openai/gpt-oss-120b`,
  `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`; Gemini `gemini-3.8-flash`, `gemini-3.5-flash`, `gemini-flash-latest`.
  `llama-3.3-70b-versatile` and `gemini-2.5-flash` are gone for new users.
- `pilot.env` sets what a push runs (now Groq `openai/gpt-oss-120b`, pool 40, n 16).

### Pilot 1 (run 40996423234, Groq `openai/gpt-oss-120b`, seed 20261030)

Eligibility: 34 of a 40-unit pool (ERROR 25, OK 9). Runs: 41 rows for 13–14 units before the run stopped,
most likely at Groq's daily token limit (not confirmed: logs and artifacts cannot be read from the cloud session;
download them with `gh run download 40996423234`). 4 failed runs, all HTTP 400 "Tool choice is none, but model
called a tool" on the forced last step; fixed in `a7219e3` (tools stay declared, a model still calling tools after 8
steps is a failed run).

| arm | ERROR units still WRONG | CORRECT | REMOVED | mean requests | mean input tokens |
|---|---|---|---|---:|---:|
| A pass-through | 10 / 10 | 0 | 0 | 1.0 | ~590 |
| B self-check | 1 / 9 | 2 | 6 | 4.2 | ~4,700 |
| C B + buddie | 0 / 9 | 2 | 7 | 4.3 | ~6,100 |

C − B on paired ERROR units: −0.125 (n 8, 95 % interval −0.375 to 0). OK units: 3, all kept correct in every arm.
A pilot: not pooled with the main run, no claim from it (PROTOCOL.md).

What it suggests: a model told to check its quotations with a source tool already removes nearly all false ones;
buddie adds little on top in that setting. Models mostly REMOVE or paraphrase a false quote rather than restore the
source's words, and some REMOVED rows may be correct replacement quotes the judge does not recognize (similarity to
the original under 0.6).

### Pilot 1, REMOVED rows read by hand (step 1, 2026-10-30)

Artifact downloaded to `data/pilot1/` (ignored by git); the rows are dumped in `data/pilot1/removed_rows.txt`.
13 REMOVED rows (B 6, C 7), read against the unit's label and evidence:

| what the model did | rows | units |
|---|---:|---|
| paraphrase without quotation marks, source lacks the words (AGENT_ABSENT): what ASK_BC asks for | 6 | F089 C, F124 C, F068 B+C, F107 B+C |
| paraphrase, source has near words (AGENT_ALTERED): not restored | 3 | F173 B+C, F001 B |
| false wording kept, only the quotation marks dropped, still linked | 2 | F228 B, F001 C |
| no paragraph: "the source link isn't provided", asks for the URL | 2 | F035 B+C |
| a correct replacement quote from the source | **0** | |

What follows:

- REPLACED_CORRECT (step 2) would not change pilot 1: no REMOVED row is a correct quote the judge missed.
  The two ERROR units counted CORRECT (F200, F261, both arms) restored the source's words.
- REMOVED mixes a good outcome (paraphrase where the source lacks the words, as instructed) with two bad ones:
  the false words kept without quotation marks under the same link, and no paragraph at all.
- F035 is a unit defect, not a model failure: its paragraph is a bare blockquote with no link. In `units.json`
  55 of 251 units (ERROR 50, OK 5) do not contain their `url` in the paragraph (footnote references such as
  `[^30]`, or no link). In arms B and C the model cannot reach the source for them.
- On AGENT_ALTERED units no B or C row restored the exact words; only AGENT_ABSENT-style paraphrase happened.

Done after this reading (PROTOCOL.md, "Changes after data", owner's decision): arm D added; units without their
link excluded in `refetch.py`; REMOVED split into NO_PARAGRAPH / UNQUOTED_KEPT / REPLACED_CORRECT / PARAPHRASED
(`removed_as`, secondary). On pilot 1's 13 rows the split reproduces the hand reading. `pilot.env` runs A–D.

### Next steps, in order

1. **Read the pilot rows by hand**: `gh run download 40996423234`, open `data/judged/audit_sheet.csv`, check the
   REMOVED rows (removed, paraphrased, or replaced with a correct quote?).
2. **Judge**: add an outcome for a replacement quote that is in the source (REPLACED_CORRECT), so REMOVED means only
   dropped or paraphrased. Add a unit test for it.
3. **Arm D** (proposed to the owner, not yet approved in PROTOCOL.md): A's instruction (no request to check) plus
   buddie's feedback, the source tool available. It is the realistic case: agents are usually not told to check
   quotations, and the hook catches them there. D vs A = what the hook alone fixes; D vs B = the hook against asking
   the model to check itself. Record it in PROTOCOL.md under "Changes after data" (decided after the pilot, before
   the main run).
4. **Main run**: every eligible unit (about 200 of 251 expected), Groq `openai/gpt-oss-120b` and Gemini
   `gemini-3.8-flash`, arms A, B, C (and D if approved). Groq's free tier seems to allow about 15 units a day at
   this token use, so run it locally where `arms.py` resumes from `data/runs.jsonl`, or in Actions with a persistent
   copy of `data/` (an Actions run starts empty: download the previous artifact first). Refetch once and reuse
   `data/store` for every model and day, so all arms read the same bytes.
5. **Audit**: a person labels a random 20 % of `audit_sheet.csv` without the arm (PROTOCOL.md).
6. **Product confirmation** (PROTOCOL.md): 20–30 full reports in Claude Code, plugin on against a clean
   `CLAUDE_CONFIG_DIR` with no plugin (the owner has `buddie@synced` installed globally: the no-plugin arm must not
   load it).

### Elsewhere in the project (same day)

- Released 2.0.4, 2.0.5 and 2.0.6; `plugin-stable` is the Claude Code channel and is protected (ruleset
  `plugin-stable-channel`). The Anthropic directory submission tracking `plugin-stable` was sent 2026-10-30 with
  the webhook connected; avoid releases while it is in review.
- Listings to update by hand: MCPRush (name `buddie`, icon, 8 tools, access labels from `docs/listing-copy.md`),
  Glama (name, icon), Cline #336 and Kilo #484 (bump from 2.0.1).
- BDX-002 (GitHub evidence efficiency) is shelved: it measures cost of reading GitHub through buddie, not whether
  fewer false claims reach a person, and is not runnable as it stands.
