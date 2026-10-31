"""What the repository's ANTHROPIC_API_KEY gives: models, rate limits (the account's tier), tool use, prompt caching,
the OpenAI-compatible endpoint (what arms.py speaks) and the Batch API. A handful of tiny requests (cents).

    ANTHROPIC_API_KEY=... python experiments/anthropic_probe.py [--model claude-opus-5-5] [--notices]

Never prints the key. With --notices every finding is also a GitHub Actions ::notice line.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

# Anthropic's API, or a compatible gateway in front of it: ANTHROPIC_BASE_URL as Claude Code reads it (without /v1)
API = os.environ.get("ANTHROPIC_BASE_URL", "").rstrip("/") or "https://api.anthropic.com"
API += "/v1"
NOTICES = False


def say(title: str, text: str) -> None:
    print(f"{title}: {text}")
    if NOTICES:
        print(f"::notice title={title}::{text.replace(chr(10), ' | ')[:900]}")


def call(method: str, path: str, body: dict | None = None, openai: bool = False):
    key = os.environ["ANTHROPIC_API_KEY"]
    headers = {"content-type": "application/json", "user-agent": "buddie-bdx003-probe"}
    if openai:
        headers["authorization"] = f"Bearer {key}"
    else:
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    req = urllib.request.Request(API + path, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, dict(r.headers), json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()[:400]
        try:
            return e.code, dict(e.headers), json.loads(raw)
        except ValueError:
            return e.code, dict(e.headers), {"raw": raw.decode("utf-8", "replace")}


def key_shape(key: str) -> str:
    """What kind of key the secret holds, without any of its secret part: the public prefix, length, stray characters."""
    kinds = (("sk-ant-api", "API key (Console)"), ("sk-ant-oat", "OAuth token (Claude subscription, not an API key)"),
             ("sk-ant-admin", "Admin key (cannot call models)"))
    core = key.strip().strip("'\"")
    kind = next((name for p, name in kinds if core.startswith(p)), "not an Anthropic key prefix")
    stray = [w for w, bad in (("surrounding whitespace or newline", key != key.strip()),
                              ("quotes", core != key.strip()), ("inner whitespace", any(c.isspace() for c in core)))
             if bad]
    return f"{kind}; {len(core)} characters" + (f"; has {', '.join(stray)}" if stray else "; no stray characters")


TOOL = {"name": "source_text", "description": "Return passages of the saved copy of a source page.",
        "input_schema": {"type": "object", "properties": {"url": {"type": "string"}, "query": {"type": "string"}},
                         "required": ["url", "query"]}}


def main() -> int:
    global NOTICES
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--notices", action="store_true")
    a = ap.parse_args()
    NOTICES = a.notices
    if not os.environ.get("ANTHROPIC_API_KEY"):
        say("anthropic key", "ANTHROPIC_API_KEY is not set (repository secret missing or named differently)")
        return 1

    st, _, body = call("GET", "/models?limit=100")
    if st != 200:
        say("anthropic models", f"HTTP {st}: {json.dumps(body)[:300]}")
        say("anthropic key shape", key_shape(os.environ["ANTHROPIC_API_KEY"]))
        return 1
    ids = [m["id"] for m in body.get("data", [])]
    say("anthropic endpoint", API.split("//")[1].split("/")[0])
    say("anthropic models", f"{len(ids)}: " + ", ".join(ids))
    if a.model not in ids:
        say("anthropic model", f"{a.model} is not in the list; the probe goes on with it anyway")

    # one tool-calling request: does the model call the tool, what usage and which limits come back
    msgs = [{"role": "user", "content": "Use the source_text tool once to look up 'funding' at https://example.org/report."}]
    st, h, body = call("POST", "/messages", {"model": a.model, "max_tokens": 300, "tools": [TOOL], "messages": msgs})
    if st != 200:
        say("anthropic tool use", f"HTTP {st}: {json.dumps(body)[:300]}")
        return 1
    used = [c["name"] for c in body.get("content", []) if c.get("type") == "tool_use"]
    say("anthropic served model", f"asked {a.model}, the answer names {body.get('model')!r}, id {body.get('id', '')[:8]}…")
    say("anthropic tool use", f"{a.model}: stop_reason {body.get('stop_reason')}, tools called {used}, "
        f"usage {json.dumps(body.get('usage'))}")
    limits = {k.split("anthropic-ratelimit-")[1]: v for k, v in h.items()
              if k.lower().startswith("anthropic-ratelimit-") and not k.lower().endswith("reset")}
    say("anthropic rate limits", json.dumps(dict(sorted((k.lower(), v) for k, v in limits.items()))))

    # prompt caching: the same long prefix twice; the second read should come from the cache
    prefix = "Reference text for caching. " + " ".join(f"Sentence {i} of the saved page." for i in range(900))
    req = {"model": a.model, "max_tokens": 20,
           "system": [{"type": "text", "text": prefix, "cache_control": {"type": "ephemeral"}}],
           "messages": [{"role": "user", "content": "Reply with OK."}]}
    usage = []
    for _ in range(2):
        st, _, body = call("POST", "/messages", req)
        usage.append(body.get("usage") if st == 200 else f"HTTP {st}")
    say("anthropic prompt caching", f"first {json.dumps(usage[0])}; second {json.dumps(usage[1])}")

    # the OpenAI-compatible endpoint: what arms.py speaks to every other provider
    st, _, body = call("POST", "/chat/completions", {
        "model": a.model, "max_tokens": 300,
        "tools": [{"type": "function", "function": {"name": TOOL["name"], "description": TOOL["description"],
                                                     "parameters": TOOL["input_schema"]}}],
        "messages": msgs}, openai=True)
    if st == 200:
        m = body["choices"][0]["message"]
        say("anthropic openai-compat", f"HTTP 200, finish {body['choices'][0].get('finish_reason')}, "
            f"tool_calls {[t['function']['name'] for t in m.get('tool_calls') or []]}, usage {json.dumps(body.get('usage'))}")
    else:
        say("anthropic openai-compat", f"HTTP {st}: {json.dumps(body)[:300]}")

    st, _, body = call("GET", "/messages/batches?limit=1")
    say("anthropic batch api", f"HTTP {st}" + ("" if st == 200 else f": {json.dumps(body)[:200]}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
