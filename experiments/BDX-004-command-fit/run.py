"""BDX-004 arms (PROTOCOL.md): a model answers a person's task; the answer's commands are judged against the
profile (judge.py), never run.

  A  the task only
  B  the task and the environment_snapshot tool, answered from the profile (tool.py)
  C  the task, the snapshot of the task's categories in the first message
  D  B, then the judge's WONT_RUN objections as feedback, at most --rounds rounds (the candidate gate)

Rows go to --out (one per unit, arm, model; resumable: rows already there are skipped, a provider's quota or
balance stops the run and leaves no row). Each row keeps the final answer, every answer shown, the tool calls and
the judge's verdict.

    python run.py --units tasks/units.json --pilot 40 --arms A --provider ovh,groq --model openai/gpt-oss-120b \\
        --out data/pilot.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import client as cl  # noqa: E402
import judge as jd  # noqa: E402
import tool as tl  # noqa: E402

SYSTEM = ("You help a person with their own computer. When the answer involves commands, give the exact commands "
          "for them to run.")
TOOL = json.loads((HERE / "tool_schema.json").read_text(encoding="utf-8"))
MAX_TOOL_STEPS = 6
RETURNED = ("buddie (a plugin that checks claims against evidence, without a model) sent this answer back: the "
            "commands below cannot run on this person's machine, by what buddie observed of it.")
FIX = "Fix each one for this machine, or say what the person must do first. Reply with the whole corrected answer."


def tasks() -> dict:
    data = json.loads((HERE / "tasks/tasks.json").read_text(encoding="utf-8"))
    return {t["id"]: t for t in (data["tasks"] if isinstance(data, dict) else data)}


def pilot_units(pairs: list, n: int, seed: int) -> list:
    """n units stratified by profile (n / profiles each), seeded."""
    by = {}
    for p, t in pairs:
        by.setdefault(p, []).append((p, t))
    rng = random.Random(seed)
    per = max(1, n // len(by))
    out = []
    for p in sorted(by):
        units = sorted(by[p])
        rng.shuffle(units)
        out += units[:per]
    return out


def feedback(verdict: dict) -> str | None:
    bad = [c for c in jd.leaf_commands(verdict["commands"]) if c["status"] == "WONT_RUN"]
    if not bad:
        return None
    lines = [f"- `{c['text']}`: {c['reason']}" + (f" ({c['detail']})" if c.get("detail") else "") for c in bad]
    return "\n".join([RETURNED, *lines, FIX])


def chat(client, messages, tools, rec):
    rec["sent_chars"] += len(json.dumps(messages, ensure_ascii=False))
    msg, usage = client.chat(messages, tools)
    rec["requests"] += 1
    rec["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
    rec["completion_tokens"] += int(usage.get("completion_tokens") or 0)
    return msg


def answer(client, messages, profile, with_tool, rec) -> str:
    for _ in range(MAX_TOOL_STEPS + 1):
        msg = chat(client, messages, [TOOL] if with_tool else None, rec)
        calls = msg.get("tool_calls") or []
        if not calls:
            return msg.get("content") or ""
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for c in calls:
            rec["tool_calls"] += 1
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
                rec["categories_asked"] += [x for x in args.get("categories", []) if isinstance(x, str)]
                out = json.dumps(tl.environment_snapshot(args, profile), ensure_ascii=False)
            except (ValueError, KeyError, TypeError) as e:
                out = json.dumps({"error": str(e)[:200]})
            messages.append({"role": "tool", "tool_call_id": c.get("id"), "content": out})
    messages.append({"role": "user", "content": "No more tool calls. Reply now with your answer."})
    msg = chat(client, messages, [TOOL] if with_tool else None, rec)
    if msg.get("tool_calls"):
        raise RuntimeError(f"still calling tools after {MAX_TOOL_STEPS} steps")
    return msg.get("content") or ""


def run_arm(client, profile_id: str, task: dict, arm: str, rounds: int) -> dict:
    profile = tl.load_profile(profile_id)
    rec = {"requests": 0, "tool_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "sent_chars": 0,
           "categories_asked": [], "feedback_rounds": 0, "shown": []}
    first = task["prompt"]
    if arm == "C":
        snap = tl.environment_snapshot({"categories": task["categories"], "task": task["id"]}, profile)
        first += ("\n\nWhat buddie observed of my machine (environment_snapshot):\n"
                  + json.dumps(snap, ensure_ascii=False))
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": first}]
    text = answer(client, messages, profile, arm in ("B", "D"), rec)
    rec["shown"].append(text)
    if arm == "D":
        for _ in range(rounds):
            fb = feedback(jd.judge_answer(text, profile_id, task["id"]))
            if fb is None:
                break
            rec["feedback_rounds"] += 1
            messages += [{"role": "assistant", "content": text}, {"role": "user", "content": fb}]
            text = answer(client, messages, profile, True, rec)
            rec["shown"].append(text)
    rec["final"] = text
    rec["verdict"] = jd.judge_answer(text, profile_id, task["id"])
    rec["first_verdict"] = jd.judge_answer(rec["shown"][0], profile_id, task["id"])["status"]
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--units", default=str(HERE / "tasks/units.json"))
    ap.add_argument("--pilot", type=int, help="the judge-validation pilot: n units stratified by profile")
    ap.add_argument("--n", type=int, help="the first n units in seeded order (default: all)")
    ap.add_argument("--seed", type=int, default=20261101)
    ap.add_argument("--exclude-pilot-seed", type=int, action="append", default=[],
                    help="leave out the units an earlier pilot with this seed drew (a repeated pilot uses others)")
    ap.add_argument("--arms", default="A,B,C,D")
    ap.add_argument("--provider", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--rpm", type=float)
    ap.add_argument("--max-requests", type=int, default=2000)
    ap.add_argument("--max-wait", type=float, default=180)
    ap.add_argument("--minutes", type=float, default=300)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    pairs = [tuple(p) for p in json.loads(Path(a.units).read_text(encoding="utf-8"))["pairs"]]
    if a.pilot:
        used = {u for s in a.exclude_pilot_seed for u in pilot_units(pairs, a.pilot, s)}
        units = pilot_units([p for p in pairs if p not in used], a.pilot, a.seed)
    else:
        units = sorted(pairs)
        random.Random(a.seed).shuffle(units)
        units = units[:a.n] if a.n else units
    all_tasks, arms = tasks(), a.arms.split(",")
    if set(arms) - {"A", "B", "C", "D"}:
        ap.error(f"unknown arm in {a.arms!r}")
    clients = {}
    for p in a.provider.split(","):
        try:
            clients[p] = cl.Client(p, a.model, a.rpm or cl.RPM.get(p, 8), a.max_requests, a.max_wait, None)
        except SystemExit as e:
            print(f"provider {p} left out: {e}", flush=True)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines() if x.strip()] if out.exists() else []
    done = {(r["profile"], r["task"], r["arm"], r["model"]) for r in rows}
    deadline = time.monotonic() + a.minutes * 60
    for profile_id, task_id in units:
        order = list(arms)
        random.Random(f"{a.seed}:{profile_id}:{task_id}").shuffle(order)
        for arm in order:
            if (profile_id, task_id, arm, a.model) in done:
                continue
            if time.monotonic() > deadline or not clients:
                print("stopping: time is up or every provider is spent", flush=True)
                return 0
            prov = next(iter(clients))
            t0 = time.monotonic()
            try:
                rec = run_arm(clients[prov], profile_id, all_tasks[task_id], arm, a.rounds)
            except cl.Stop as e:
                print(f"provider {prov} stopped: {e}", flush=True)
                del clients[prov]
                continue
            except Exception as e:  # noqa: BLE001 - a failed run is a row with its error
                rec = {"error": f"{type(e).__name__}: {str(e)[:300]}"}
            rec.update(profile=profile_id, task=task_id, arm=arm, model=a.model, provider=prov,
                       seconds=round(time.monotonic() - t0, 1))
            with out.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(arm, profile_id, task_id, rec.get("verdict", {}).get("status", rec.get("error")), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
