# BDX-003: correction of false quotations, with and without buddie

Status 2026-10-30: built and tested without a model; the pilot runs in GitHub Actions on GitHub Models' free tier.
No results yet. The question, arms, outcomes and stop rules are fixed in [PROTOCOL.md](PROTOCOL.md).

| File | What it does |
|---|---|
| `units.py` | 251 units from the blind labels of E008 and E011 (a quotation, its paragraph, its link, ERROR or OK) |
| `refetch.py` | fetches the sources again (direct, then web archive); keeps a unit only if its label still holds |
| `arms.py` | runs arms A (pass-through), B (self-check with a source tool), C (B plus buddie's feedback) |
| `judge.py` | judges the final paragraphs with an independent matcher (not buddie), pairs the arms, writes an audit sheet |
| `common.py` | the matcher, page text, file helpers |

## Run

In GitHub Actions (free, the workflow's own token with `models: read`): push to `experiment/bdx-003-pilot`, or run
the `bdx003` workflow by hand (model, pool, n, arms, request budget). The run summary shows the table; the artifact
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
