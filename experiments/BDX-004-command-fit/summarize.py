"""BDX-004 rows (run.py) in numbers, as GitHub notices (at most 10 a step), and a sheet of every judged command for
the owner's reading (the pilot) or the blind audit.

    python summarize.py data/pilot.jsonl --sheet data/pilot-commands.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import judge as jd  # noqa: E402


# Why a command is UNKNOWN (PROTOCOL 2026-11-02): the profile does not say (a data gap, a property of what the person
# granted and of the machine) or the judge cannot read the command (a judge gap, what the pilot limits to 25 %)
DATA_GAP = ("unobserved", "not established", "not observed", "placeholder", "establish that", "does not establish", "not granted")


def unknown_cause(command: dict) -> str:
    detail = (command.get("detail") or "").lower()
    return "data" if any(k in detail for k in DATA_GAP) else "judge"


def bootstrap(pairs, iters=4000, seed=7):
    if len(pairs) < 5:
        return None
    rng = random.Random(seed)
    stats = sorted(sum(b - a for a, b in (pairs[rng.randrange(len(pairs))] for _ in pairs)) / len(pairs)
                   for _ in range(iters))
    return [round(stats[int(0.025 * iters)], 3), round(stats[int(0.975 * iters) - 1], 3)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs")
    ap.add_argument("--sheet")
    ap.add_argument("--examples", type=int, default=0, help="per verdict reason, this many judged commands as notices")
    ap.add_argument("--dump", type=int, default=0,
                    help="this many whole answers with a WONT_RUN or UNKNOWN command, as notices (a step shows 10)")
    a = ap.parse_args(argv)
    rows = [json.loads(x) for x in Path(a.runs).read_text(encoding="utf-8").splitlines() if x.strip()]
    ok = [r for r in rows if "verdict" in r]
    notes = [f"{len(rows)} rows, {len(rows) - len(ok)} failed; per arm {dict(Counter(r['arm'] for r in ok))}"]
    by = defaultdict(list)
    for r in ok:
        by[(r["model"], r["arm"])].append(r)
    cells = []
    for (model, arm), rs in sorted(by.items()):
        st = Counter(r["verdict"]["status"] for r in rs)
        leaves = [c for r in rs for c in jd.leaf_commands(r["verdict"]["commands"])]
        cs = Counter(c["status"] for c in leaves)
        reasons = Counter(c["reason"] for c in leaves if c["status"] == "WONT_RUN")
        n = len(rs)
        targeting = dict(Counter(r['verdict'].get('targeting', 'UNRECORDED') for r in rs))
        measured = [r['verdict'] for r in rs if 'commands_total' in r['verdict'] and 'commands_for_profile' in r['verdict']]
        audience = (f"; targeting {targeting}; offered {sum(v['commands_total'] for v in measured) / len(measured):.1f}, "
                    f"for profile {sum(v['commands_for_profile'] for v in measured) / len(measured):.1f} "
                    f"({len(measured)}/{n} measured)" if measured else f"; targeting {targeting}; audience counts UNRECORDED")
        cells.append(f"{model} | {arm}: n {n}; answers " + ", ".join(f"{k} {v / n:.2f}" for k, v in sorted(st.items()))
                     + f"; commands {len(leaves)}: " + ", ".join(f"{k} {v}" for k, v in sorted(cs.items()))
                     + f" (UNKNOWN {cs['UNKNOWN'] / max(1, len(leaves)):.2f}: judge gap "
                     f"{sum(unknown_cause(c) == 'judge' for c in leaves if c['status'] == 'UNKNOWN') / max(1, len(leaves)):.2f}, "
                     f"data gap {sum(unknown_cause(c) == 'data' for c in leaves if c['status'] == 'UNKNOWN') / max(1, len(leaves)):.2f})"
                     + f"; WONT_RUN reasons {dict(reasons)}"
                     + f"; tool calls {sum(r['tool_calls'] for r in rs) / n:.2f}, requests "
                     f"{sum(r['requests'] for r in rs) / n:.2f}, sent chars {sum(r['sent_chars'] for r in rs) / n:.0f}" + audience)
    paired = []
    models = {r["model"] for r in ok}
    for model in sorted(models):
        for outcome in ("OK", "BROKEN"):  # OK share B-A is the registered primary, so it is printed first
            cell = {(r["profile"], r["task"], r["arm"]): r["verdict"]["status"] == outcome
                    for r in ok if r["model"] == model}
            for x, y in (("A", "B"), ("A", "C"), ("B", "D"), ("A", "D")):
                pairs = [(int(cell[(p, t, x)]), int(cell[(p, t, y)])) for (p, t, arm) in cell if arm == x
                         and (p, t, y) in cell]
                if pairs:
                    paired.append(f"{model} | {y}-{x} {outcome}: n {len(pairs)}, diff "
                                  f"{sum(b - a for a, b in pairs) / len(pairs):.3f}, ci {bootstrap(pairs)}")
    lines = [] if a.dump else paired + notes + cells  # a dump step has its own 10 notices
    for i in range(0, len(lines), 2):
        print("::notice title=BDX-004 " + str(i // 2 + 1) + "::" + " || ".join(lines[i:i + 2]))
    if a.examples:  # what the owner would read in the sheet, when the artifact cannot be fetched
        groups = defaultdict(list)
        for r in ok:
            shells = {c.get("shell") for c in r["verdict"]["commands"]}
            for c in jd.leaf_commands(r["verdict"]["commands"]):
                if c["status"] in ("WONT_RUN", "UNKNOWN"):
                    groups[f"{c['status']} {c.get('reason') or ''}".strip()].append(
                        f"{r['profile']}/{r['task']} [{c.get('shell')}; answer shells {len(shells)}] "
                        f"{c['text'][:70]!r} ({(c.get('detail') or '')[:50]})")
        multi = sum(len({c.get('shell') for c in r["verdict"]["commands"]}) > 1 for r in ok)
        print(f"::notice title=BDX-004 shape::{multi} of {len(ok)} answers have blocks for more than one shell; "
              f"commands per answer {sum(len(list(jd.leaf_commands(r["verdict"]["commands"]))) for r in ok) / max(1, len(ok)):.1f}")
        rng = random.Random(3)
        for g, items in sorted(groups.items()):
            rng.shuffle(items)
            print(f"::notice title=BDX-004 examples {g} ({len(items)})::" + " || ".join(items[:a.examples]))
    if a.dump:  # whole answers, so a judge fix can be made from what models write
        picked = [r for r in ok if any(c["status"] in ("WONT_RUN", "UNKNOWN")
                                       for c in jd.leaf_commands(r["verdict"]["commands"]))]
        random.Random(5).shuffle(picked)
        for r in picked[:a.dump]:
            bad = [f"{c['status']} {c.get('reason') or ''} `{c['text'][:60]}`" for c in jd.leaf_commands(
                r["verdict"]["commands"]) if c["status"] in ("WONT_RUN", "UNKNOWN")][:6]
            print(f"::notice title=BDX-004 answer {r['profile']}/{r['task']}::verdicts: {'; '.join(bad)} ===== "
                  + r["final"][:5000].replace("\r", "").replace("\n", " ⏎ "))
    if a.sheet:
        with open(a.sheet, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["profile", "task", "arm", "answer_status", "shell", "command", "verdict", "reason", "detail",
                        "owner: holds? (y/n)", "owner note"])
            for r in ok:
                for c in jd.leaf_commands(r["verdict"]["commands"]):
                    w.writerow([r["profile"], r["task"], r["arm"], r["verdict"]["status"], c.get("shell"), c["text"],
                                c["status"], c.get("reason"), c.get("detail"), "", ""])
                if not r["verdict"]["commands"]:
                    w.writerow([r["profile"], r["task"], r["arm"], r["verdict"]["status"], "", r["final"][:300],
                                "", "", "", "", ""])
    return 0


if __name__ == "__main__":
    sys.exit(main())
