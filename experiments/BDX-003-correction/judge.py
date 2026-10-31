"""Judge the arms' final paragraphs without buddie, and summarize.

For each run the target quotation is looked for among the final paragraph's quoted spans (the most similar one).
  REMOVED  no quoted span is at least --min-sim like it (the agent dropped it or turned it into a paraphrase);
  CORRECT  the span is in the source text (common.in_text, the same snapshot every arm saw);
  WRONG    the span is not in the source text: a false quotation still reaches the reader.
`flagged`: the paragraph says something is unverified (a 'buddie:' line, "unverified", "could not verify").

`removed_as` splits REMOVED (secondary, added after pilot 1; PROTOCOL.md "Changes after data"), first match wins:
  NO_PARAGRAPH      the answer is not the paragraph: under --min-overlap of its words are left (a question, a refusal);
  UNQUOTED_KEPT     the target's words are still there without quotation marks (a window at least --kept-sim like it);
  REPLACED_CORRECT  a new quoted span, not in the paragraph before, that is in the source text;
  PARAPHRASED       none of these: dropped or said in other words.

Primary endpoint, pre-registered (PROTOCOL.md): on ERROR units, the share still WRONG, arm C against arm B.
Secondary: on OK units, the share no longer CORRECT (WRONG or REMOVED): what a fix costs good quotes. Cost:
requests, tokens, seconds per unit. Failed runs (API errors) are reported, not dropped silently.

    python judge.py --units data/units.json --store data/store --runs data/runs.jsonl --out data/judged
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import random
import re
from collections import defaultdict

from common import best_span, in_text, norm, page_text, quoted_spans, read_json, read_jsonl, similarity, write_json

FLAG = re.compile(r"^\s*buddie:|\bunverified\b|could not (?:be )?verif|cannot verify|not (?:be )?verified", re.I | re.M)
WORDS = re.compile(r"\w{4,}")
REMOVED_AS = ("NO_PARAGRAPH", "UNQUOTED_KEPT", "REPLACED_CORRECT", "PARAPHRASED")


def overlap(paragraph: str, final: str) -> float:
    """Share of the paragraph's words (4+ letters) still in the final answer."""
    want = set(WORDS.findall(norm(paragraph)))
    return len(want & set(WORDS.findall(norm(final)))) / len(want) if want else 1.0


def kept_unquoted(quote: str, body: str) -> float:
    """How like the quote the closest run of words in the body is (quoted or not)."""
    q, words = norm(quote), norm(body).split()
    n = len(q.split())
    best = 0.0
    for size in {max(1, n - 1), n, n + 1, n + 2}:
        for i in range(max(1, len(words) - size + 1)):
            best = max(best, similarity(q, " ".join(words[i:i + size])))
    return best


def removed_as(unit: dict, body: str, text: str, min_overlap: float, kept_sim: float) -> str:
    if overlap(unit["paragraph"], body) < min_overlap:
        return "NO_PARAGRAPH"
    if kept_unquoted(unit["quote"], body) >= kept_sim:
        return "UNQUOTED_KEPT"
    before = {norm(s) for s in quoted_spans(unit["paragraph"])}
    if any(norm(s) not in before and len(s.split()) >= 4 and in_text(s, text) for s in quoted_spans(body)):
        return "REPLACED_CORRECT"
    return "PARAPHRASED"


def judge(unit: dict, final: str, text: str, min_sim: float, min_overlap: float = 0.3, kept_sim: float = 0.85) -> dict:
    body = "\n".join(line for line in (final or "").splitlines() if not line.strip().lower().startswith("buddie:"))
    span, sim = best_span(unit["quote"], body)
    detail = None
    if span is None or sim < min_sim:
        outcome = "REMOVED"
        detail = removed_as(unit, body, text, min_overlap, kept_sim)
    else:
        outcome = "CORRECT" if in_text(span, text) else "WRONG"
    return {"outcome": outcome, "removed_as": detail, "similarity": round(sim, 3), "span": span,
            "verbatim_kept": bool(span) and norm(span) == norm(unit["quote"]),
            "flagged": bool(FLAG.search(final or "")),
            "length_ratio": round(len(final or "") / max(1, len(unit["paragraph"])), 2)}


PAIRS = (("B", "C"), ("A", "C"), ("A", "B"), ("A", "D"), ("B", "D"),  # D: added after pilot 1 (PROTOCOL.md)
         ("C", "E"), ("B", "E"))  # E: added after the gpt-oss main run (PROTOCOL.md, 2026-10-31)


def bootstrap_diff(pairs: list[tuple[int, int]], iters: int = 4000, seed: int = 7) -> list[float] | None:
    """95 % interval of mean(b) - mean(a) over paired units."""
    if len(pairs) < 5:
        return None
    rng = random.Random(seed)
    stats = []
    for _ in range(iters):
        s = [pairs[rng.randrange(len(pairs))] for _ in pairs]
        stats.append(sum(b - a for a, b in s) / len(s))
    stats.sort()
    return [round(stats[int(0.025 * iters)], 3), round(stats[int(0.975 * iters) - 1], 3)]


def summarize(judged: list[dict]) -> dict:
    out: dict = {"cells": {}, "paired": {}}
    by = defaultdict(list)
    for r in judged:
        by[(r["model"], r["arm"], r["gold"])].append(r)
    for (model, arm, gold), rows in sorted(by.items()):
        ok = [r for r in rows if "error" not in r]
        n = len(ok)
        cell = {"n": n, "failed_runs": len(rows) - n}
        for o in ("CORRECT", "WRONG", "REMOVED"):
            cell[o.lower()] = round(sum(r["outcome"] == o for r in ok) / n, 3) if n else None
        for d in REMOVED_AS:
            cell[d.lower()] = round(sum(r.get("removed_as") == d for r in ok) / n, 3) if n else None
        for k in ("requests", "tool_calls", "prompt_tokens", "completion_tokens", "seconds", "feedback_rounds"):
            vals = [r.get(k) or 0 for r in ok]
            cell["mean_" + k] = round(sum(vals) / n, 2) if n else None
        cell["flagged"] = round(sum(r["flagged"] for r in ok) / n, 3) if n else None
        out["cells"][f"{model} | {arm} | {gold}"] = cell
    # per provider, next to the pooled cells: a provider effect would show here (PROVIDERS.md)
    out["providers"] = {}
    byp = defaultdict(list)
    for r in judged:
        byp[(r["model"], r.get("provider") or "?", r["arm"], r["gold"])].append(r)
    for (model, prov, arm, gold), rows in sorted(byp.items()):
        ok = [r for r in rows if "error" not in r]
        out["providers"][f"{model} | {prov} | {arm} | {gold}"] = {
            "n": len(ok), "failed_runs": len(rows) - len(ok),
            **{o.lower(): round(sum(r["outcome"] == o for r in ok) / len(ok), 3) if ok else None
               for o in ("CORRECT", "WRONG", "REMOVED")}}
    # paired: the same unit, model and rep in two arms; 1 = the bad outcome for that gold
    bad = {"ERROR": lambda r: r["outcome"] == "WRONG", "OK": lambda r: r["outcome"] != "CORRECT"}
    index = {(r["model"], r["unit"], r["rep"], r["arm"]): r for r in judged if "error" not in r}
    for model in sorted({r["model"] for r in judged}):
        for gold in ("ERROR", "OK"):
            for a, b in PAIRS:
                pairs = []
                for (m, u, rep, arm), r in index.items():
                    if m == model and arm == a and r["gold"] == gold and (m, u, rep, b) in index:
                        pairs.append((int(bad[gold](r)), int(bad[gold](index[(m, u, rep, b)]))))
                if pairs:
                    out["paired"][f"{model} | {gold} | {b}-{a}"] = {
                        "n": len(pairs), "diff": round(sum(y - x for x, y in pairs) / len(pairs), 3),
                        "ci95": bootstrap_diff(pairs),
                        "only_a_bad": sum(x and not y for x, y in pairs), "only_b_bad": sum(y and not x for x, y in pairs)}
    return out


def markdown(s: dict) -> str:
    lines = ["| model | arm | gold | n | correct | wrong | removed | flagged | requests | tokens in | tokens out | s | failed |",
             "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for key, c in s["cells"].items():
        model, arm, gold = key.split(" | ")
        lines.append(f"| {model} | {arm} | {gold} | {c['n']} | {c['correct']} | {c['wrong']} | {c['removed']} | "
                     f"{c['flagged']} | {c['mean_requests']} | {c['mean_prompt_tokens']} | "
                     f"{c['mean_completion_tokens']} | {c['mean_seconds']} | {c['failed_runs']} |")
    lines += ["", "REMOVED, split (share of all runs in the cell):", "",
              "| model | arm | gold | " + " | ".join(d.lower() for d in REMOVED_AS) + " |",
              "|---|---|---|" + "---:|" * len(REMOVED_AS)]
    for key, c in s["cells"].items():
        lines.append(f"| {key} | " + " | ".join(str(c.get(d.lower())) for d in REMOVED_AS) + " |")
    lines += ["", "Per provider:", "", "| model | provider | arm | gold | n | correct | wrong | removed | failed |",
              "|---|---|---|---|---:|---:|---:|---:|---:|"]
    for key, c in s.get("providers", {}).items():
        lines.append(f"| {key} | {c['n']} | {c['correct']} | {c['wrong']} | {c['removed']} | {c['failed_runs']} |")
    lines += ["", "Paired (bad = WRONG on ERROR units; not CORRECT on OK units), later arm minus earlier:", "",
              "| comparison | n | diff | 95 % CI | only earlier bad | only later bad |", "|---|---:|---:|---|---:|---:|"]
    for key, p in s["paired"].items():
        lines.append(f"| {key} | {p['n']} | {p['diff']} | {p['ci95']} | {p['only_a_bad']} | {p['only_b_bad']} |")
    return "\n".join(lines) + "\n"


def blind_sheet(judged: list[dict], units: dict, path_csv, path_key, seed: int = 11) -> None:
    """A sheet for a person to audit outcomes without seeing the arm; the key maps rows back."""
    rows = [r for r in judged if "error" not in r]
    random.Random(seed).shuffle(rows)
    key = []
    with open(path_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["row", "source_url", "original_quote", "final_paragraph", "auto_outcome", "your_outcome", "note"])
        for i, r in enumerate(rows, 1):
            u = units[r["unit"]]
            w.writerow([i, u["url"], u["quote"], r["final"], r["outcome"], "", ""])
            key.append({"row": i, "unit": r["unit"], "arm": r["arm"], "model": r["model"], "rep": r["rep"],
                        "check": hashlib.sha256((r["final"] or "").encode()).hexdigest()[:12]})
    write_json(path_key, key)


def main(argv=None) -> int:
    from pathlib import Path

    from buddie.verbatim.store import Store
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--units", required=True)
    ap.add_argument("--store", required=True)
    ap.add_argument("--runs", required=True)
    ap.add_argument("--out", required=True, help="directory")
    ap.add_argument("--min-sim", type=float, default=0.6)
    ap.add_argument("--min-overlap", type=float, default=0.3, help="below it a REMOVED answer is NO_PARAGRAPH")
    ap.add_argument("--kept-sim", type=float, default=0.85, help="from it a REMOVED quote is UNQUOTED_KEPT")
    a = ap.parse_args(argv)
    units = {u["id"]: u for u in read_json(a.units)["units"]}
    store = Store(a.store)
    texts: dict[str, str | None] = {}
    judged = []
    for r in read_jsonl(a.runs):
        u = units[r["unit"]]
        row = {k: r.get(k) for k in ("unit", "arm", "model", "provider", "rep", "requests", "tool_calls", "prompt_tokens",
                                       "completion_tokens", "seconds", "feedback_rounds", "final")}
        row["gold"] = u["gold"]
        if "error" in r:
            row["error"] = r["error"]
        else:
            if u["url"] not in texts:
                texts[u["url"]] = page_text(store, u["url"])[1]
            row |= judge(u, r.get("final") or "", texts[u["url"]] or "", a.min_sim, a.min_overlap, a.kept_sim)
        judged.append(row)
    out = Path(a.out)
    write_json(out / "judged.json", judged)
    s = summarize(judged)
    write_json(out / "summary.json", s)
    (out / "summary.md").write_text(markdown(s), encoding="utf-8")
    blind_sheet(judged, units, out / "audit_sheet.csv", out / "audit_key.json")
    print(markdown(s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
