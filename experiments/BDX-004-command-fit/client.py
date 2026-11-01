"""Chat client for BDX-004: copied from experiments/BDX-003-correction/arms.py (Client, Stop, PROVIDERS, MODEL_IDS,
RPM, to_anthropic, from_anthropic) at its commit on experiment/bdx-003-correction, so this experiment does not import
another one's files. Same behaviour: OpenAI-compatible chat completions; Anthropic's Messages API translated; a 429
quota or a 402 balance stops the provider instead of recording a failed run."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

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

class Stop(Exception):
    """A limit was reached (daily quota, request budget): stop the run, keep what is done."""




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
                if e.code == 402:  # the account's balance: the provider's, never the model's (a Stop, not a failed run)
                    raise Stop(f"balance spent (HTTP 402): {e.read()[:160]!r}") from e
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


