"""Run the arms on eligible units with an OpenAI-compatible chat API (free tiers).

Arms, same model, same paragraph, same system prompt:
  A  pass-through: "return the paragraph ready to send" (no tools);
  B  self-check: "check every quotation against its source with the source_text tool, fix or paraphrase";
  C  self-check + buddie: B, and after each answer buddie checks the paragraph against the same snapshot and, when a
     quote does not hold, returns the hook's own words (buddie/hook.py RETURNED, FIX) with the failing items, up to
     --rounds times. This is what the Claude Code Stop hook does, outside Claude Code.
  D  A's instruction (no request to check) with the source_text tool available, and buddie's feedback as in C: the
     hook catching an agent nobody asked to check its quotations (added after pilot 1, PROTOCOL.md).

B, C and D get the identical source_text tool over the identical curated store; C's only extra over B is buddie's
feedback, D's only difference from C is the instruction (A's).

    python arms.py --units data/units.json --eligible data/eligible.json --store data/store \
        --provider github --model openai/gpt-4.1-mini --n 20 --out data/runs.jsonl

Providers (key from the environment): github (GITHUB_TOKEN, models: read), groq (GROQ_API_KEY),
gemini (GEMINI_API_KEY), openrouter (OPENROUTER_API_KEY). Resumable: rows already in --out are skipped.
A daily limit (a 429 asking to wait over --max-wait seconds) stops the run cleanly; run it again later.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import time
import urllib.error
import urllib.request

from common import page_text, read_json, read_jsonl, append_jsonl

PROVIDERS = {
    "github": ("https://models.github.ai/inference/chat/completions", "GITHUB_TOKEN"),
    "groq": ("https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "GEMINI_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_API_KEY"),
}
SYSTEM = ("You prepare a paragraph from a research report before it is sent to a reader. In this report, text in "
          "quotation marks presents the exact words of the source it links to.")
ASK_A = "Return the paragraph ready to send to the reader. Keep its links. Reply with the paragraph only."
ASK_BC = ("Before returning it, check every quotation against the source it links to, using the source_text tool. "
          "A quotation must be the source's exact words: correct it from the source, or, if the source does not "
          "contain it, rewrite that part as a paraphrase without quotation marks. Keep its links. "
          "Reply with the paragraph only.")
TOOL = {"type": "function", "function": {
    "name": "source_text",
    "description": "Text of the page a link points to, around the words you ask for (up to 3 passages).",
    "parameters": {"type": "object", "additionalProperties": False, "required": ["url", "query"], "properties": {
        "url": {"type": "string", "description": "the link as it appears in the paragraph"},
        "query": {"type": "string", "description": "words to look for, e.g. the quotation"}}}}}
MAX_TOOL_STEPS = 8
WORD = re.compile(r"\w+", re.U)


class Stop(Exception):
    """A limit was reached (daily quota, request budget): stop the run, keep what is done."""


# ---- the source_text tool (identical for B and C) ------------------------------------------------------------

def passages(text: str, query: str, k: int = 3, size: int = 450) -> list[str]:
    """Up to k windows of the page most like the query: exact (case-insensitive) hits first, then word overlap."""
    low, q = text.lower(), " ".join(query.lower().split())
    hits = []
    if len(q) >= 4:
        i = low.find(q)
        while i >= 0 and len(hits) < k:
            hits.append(max(0, i - size // 3))
            i = low.find(q, i + 1)
    if len(hits) < k:
        want = set(WORD.findall(q))
        step = size // 2
        scored = []
        for start in range(0, max(1, len(text) - step), step):
            got = set(WORD.findall(low[start:start + size]))
            if want:
                scored.append((len(want & got) / len(want), -start, start))
        for _, _, start in sorted(scored, reverse=True):
            if all(abs(start - h) >= step for h in hits):
                hits.append(start)
            if len(hits) >= k:
                break
    return [text[s:s + size].strip() for s in sorted(hits)[:k]]


def source_text(store, url: str, query: str) -> str:
    entry, text = page_text(store, (url or "").strip().strip("<>"))
    if entry is None:
        return "No copy of this page is available."
    if not text:
        return "This page has no readable text."
    found = passages(text, query or "")
    return "\n---\n".join(found) if found else "Nothing like that on the page."


# ---- buddie's feedback (arm C) -------------------------------------------------------------------------------

def buddie_feedback(store, text: str) -> tuple[str | None, dict]:
    """The hook's words when a quote does not hold, else None; and the receipt summary for the record."""
    from buddie.hook import FIX, RETURNED
    from buddie.verify import verify
    receipt = verify(text, store=store, fetch=False, github=None, repos=[], mandate=False, numbers="gap")
    pred = receipt["predicate"]
    record = {"outcome": pred["outcome"], "quotes": pred["summary"]["quotes"], "blocking": len(pred["blocking"])}
    quotes_blocking = [b for b in pred["blocking"] if b.startswith("quote ")]
    if not quotes_blocking:
        return None, record
    body = "\n".join(["- " + b for b in quotes_blocking])
    return (f"{RETURNED}\n{pred['line']}\n{body}\n{FIX}\nReply with the corrected paragraph only.", record)


# ---- the chat API --------------------------------------------------------------------------------------------

class Client:
    def __init__(self, provider: str, model: str, rpm: float, max_requests: int, max_wait: float,
                 temperature: float | None):
        self.url, env = PROVIDERS[provider]
        self.key = os.environ.get(env) or ""
        if not self.key:
            raise SystemExit(f"{env} is not set")
        self.model, self.gap, self.left, self.max_wait = model, 60.0 / rpm, max_requests, max_wait
        self.temperature, self.last = temperature, 0.0

    def chat(self, messages: list[dict], tools: list | None) -> tuple[dict, dict]:
        if self.left <= 0:
            raise Stop("request budget spent")
        body = {"model": self.model, "messages": messages, "max_tokens": 4000}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if tools:
            body["tools"] = tools
        for attempt in range(6):
            wait = self.last + self.gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last, self.left = time.monotonic(), self.left - 1
            req = urllib.request.Request(self.url, data=json.dumps(body).encode(), method="POST", headers={
                "Content-Type": "application/json", "Accept": "application/json",
                "User-Agent": "buddie-bdx003/1 (+https://github.com/tsyyan/buddie)",
                "Authorization": f"Bearer {self.key}"})
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    raw, status, ctype = r.read(), r.status, r.headers.get("Content-Type")
                try:
                    data = json.loads(raw)
                    return data["choices"][0]["message"], data.get("usage") or {}
                except (ValueError, KeyError, IndexError, TypeError) as e:
                    raise RuntimeError(f"HTTP {status} {ctype}: not a chat completion: {raw[:200]!r}") from e
            except urllib.error.HTTPError as e:
                after = float(e.headers.get("Retry-After") or 0) or min(120.0, 5 * 2 ** attempt)
                if e.code == 429 and after > self.max_wait:
                    raise Stop(f"rate limit: retry after {after:.0f} s") from e
                if e.code in (429, 500, 502, 503, 504) and attempt < 5:
                    time.sleep(after)
                    continue
                raise RuntimeError(f"HTTP {e.code}: {e.read()[:300]!r}") from e
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < 5:
                    time.sleep(5 * 2 ** attempt)
                    continue
                raise RuntimeError(str(e)[:300]) from e
        raise RuntimeError("no answer after retries")


def answer(client, store, messages: list[dict], tools: bool, rec: dict) -> str:
    """Run the model until it answers without a tool call; count requests, tool calls and tokens into rec."""
    for _ in range(MAX_TOOL_STEPS + 1):
        msg, usage = client.chat(messages, [TOOL] if tools else None)
        rec["requests"] += 1
        for k in ("prompt_tokens", "completion_tokens"):
            rec[k] += int(usage.get(k) or 0)
        calls = msg.get("tool_calls") or []
        if not calls:
            return msg.get("content") or ""
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for c in calls:
            rec["tool_calls"] += 1
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
                out = source_text(store, args.get("url", ""), args.get("query", ""))
            except (ValueError, KeyError, TypeError) as e:
                out = f"tool error: {e}"
            messages.append({"role": "tool", "tool_call_id": c.get("id"), "content": out})
    # the tools stay declared (some providers reject a tool call when none are), but another call ends the run
    messages.append({"role": "user", "content": "No more tool calls. Reply now with the paragraph only."})
    msg, usage = client.chat(messages, [TOOL] if tools else None)
    rec["requests"] += 1
    for k in ("prompt_tokens", "completion_tokens"):
        rec[k] += int(usage.get(k) or 0)
    if msg.get("tool_calls"):
        raise RuntimeError(f"still calling tools after {MAX_TOOL_STEPS} steps")
    return msg.get("content") or ""


def run_arm(client, store, unit: dict, arm: str, rounds: int) -> dict:
    rec = {"requests": 0, "tool_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "feedback_rounds": 0,
           "buddie": []}
    ask = ASK_BC if arm in ("B", "C") else ASK_A
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Paragraph:\n\n{unit['paragraph']}\n\n{ask}"}]
    text = answer(client, store, messages, arm != "A", rec)
    if arm in ("C", "D"):
        for _ in range(rounds):
            fb, receipt = buddie_feedback(store, text)
            rec["buddie"].append(receipt)
            if fb is None:
                break
            rec["feedback_rounds"] += 1
            messages += [{"role": "assistant", "content": text}, {"role": "user", "content": fb}]
            text = answer(client, store, messages, True, rec)
        else:
            rec["buddie"].append(buddie_feedback(store, text)[1])
    rec["final"] = text
    return rec


def select(units: list[dict], eligible: dict, n: int | None, seed: int) -> list[dict]:
    ok = [u for u in units if eligible.get(u["id"], {}).get("eligible")]
    rng = random.Random(seed)
    rng.shuffle(ok)
    if n:  # stratified: errors and correct quotes in the eligible proportion, at least a quarter of the smaller
        err = [u for u in ok if u["gold"] == "ERROR"]
        good = [u for u in ok if u["gold"] == "OK"]
        n_good = min(len(good), max(n // 4, round(n * len(good) / max(1, len(ok)))))
        ok = err[:n - n_good] + good[:n_good]
        rng.shuffle(ok)
    return ok


def main(argv=None) -> int:
    from buddie.verbatim.store import Store
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--units", required=True)
    ap.add_argument("--eligible", required=True)
    ap.add_argument("--store", required=True)
    ap.add_argument("--provider", choices=sorted(PROVIDERS), required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--arms", default="A,B,C")
    ap.add_argument("--n", type=int, help="units (a seeded, stratified sample of the eligible ones)")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--rounds", type=int, default=2, help="buddie feedback rounds in arms C and D")
    ap.add_argument("--seed", type=int, default=20261030)
    ap.add_argument("--rpm", type=float, default=8)
    ap.add_argument("--max-requests", type=int, default=400)
    ap.add_argument("--max-wait", type=float, default=300)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--no-temperature", action="store_true", help="for models that reject the parameter")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    units = read_json(a.units)["units"]
    eligible = {r["id"]: r for r in read_json(a.eligible)["rows"]}
    store = Store(a.store)
    client = Client(a.provider, a.model, a.rpm, a.max_requests, a.max_wait,
                    None if a.no_temperature else a.temperature)
    done = {(r["unit"], r["arm"], r["model"], r["rep"]) for r in read_jsonl(a.out)}
    arms = a.arms.split(",")
    if set(arms) - {"A", "B", "C", "D"}:
        ap.error(f"unknown arm in --arms {a.arms!r}")
    rng = random.Random(a.seed + 1)
    try:
        for unit in select(units, eligible, a.n, a.seed):
            for rep in range(a.reps):
                order = arms[:]
                rng.shuffle(order)
                for arm in order:
                    if (unit["id"], arm, a.model, rep) in done:
                        continue
                    t0 = time.monotonic()
                    row = {"unit": unit["id"], "arm": arm, "model": a.model, "provider": a.provider, "rep": rep,
                           "seed": a.seed}
                    try:
                        row |= run_arm(client, store, unit, arm, a.rounds)
                    except Stop:
                        raise
                    except Exception as e:  # noqa: BLE001 - a failed run is a result: recorded, counted
                        row |= {"error": str(e)[:300]}
                    row["seconds"] = round(time.monotonic() - t0, 2)
                    append_jsonl(a.out, row)
                    print(unit["id"], arm, "error" if "error" in row else "ok", row.get("requests"), flush=True)
    except Stop as stop:
        print("stopped:", stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
