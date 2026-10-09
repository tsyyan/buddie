Hook events in the shape Claude Code sends them (keys of a recorded `Stop` and `PreToolUse` event; `{transcript}` and
`{cwd}` are filled in by tests/test_smoke.py). `transcript.jsonl` is a short session: one `pytest` run that printed
`3 passed`, then the answer the `Stop` event checks: bare in `transcript.jsonl`, anchored in
`transcript-anchored.jsonl`.
