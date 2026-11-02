"""The spend ledger: usage split, written per request, a budget, dollars only with a price."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import spend  # noqa: E402


class Split(unittest.TestCase):
    def test_anthropic_counts_cache_apart(self):
        s = spend.split({"input_tokens": 10, "cache_creation_input_tokens": 500, "cache_read_input_tokens": 2000,
                         "output_tokens": 30})
        self.assertEqual((s["input"], s["cache_write"], s["cache_read"], s["output"], s["reported"]),
                         (10, 500, 2000, 30, True))

    def test_openai_cached_tokens_come_out_of_the_input(self):
        s = spend.split({"prompt_tokens": 1000, "completion_tokens": 50,
                         "prompt_tokens_details": {"cached_tokens": 800}})
        self.assertEqual((s["input"], s["cache_read"], s["output"]), (200, 800, 50))

    def test_empty_usage_is_unreported_not_free(self):
        self.assertFalse(spend.split({})["reported"])
        self.assertFalse(spend.split({"prompt_tokens": 0, "completion_tokens": 0})["reported"])


class Ledgers(unittest.TestCase):
    def test_each_request_is_written_at_once_and_counted_on_resume(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "out.jsonl.spend.jsonl"
            led = spend.Ledger(path)
            led.record(provider="p", model="m", usage={"prompt_tokens": 100, "completion_tokens": 10},
                       request_id="r1")
            led.record(provider="p", model="m", usage={})
            lines = [json.loads(x) for x in path.read_text().splitlines()]
            self.assertEqual([x["request_id"] for x in lines], ["r1", None])
            again = spend.Ledger(path, budget_tokens=110)
            self.assertEqual(again.totals()["requests"], 2)
            self.assertEqual(again.totals()["unreported"], 1)
            with self.assertRaises(spend.BudgetSpent):
                again.check()

    def test_dollars_need_a_price(self):
        led = spend.Ledger()
        e = led.record(provider="p", model="m", usage={"input_tokens": 1_000_000, "output_tokens": 1_000_000})
        self.assertIsNone(e["usd"])
        self.assertIsNone(led.totals()["usd"])
        priced = spend.Ledger(price=spend.price("3,3.75,0.3,15"))
        e = priced.record(provider="p", model="m", usage={"input_tokens": 1_000_000, "cache_read_input_tokens":
                                                           1_000_000, "output_tokens": 100_000})
        self.assertAlmostEqual(e["usd"], 3 + 0.3 + 1.5)

    def test_unreported_requests_make_the_dollars_a_lower_bound(self):
        led = spend.Ledger(price=spend.price("1,1,1,1"))
        led.record(provider="p", model="m", usage={})
        self.assertTrue(led.totals()["usd_is_lower_bound"])

    def test_a_bad_price_is_refused(self):
        with self.assertRaises(ValueError):
            spend.price("1,2")


if __name__ == "__main__":
    unittest.main()
