"""BDX-003 product run, judged without buddie (common.in_text against the run's snapshots), from what the reader saw:
the assistant's text messages in order (product.py `texts`).

paragraph (per run, the unit's target quotation):
  every message that states the target (a quoted span at least --min-sim like it) is a statement, right or wrong.
  CORRECT  the last statement is in the source
  WRONG    the last statement is not, and nothing after it flags it
  FLAGGED  the last statement is not, and a later message flags it (a `buddie:` line, "could not verify" ...)
  REMOVED  no message states it
  shown_wrong: a wrong statement reached the screen at some point (Claude Code shows every message).
summary (per run, every quotation of 4+ words):
  false_shown  quoted spans not in the source, in any message
  false_final  those in the last message that quotes at all, unless a later message flags them
Cells: per task, gold and condition; paired with-without by unit (bootstrap, judge.bootstrap_diff).

    python product_judge.py --units data/units.json --store data/store --runs data/product-runs.jsonl --out data/product
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import best_span, in_text, page_text, quoted_spans, read_json, read_jsonl, write_json  # noqa: E402
from judge import FLAG, bootstrap_diff  # noqa: E402


def _body(t: str) -> str:
    return "\n".join(line for line in t.splitlines() if not line.strip().lower().startswith("buddie:"))


def paragraph(unit: dict, texts: list[str], page: str, min_sim: float) -> dict:
    last, last_i, shown_wrong = None, -1, False
    for i, t in enumerate(texts):
        span, sim = best_span(unit["quote"], _body(t))
        if span is not None and sim >= min_sim:
            ok = in_text(span, page)
            shown_wrong |= not ok
            last, last_i = ok, i
    if last is None:
        outcome = "REMOVED"
    elif last:
        outcome = "CORRECT"
    else:
        outcome = "FLAGGED" if any(FLAG.search(t) for t in texts[last_i:]) else "WRONG"
    return {"outcome": outcome, "shown_wrong": shown_wrong}


def summary(texts: list[str], page: str) -> dict:
    def false(t):
        return [s for s in quoted_spans(_body(t)) if len(s.split()) >= 4 and not in_text(s, page)]
    shown = sorted({s for t in texts for s in false(t)})
    quoting = [i for i, t in enumerate(texts) if any(len(s.split()) >= 4 for s in quoted_spans(_body(t)))]
    final = false(texts[quoting[-1]]) if quoting else []
    flagged = bool(quoting) and any(FLAG.search(t) for t in texts[quoting[-1]:])
    return {"quotes": len(quoted_spans(_body(texts[quoting[-1]]))) if quoting else 0,
            "false_shown": len(shown), "false_final": 0 if flagged else len(final), "flagged": flagged}


def main(argv=None) -> int:
    from buddie.verbatim.store import Store
    ap = argparse.ArgumentParser()
    ap.add_argument("--units", required=True)
    ap.add_argument("--store", required=True)
    ap.add_argument("--runs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-sim", type=float, default=0.6)
    a = ap.parse_args(argv)
    units = {u["id"]: u for u in read_json(Path(a.units))}
    store = Store(Path(a.store))
    rows, failed, skipped = [], defaultdict(int), 0
    for r in read_jsonl(Path(a.runs)):
        if "error" in r:
            failed[(r["task"], r["gold"], r["condition"])] += 1
            continue
        _, page = page_text(store, r["url"])
        if page is None:
            skipped += 1
            continue
        j = paragraph(units[r["unit"]], r["texts"], page, a.min_sim) if r["task"] == "paragraph" \
            else summary(r["texts"], page)
        rows.append({**{k: r.get(k) for k in ("unit", "task", "gold", "condition", "rep", "turns", "hook_returns",
                                               "input_tokens", "output_tokens", "seconds", "denied")}, **j})
    cells = {}
    by = defaultdict(list)
    for r in rows:
        by[(r["task"], r["gold"], r["condition"])].append(r)
    for (task, gold, cond), rs in sorted(by.items()):
        n = len(rs)
        c = {"n": n, "failed_runs": failed[(task, gold, cond)]}
        if task == "paragraph":
            for o in ("CORRECT", "WRONG", "FLAGGED", "REMOVED"):
                c[o.lower()] = round(sum(r["outcome"] == o for r in rs) / n, 3)
            c["shown_wrong"] = round(sum(r["shown_wrong"] for r in rs) / n, 3)
        else:
            c["runs_false_final"] = round(sum(r["false_final"] > 0 for r in rs) / n, 3)
            c["runs_false_shown"] = round(sum(r["false_shown"] > 0 for r in rs) / n, 3)
            c["mean_quotes"] = round(sum(r["quotes"] for r in rs) / n, 2)
        for k in ("turns", "hook_returns", "input_tokens", "output_tokens", "seconds"):
            c["mean_" + k] = round(sum(r.get(k) or 0 for r in rs) / n, 1)
        cells[f"{task} | {gold} | {cond}"] = c
    # paired, with minus without, on the same unit (rep 0): bad = WRONG (paragraph), a false quote left (summary)
    paired = {}
    for task, gold in sorted({(r["task"], r["gold"]) for r in rows}):
        def bad(r):
            return (r["outcome"] == "WRONG") if task == "paragraph" else (r["false_final"] > 0)
        w = {r["unit"]: bad(r) for r in by[(task, gold, "with")] if r["rep"] == 0}
        wo = {r["unit"]: bad(r) for r in by[(task, gold, "without")] if r["rep"] == 0}
        pairs = [(int(wo[u]), int(w[u])) for u in w.keys() & wo.keys()]
        if pairs:
            paired[f"{task} | {gold} | with-without"] = {
                "n": len(pairs), "diff": round(sum(b - a for a, b in pairs) / len(pairs), 3),
                "ci": bootstrap_diff(pairs), "only_without_bad": sum(a and not b for a, b in pairs),
                "only_with_bad": sum(b and not a for a, b in pairs)}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "judged.json", rows)
    write_json(out / "summary.json", {"cells": cells, "paired": paired})
    print(f"::notice title=BDX-003 product judged::{len(rows)} rows judged; failed runs {dict(failed)}; "
          f"skipped for an unreadable snapshot {skipped}")
    for k, c in cells.items():
        print(f"::notice title=BDX-003 product {k}::{c}")
    for k, p in paired.items():
        print(f"::notice title=BDX-003 product paired {k}::{p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
