"""BDX-003 product run: the stream reduced to what the reader saw, and judged from it."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import product  # noqa: E402
import product_judge as pj  # noqa: E402

PAGE = "The committee said the plan is fully funded through 2027 and construction will start in the spring."
UNIT = {"quote": "fully funded through 2030"}


def ev(kind, *content, **extra):
    return json.dumps({"type": kind, "message": {"content": list(content)}, **extra})


class Stream(unittest.TestCase):
    def test_texts_tools_and_hook_returns(self):
        raw = "\n".join([
            ev("assistant", {"type": "text", "text": "The plan is “fully funded through 2030”."}),
            ev("user", {"type": "text", "text": "Stop hook feedback:\n[sh ...] buddie sent this text back"}),
            ev("assistant", {"type": "tool_use", "name": "mcp__plugin_buddie_buddie__snap"}),
            json.dumps({"type": "system", "subtype": "permission_denied"}),
            ev("assistant", {"type": "text", "text": "“fully funded through 2027”"}),
            json.dumps({"type": "result", "num_turns": 3, "subtype": "success",
                        "usage": {"input_tokens": 100, "cache_read_input_tokens": 50, "output_tokens": 9}}),
            "not json"])
        r = product.reduce_stream(raw)
        self.assertEqual(len(r["texts"]), 2)
        self.assertEqual(r["tools"], ["mcp__plugin_buddie_buddie__snap"])
        self.assertEqual((r["hook_returns"], r["denied"], r["turns"]), (1, 1, 3))
        self.assertEqual((r["input_tokens"], r["output_tokens"]), (150, 9))
        self.assertEqual((r["uncached_input"], r["cache_write"], r["cache_read"]), (100, 0, 50))


class Spending(unittest.TestCase):
    def test_failed_runs_count_and_unpriced_is_not_free(self):
        runs = [{"condition": "with", "texts": ["a"], "turns": 3, "input_tokens": 10, "cost_usd": 0.5,
                 "cache_read": 7},
                {"condition": "with", "error": "API Error: 500", "texts": [], "cost_usd": 0.25},
                {"condition": "without", "texts": ["a"], "turns": 1, "input_tokens": 10, "cost_usd": None}]
        s = pj.spending(runs)
        self.assertEqual((s["with"]["runs"], s["with"]["failed"], s["with"]["cost_usd"]), (2, 1, 0.75))
        self.assertEqual(s["with"]["usd_per_judged_run"], 0.75)  # the failed run's cost is paid by the good one
        self.assertEqual(s["with"]["cache_read"], 7)
        self.assertIsNone(s["without"]["usd_per_judged_run"])


class Judge(unittest.TestCase):
    def test_a_later_correct_statement_wins_but_the_wrong_one_was_shown(self):
        j = pj.paragraph(UNIT, ["It is “fully funded through 2030”.", "“fully funded through 2027”"], PAGE, 0.6)
        self.assertEqual(j, {"outcome": "CORRECT", "shown_wrong": True})

    def test_wrong_flagged_and_removed(self):
        self.assertEqual(pj.paragraph(UNIT, ["It is “fully funded through 2030”."], PAGE, 0.6)["outcome"], "WRONG")
        self.assertEqual(pj.paragraph(UNIT, ["It is “fully funded through 2030”.",
                                             "buddie: the quote could not be verified."], PAGE, 0.6)["outcome"],
                         "FLAGGED")
        self.assertEqual(pj.paragraph(UNIT, ["It is funded for years."], PAGE, 0.6)["outcome"], "REMOVED")

    def test_summary_counts_false_quotes_shown_and_left(self):
        s = pj.summary(["They say “the plan is fully funded through 2031” and “construction will start in the "
                        "spring”.", "Corrected: “the plan is fully funded through 2027”."], PAGE)
        self.assertEqual((s["false_shown"], s["false_final"]), (1, 0))
        s = pj.summary(["They say “the plan is fully funded through 2031”."], PAGE)
        self.assertEqual(s["false_final"], 1)


if __name__ == "__main__":
    unittest.main()
