"""No network/model calls. Safe metric-only instrumentation for future reviewed adapters."""
import json
import math
import re
import time


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


class ToolMeter:
    def __init__(self, records, *, allowed_tools, clock=time.perf_counter):
        self.records, self.clock, self.allowed_tools = records, clock, allowed_tools

    def call(self, boundary, tool, callback, request):
        if boundary not in ('agent_tool', 'github_http', 'hook') or not re.fullmatch(r'[a-zA-Z0-9_]{1,64}', tool) \
                or tool not in self.allowed_tools.get(boundary, set()):
            raise ValueError('invalid metric identity')
        request_size = len(encode(request))
        started = self.clock()
        ok, response_size = False, None
        try:
            result = callback(request)
            response_size = len(encode(result))
            ok = True
            return result
        finally:
            self.records.append({'boundary': boundary, 'tool': tool, 'ok': ok,
                                 'duration_s': self.clock() - started, 'request_bytes': request_size,
                                 'response_bytes': response_size, 'bytes_scope': 'canonical_json_application'})


def usage(result):
    """Observed Claude CLI result counters. No defaults, rate tables or token estimates."""
    if not isinstance(result, dict) or result.get('type') != 'result' or not isinstance(result.get('usage'), dict):
        raise ValueError('runtime result with usage required')
    mapping = {'input_tokens': 'input_tokens', 'cache_read_tokens': 'cache_read_input_tokens',
               'cache_creation_tokens': 'cache_creation_input_tokens', 'output_tokens': 'output_tokens'}
    out = {}
    for target, source in mapping.items():
        value = result['usage'].get(source)
        if type(value) is not int or not 0 <= value <= 2**63-1:
            raise ValueError('missing or invalid runtime token counter')
        out[target] = value
    cost = result.get('total_cost_usd')
    if type(cost) not in (int, float) or not 0 <= cost <= 1e9 or not math.isfinite(cost):
        raise ValueError('missing or invalid runtime USD counter')
    return {**out, 'cost_usd': cost, 'source': 'claude_cli_result', 'billing_authenticated': False}


def isolation(envelope, tools, *, hooks):
    """Preflight assertions, NOT proof that a runtime supplied a complete envelope.

    A trusted adapter must inspect the real in-memory payload before setting the reviewed flags.
    No raw payload or secret is persisted here.
    """
    if not (envelope.get('bare') is True and envelope.get('host_context_injected') is False
            and envelope.get('plugins') == [] and envelope.get('hooks') is hooks
            and envelope.get('tools') == tools and envelope.get('context_reviewed') is True
            and envelope.get('secrets_absent') is True):
        raise ValueError('isolation_preflight_failed')
