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
gemini (GEMINI_API_KEY), openrouter (OPENROUTER_API_KEY), ovh (no key: the anonymous tier), cloudflare
(CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID). See PROVIDERS.md.

--provider may list several (ovh,groq,cloudflare) serving the same --model. Every arm of a unit goes to one provider:
a unit already begun stays with its provider, a new unit takes the first provider not yet spent. When a provider's
limit is reached, the unit it was on waits for that provider (never split) and the run goes on with the others.
Rows record the provider; --model stays the model's common name (MODEL_IDS maps it to each provider's id).

Resumable: rows already in --out are skipped. A daily limit (a 429 asking to wait over --max-wait seconds) or the
request budget spends a provider; the run ends when every provider is spent. Run it again later.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request

from common import HERE, page_text, read_json, read_jsonl, append_jsonl

sys.path.append(str(HERE.parent))  # experiments/endpoint_pool.py, for --pool

PROVIDERS = {
    "github": ("https://models.github.ai/inference/chat/completions", "GITHUB_TOKEN"),
    "groq": ("https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "GEMINI_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_API_KEY"),
    "ovh": ("https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/chat/completions", None),
    "cloudflare": ("https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/v1/chat/completions",
                   "CLOUDFLARE_API_TOKEN"),
    # Anthropic's Messages API (not OpenAI-compatible: to_anthropic / from_anthropic translate); ANTHROPIC_BASE_URL
    # as Claude Code reads it, without /v1
    "anthropic": ("{ANTHROPIC_BASE_URL}/v1/messages", "ANTHROPIC_API_KEY"),
}
MODEL_IDS = {  # the model's common name -> its id at a provider, where it differs
    "openai/gpt-oss-120b": {"ovh": "gpt-oss-120b", "cloudflare": "@cf/openai/gpt-oss-120b"},
    "openai/gpt-oss-20b": {"ovh": "gpt-oss-20b", "cloudflare": "@cf/openai/gpt-oss-20b"},
}
RPM = {"ovh": 2, "groq": 20, "anthropic": 20}  # free-tier pace where known (PROVIDERS.md); others 8, --rpm overrides all
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

# The hook's FIX as arm C ran it on gpt-oss-120b (buddie 2.0.6); arm C keeps it so its rows stay comparable.
FIX_206 = ("Fix each item: copy a quote character for character from its page (buddie's source_text tool, after snap), "
           "or correct the anchor (ready anchors are listed above when buddie could compute them). If an item cannot "
           "be fixed, keep it and add a line starting with 'buddie:' that tells the reader what is unverified and why.")
NEAR = re.compile(r" \(closest [0-9.]+(?::|; the page reads:) “.*”\)$", re.S)


def _as_206(line: str, quotes: dict) -> str:
    """A blocking quote line as buddie 2.0.6 wrote it: the near match cut to the quote's length, no sentence."""
    m = re.match(r"quote (\S+) ", line)
    near = quotes.get(m.group(1), {}).get("closest") if m else None
    line = NEAR.sub("", line)
    return line + (f" (closest {near['ratio']:.2f}: “{near['text'][:120]}”)" if near else "")


def buddie_feedback(store, text: str, passage: bool = False) -> tuple[str | None, dict]:
    """The hook's words when a quote does not hold, else None; and the receipt summary for the record.
    passage=False (arm C, D): the 2.0.6 words; passage=True (arm E): the page's sentence around the near match."""
    from buddie.hook import FIX, RETURNED
    from buddie.verify import verify
    receipt = verify(text, store=store, fetch=False, github=None, repos=[], mandate=False, numbers="gap")
    pred = receipt["predicate"]
    record = {"outcome": pred["outcome"], "quotes": pred["summary"]["quotes"], "blocking": len(pred["blocking"])}
    quotes_blocking = [b for b in pred["blocking"] if b.startswith("quote ")]
    if not quotes_blocking:
        return None, record
    if not passage:
        by_id = {q.get("id"): q for q in pred.get("quotes", [])}
        quotes_blocking = [_as_206(b, by_id) for b in quotes_blocking]
    body = "\n".join(["- " + b for b in quotes_blocking])
    return (f"{RETURNED}\n{pred['line']}\n{body}\n{FIX if passage else FIX_206}\n"
            "Reply with the corrected paragraph only.", record)


# ---- the chat API --------------------------------------------------------------------------------------------

class Client:
    def __init__(self, provider: str, model: str, rpm: float, max_requests: int, max_wait: float,
                 temperature: float | None):
        url, env = PROVIDERS[provider]
        if "{CLOUDFLARE_ACCOUNT_ID}" in url:
            if not os.environ.get("CLOUDFLARE_ACCOUNT_ID"):
                raise SystemExit("CLOUDFLARE_ACCOUNT_ID is not set")
            url = url.replace("{CLOUDFLARE_ACCOUNT_ID}", os.environ["CLOUDFLARE_ACCOUNT_ID"])
        if "{ANTHROPIC_BASE_URL}" in url:
            url = url.replace("{ANTHROPIC_BASE_URL}",
                              os.environ.get("ANTHROPIC_BASE_URL", "").rstrip("/") or "https://api.anthropic.com")
        self.anthropic = provider == "anthropic"
        self.url, self.key = url, (os.environ.get(env) or "") if env else ""
        if env and not self.key:
            raise SystemExit(f"{env} is not set")
        model = MODEL_IDS.get(model, {}).get(provider, model)
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
        if self.anthropic:
            body = to_anthropic(body)
        for attempt in range(6):
            wait = self.last + self.gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last, self.left = time.monotonic(), self.left - 1
            headers = {"Content-Type": "application/json", "Accept": "application/json",
                       "User-Agent": "buddie-bdx003/1 (+https://github.com/tsyyan/buddie)"}
            if self.anthropic:
                headers.update({"x-api-key": self.key, "anthropic-version": "2023-06-01"})
            elif self.key:
                headers["Authorization"] = f"Bearer {self.key}"
            req = urllib.request.Request(self.url, data=json.dumps(body).encode(), method="POST", headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    raw, status, ctype = r.read(), r.status, r.headers.get("Content-Type")
                try:
                    data = json.loads(raw)
                    if self.anthropic:
                        return from_anthropic(data)
                    return data["choices"][0]["message"], data.get("usage") or {}
                except (ValueError, KeyError, IndexError, TypeError) as e:
                    raise RuntimeError(f"HTTP {status} {ctype}: not a chat completion: {raw[:200]!r}") from e
            except urllib.error.HTTPError as e:
                after = float(e.headers.get("Retry-After") or 0) or min(120.0, 5 * 2 ** attempt)
                if e.code == 429:
                    body = e.read()[:300]
                    # a quota or rate limit is the provider's, never the model's: it stops the provider (the unit
                    # waits for it), it is never recorded as a failed run
                    if after > self.max_wait or b"quota" in body.lower() or attempt >= 5:
                        raise Stop(f"rate limit (HTTP 429): {body[:160]!r}") from e
                    time.sleep(after)
                    continue
                if e.code in (500, 502, 503, 504, 529) and attempt < 5:
                    time.sleep(after)
                    continue
                raise RuntimeError(f"HTTP {e.code}: {e.read()[:300]!r}") from e
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < 5:
                    time.sleep(5 * 2 ** attempt)
                    continue
                raise RuntimeError(str(e)[:300]) from e
        raise RuntimeError("no answer after retries")


def to_anthropic(body: dict) -> dict:
    """An OpenAI chat-completions request as a Messages API request: system apart, tool calls as tool_use blocks, tool
    results as tool_result blocks in a user turn, consecutive turns of one role merged (the API wants them to alternate)."""
    system, turns = [], []
    for m in body["messages"]:
        role, text = m["role"], m.get("content") or ""
        if role == "system":
            system.append(text)
            continue
        if role == "tool":
            role, blocks = "user", [{"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": text}]
        else:
            blocks = [{"type": "text", "text": text}] if text else []
            for c in m.get("tool_calls") or []:
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                except ValueError:
                    args = {}
                blocks.append({"type": "tool_use", "id": c["id"], "name": c["function"]["name"], "input": args})
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] += blocks
        else:
            turns.append({"role": role, "content": blocks})
    out = {k: v for k, v in body.items() if k not in ("messages", "tools")}
    out["messages"] = turns
    if system:
        out["system"] = "\n\n".join(system)
    if body.get("tools"):
        out["tools"] = [{"name": t["function"]["name"], "description": t["function"].get("description", ""),
                         "input_schema": t["function"]["parameters"]} for t in body["tools"]]
    return out


def from_anthropic(data: dict) -> tuple[dict, dict]:
    """A Messages API answer as (OpenAI-style message, usage with prompt_tokens / completion_tokens)."""
    blocks = data["content"]
    msg = {"role": "assistant", "content": "".join(b.get("text", "") for b in blocks if b.get("type") == "text")}
    calls = [{"id": b["id"], "type": "function",
              "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {})}}
             for b in blocks if b.get("type") == "tool_use"]
    if calls:
        msg["tool_calls"] = calls
    u = data.get("usage") or {}
    prompt = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    return msg, {"prompt_tokens": prompt, "completion_tokens": int(u.get("output_tokens") or 0)}


def answer(client, store, messages: list[dict], tools: bool, rec: dict) -> str:
    """Run the model until it answers without a tool call; count requests, tool calls and tokens into rec."""
    for _ in range(MAX_TOOL_STEPS + 1):
        msg, usage = client.chat(messages, [TOOL] if tools else None)
        rec["requests"] += 1
        rec["sent_chars"] = rec.get("sent_chars", 0) + len(json.dumps(messages, ensure_ascii=False))
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
    rec["sent_chars"] = rec.get("sent_chars", 0) + len(json.dumps(messages, ensure_ascii=False))
    for k in ("prompt_tokens", "completion_tokens"):
        rec[k] += int(usage.get(k) or 0)
    if msg.get("tool_calls"):
        raise RuntimeError(f"still calling tools after {MAX_TOOL_STEPS} steps")
    return msg.get("content") or ""


def run_arm(client, store, unit: dict, arm: str, rounds: int) -> dict:
    # sent_chars: what every request carried, counted here; a provider's usage can come back empty (seen: 0 tokens)
    rec = {"requests": 0, "tool_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "sent_chars": 0,
           "feedback_rounds": 0,
           "buddie": []}
    ask = ASK_BC if arm in ("B", "C", "E") else ASK_A
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Paragraph:\n\n{unit['paragraph']}\n\n{ask}"}]
    text = answer(client, store, messages, arm != "A", rec)
    if arm in ("C", "D", "E"):
        for _ in range(rounds):
            fb, receipt = buddie_feedback(store, text, passage=arm == "E")
            rec["buddie"].append(receipt)
            if fb is None:
                break
            rec["feedback_rounds"] += 1
            messages += [{"role": "assistant", "content": text}, {"role": "user", "content": fb}]
            text = answer(client, store, messages, True, rec)
        else:
            rec["buddie"].append(buddie_feedback(store, text, passage=arm == "E")[1])
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
    ap.add_argument("--provider", required=True, help="one, or several in order of preference: ovh,groq,cloudflare")
    ap.add_argument("--model", required=True)
    ap.add_argument("--arms", default="A,B,C")
    ap.add_argument("--n", type=int, help="units (a seeded, stratified sample of the eligible ones)")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--rounds", type=int, default=2, help="buddie feedback rounds in arms C and D")
    ap.add_argument("--seed", type=int, default=20261030)
    ap.add_argument("--rpm", type=float, help="requests a minute for every provider (default: RPM, else 8)")
    ap.add_argument("--max-requests", type=int, default=400)
    ap.add_argument("--max-wait", type=float, default=300)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--no-temperature", action="store_true", help="for models that reject the parameter")
    ap.add_argument("--drop-rate-limited", action="store_true",
                    help="drop rows whose only result is a provider's HTTP 429 (recorded as failed runs before "
                         "2026-10-31), so those arms run again")
    ap.add_argument("--pool", action="store_true",
                    help="all --provider endpoints at once, each at its own adaptive pace (experiments/endpoint_pool.py)")
    ap.add_argument("--minutes", type=float, help="with --pool: start no new unit after this many minutes")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.drop_rate_limited:
        from pathlib import Path
        keep = [r for r in read_jsonl(a.out) if not str(r.get("error", "")).startswith("HTTP 429")]
        dropped = len(read_jsonl(a.out)) - len(keep)
        Path(a.out).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in keep), encoding="utf-8")
        print("dropped", dropped, "rate-limited rows", flush=True)
    units = read_json(a.units)["units"]
    eligible = {r["id"]: r for r in read_json(a.eligible)["rows"]}
    store = Store(a.store)
    providers = a.provider.split(",")
    if set(providers) - set(PROVIDERS):
        ap.error(f"unknown provider in --provider {a.provider!r}")
    if set(a.arms.split(",")) - {"A", "B", "C", "D", "E"}:
        ap.error(f"unknown arm in --arms {a.arms!r}")
    if a.pool:
        return run_pool(a, units, eligible, store)
    clients = {}
    for p in providers:
        try:
            clients[p] = Client(p, a.model, a.rpm or RPM.get(p, 8), a.max_requests, a.max_wait,
                                None if a.no_temperature else a.temperature)
        except SystemExit as e:
            print("provider", p, "left out:", e)
    if not clients:
        raise SystemExit("no provider is usable")
    rows = read_jsonl(a.out)
    done = {(r["unit"], r["arm"], r["model"], r["rep"]) for r in rows}
    pinned = {(r["unit"], r["model"], r["rep"]): r.get("provider") for r in rows}
    arms = a.arms.split(",")
    spent: set[str] = set()
    rng = random.Random(a.seed + 1)
    for unit in select(units, eligible, a.n, a.seed):
        for rep in range(a.reps):
            order = arms[:]
            rng.shuffle(order)
            todo = [arm for arm in order if (unit["id"], arm, a.model, rep) not in done]
            while todo:
                prov = pinned.get((unit["id"], a.model, rep)) or next((p for p in clients if p not in spent), None)
                if prov is None or prov in spent or prov not in clients:
                    print(unit["id"], "waits for", prov or "a provider", flush=True)
                    break
                try:
                    while todo:
                        arm = todo[0]
                        t0 = time.monotonic()
                        row = {"unit": unit["id"], "arm": arm, "model": a.model, "provider": prov, "rep": rep,
                               "seed": a.seed}
                        try:
                            row |= run_arm(clients[prov], store, unit, arm, a.rounds)
                        except Stop:
                            raise
                        except Exception as e:  # noqa: BLE001 - a failed run is a result: recorded, counted
                            row |= {"error": str(e)[:300]}
                        row["seconds"] = round(time.monotonic() - t0, 2)
                        append_jsonl(a.out, row)
                        pinned[(unit["id"], a.model, rep)] = prov
                        todo.pop(0)
                        print(unit["id"], arm, prov, "error" if "error" in row else "ok", row.get("requests"),
                              flush=True)
                except Stop as stop:
                    print("provider", prov, "stopped:", stop, flush=True)
                    spent.add(prov)
        if spent >= set(clients):
            print("every provider is spent")
            break
    return 0


def run_pool(a, units: list[dict], eligible: dict, store) -> int:
    """--pool: every listed endpoint works at once; a job is one unit and repetition with its remaining arms, and
    it stays with the endpoint it started at (endpoint_pool.Pool), so the never-split rule holds as before."""
    import dataclasses

    from endpoint_pool import REGISTRY, Pool, Spent
    endpoints = [dataclasses.replace(REGISTRY[p], rpm=a.rpm) if a.rpm else REGISTRY[p] for p in a.provider.split(",")]
    pool = Pool(endpoints, a.model, max_wait=a.max_wait, max_requests=a.max_requests,
                temperature=None if a.no_temperature else a.temperature)
    rows = read_jsonl(a.out)
    done = {(r["unit"], r["arm"], r["model"], r["rep"]) for r in rows}
    started = {f"{r['unit']}#{r['rep']}" for r in rows if r["model"] == a.model}
    pinned = {f"{r['unit']}#{r['rep']}": r["provider"] for r in rows if r["model"] == a.model and r.get("provider")}
    arms, rng, jobs = a.arms.split(","), random.Random(a.seed + 1), []
    for unit in select(units, eligible, a.n, a.seed):
        for rep in range(a.reps):
            order = arms[:]
            rng.shuffle(order)  # the same arm order as the sequential run
            todo = [arm for arm in order if (unit["id"], arm, a.model, rep) not in done]
            if todo:
                jobs.append({"key": f"{unit['id']}#{rep}", "unit": unit, "rep": rep, "todo": todo})

    def work(job: dict, client, name: str) -> None:
        while job["todo"]:
            arm, t0 = job["todo"][0], time.monotonic()
            row = {"unit": job["unit"]["id"], "arm": arm, "model": a.model, "provider": name, "rep": job["rep"],
                   "seed": a.seed}
            try:
                row |= run_arm(client, store, job["unit"], arm, a.rounds)
            except Spent:
                raise
            except Exception as e:  # noqa: BLE001 - a failed run is a result: recorded, counted
                row |= {"error": str(e)[:300]}
            row["seconds"] = round(time.monotonic() - t0, 2)
            with pool.lock:
                append_jsonl(a.out, row)
                started.add(job["key"])
            job["todo"].pop(0)
            print(row["unit"], arm, name, "error" if "error" in row else "ok", row.get("requests"), flush=True)

    deadline = time.monotonic() + 60 * a.minutes if a.minutes else None
    out = pool.run(jobs, work, started=lambda j: j["key"] in started, key=lambda j: j["key"], pinned=pinned,
                   deadline=deadline)
    print("pool:", json.dumps(out["endpoints"]), "| jobs left", len(out["left"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
