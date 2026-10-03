"""E014: Search Arena's primary_intent for every sampled report (run in data/ after run.py): writes ../intents.json,
which compare.py uses for the by-intent split (a post-hoc split, not part of the sample design)."""
import json
import pandas as pd

df = pd.read_parquet("sa24k.parquet")
intent = {r[f"system_{s}_metadata"]["conv_id"]: r["primary_intent"] for _, r in df.iterrows() for s in "ab"}
files = json.load(open("../summary.json"))["sampled_sha256"]
json.dump({f: intent[f.split("/")[1].rsplit("-", 1)[0]] for f in sorted(files)}, open("../intents.json", "w"), indent=1)
