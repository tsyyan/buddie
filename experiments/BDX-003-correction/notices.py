"""Print a run's eligibility and summary as GitHub Actions notices, so the numbers can be read from the run's
annotations (API) without downloading the artifact. At most 10 notices.

    python notices.py data
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from common import read_json, read_jsonl


def lines(data: Path) -> list[tuple[str, str]]:
    out = []
    if (data / "eligible.json").exists():
        rows = read_json(data / "eligible.json")["rows"]
        c = Counter((r["gold"], r.get("stratum") or r["reason"]) for r in rows)
        out.append(("BDX-003 eligible", f"{sum(r['eligible'] for r in rows)} of {len(rows)}: "
                    + "; ".join(f"{g} {k} {n}" for (g, k), n in sorted(c.items()))))
    runs = read_jsonl(data / "runs.jsonl")
    if runs:
        errs = [r["error"] for r in runs if "error" in r]
        out.append(("BDX-003 runs", f"{len(runs)} rows; per arm {dict(Counter(r['arm'] for r in runs))}; "
                    f"errors {len(errs)}" + (f"; first: {errs[0][:300]}" if errs else "")))
    if (data / "judged" / "summary.json").exists():
        s = read_json(data / "judged" / "summary.json")
        cells = [f"{k}: n {c['n']}, correct {c['correct']}, wrong {c['wrong']}, removed {c['removed']}, "
                 f"req {c['mean_requests']}, tok {c['mean_prompt_tokens']}/{c['mean_completion_tokens']}, "
                 f"failed {c['failed_runs']}" for k, c in s["cells"].items()]
        for i in range(0, len(cells), 3):
            out.append((f"BDX-003 cells {i // 3 + 1}", " || ".join(cells[i:i + 3])))
        out.append(("BDX-003 paired", " || ".join(
            f"{k}: n {p['n']}, diff {p['diff']}, ci {p['ci95']}, only-earlier-bad {p['only_a_bad']}, "
            f"only-later-bad {p['only_b_bad']}" for k, p in s["paired"].items())))
    return out[:10]


if __name__ == "__main__":
    for title, msg in lines(Path(sys.argv[1] if len(sys.argv) > 1 else "data")):
        print(f"::notice title={title}::{msg.replace('%', '%25').replace(chr(10), '%0A')}")
