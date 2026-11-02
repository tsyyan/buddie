"""One tool-calling request to each named endpoint of endpoint_pool.REGISTRY; prints what came back.

For each endpoint: whether it answered, whether the model called the tool, the model and backend the response names
(a gateway pinned to one backend should name that one), tokens, seconds. As GitHub Actions notices with --notices.

    python probe_endpoints.py ovh groq vercel-baseten vercel-groq --model openai/gpt-oss-120b
"""
from __future__ import annotations

import argparse
import json
import time

from endpoint_pool import REGISTRY, EndpointClient, Pace, Spent, urllib_send

TOOL = {"type": "function", "function": {
    "name": "source_text", "description": "Text of the page a link points to, around the words you ask for.",
    "parameters": {"type": "object", "required": ["url", "query"], "properties": {
        "url": {"type": "string"}, "query": {"type": "string"}}}}}
ASK = [{"role": "user", "content": "Look up https://example.org for the words 'Example Domain' using the tool."}]


def probe(name: str, model: str) -> str:
    ep = REGISTRY[name]
    seen = {}

    def send(url, headers, body):
        status, rheaders, raw = urllib_send(url, headers, body, timeout=120)
        seen.update(status=status, headers=dict(rheaders or {}), raw=raw)
        return status, rheaders, raw

    try:
        client = EndpointClient(ep, model, Pace(ep, max_wait=60, breaker=2, cooldown=1), send=send)
    except Spent as e:
        return f"not configured: {e}"
    t0 = time.monotonic()
    try:
        msg, usage = client.chat(ASK, [TOOL])
    except Exception as e:  # noqa: BLE001 - a probe reports whatever happened
        return f"failed: {str(e)[:300]}"
    calls = msg.get("tool_calls") or []
    try:
        data = json.loads(seen.get("raw") or b"{}")
    except ValueError:
        data = {}
    named = {k: data[k] for k in ("model", "provider") if k in data}
    meta = {k: v for k, v in data.items() if k not in ("id", "object", "created", "choices", "usage", "model")}
    hdrs = {k: v for k, v in seen.get("headers", {}).items() if any(w in k.lower() for w in ("provider", "gateway"))}
    return (f"answered in {time.monotonic() - t0:.1f} s; tool call: "
            f"{calls[0]['function']['name'] + ' ' + calls[0]['function'].get('arguments', '')[:80] if calls else 'none'}"
            f"; names {json.dumps(named)}; other fields {json.dumps(meta)[:300]}; headers {json.dumps(hdrs)[:300]}"
            f"; tokens {usage.get('prompt_tokens')}/{usage.get('completion_tokens')}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("endpoints", nargs="+", help=f"from: {', '.join(REGISTRY)}")
    ap.add_argument("--model", default="openai/gpt-oss-120b")
    ap.add_argument("--notices", action="store_true", help="print as GitHub Actions notices")
    a = ap.parse_args(argv)
    for name in a.endpoints:
        result = probe(name, a.model)
        if a.notices:
            print(f"::notice title=probe {name}::{result.replace('%', '%25').replace(chr(10), ' ')}")
        else:
            print(f"{name}: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
