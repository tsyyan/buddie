"""E011 step 2b. Run in data/ after run.py: re-read every claim's kind with the frozen rules (tsyyan/lab 07b2dd0).

run.py's first runner had loaded report.py at 4ae04e9, before the list rule ("“A” or “B”" shares A's kind, 07b2dd0)
was added; the rule was committed before results.json was read. Kinds only relabel misses (check.py: NOT_FOUND /
UNCERTAIN with a kind -> NOT_A_QUOTE, the old verdict in "miss"), so they are recomputed here without fetching again.
Rewrites results.json in place.
"""
import json, os, sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.getcwd())
import report_030
from verbatim.report import from_markdown

out = json.load(open("results.json"))
changed = 0
for o in out:
    text = Path("md", o["system"], f"row-{o['id']}.md").read_text()
    new = {c["id"]: c.get("not_quote") for c in from_markdown(text)[0]}
    old = {c["id"]: c.get("not_quote") for c in report_030.from_markdown(text)[0]}
    for c in o["claims"]:
        kind = new[c["id"]]
        base = c.get("miss") or c["verdict"]
        verdict = "NOT_A_QUOTE" if base in ("NOT_FOUND", "UNCERTAIN") and kind else base
        changed += verdict != c["verdict"] or kind != c.get("not_quote")
        c.pop("miss", None)
        c.pop("not_quote", None)
        if kind:
            c["not_quote"] = kind
        if verdict == "NOT_A_QUOTE":
            c["miss"] = base
        c["verdict"], c["not_quote_031"], c["not_quote_030"] = verdict, kind, old[c["id"]]
Path("results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
print("claims changed", changed)
