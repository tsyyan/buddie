"""Model-free tests of BDX-003: units, the independent matcher, eligibility, the tool, buddie's feedback loop in
arm C (with a scripted model) and the judge. Run from the experiment directory:

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import common  # noqa: E402
import judge  # noqa: E402
import refetch  # noqa: E402
import arms as run  # noqa: E402
import units as units_mod  # noqa: E402
from buddie.verbatim.store import Store  # noqa: E402

FILLER = " ".join(f"Background sentence number {i} about the regional transport survey." for i in range(30))
PAGE = (f"<html><body><article><p>{FILLER}</p><p>The committee said the plan is fully funded through 2027 and "
        f"construction will start in the spring.</p><p>{FILLER}</p></article></body></html>").encode()
URL = "https://example.org/report"
UNIT_ERR = {"id": "T:1", "gold": "ERROR", "label": "AGENT_ALTERED", "quote": "fully funded through 2030",
            "evidence": "fully funded through 2027", "url": URL,
            "paragraph": f"The committee said the plan is “fully funded through 2030” ([1]({URL}))."}
UNIT_OK = {"id": "T:2", "gold": "OK", "label": "IN_SOURCE", "quote": "fully funded through 2027", "evidence": None,
           "url": URL, "paragraph": f"The committee said the plan is “fully funded through 2027” ([1]({URL}))."}


def store_with_page(tmp: str) -> Store:
    s = Store(Path(tmp) / "store")
    s.add(URL, PAGE, content_type="text/html")
    return s


class Scripted:
    """A stand-in for run.Client: answers from a list, records what it was sent."""

    def __init__(self, replies):
        self.replies, self.sent = list(replies), []

    def chat(self, messages, tools):
        self.sent.append([dict(m) for m in messages])
        return self.replies.pop(0), {"prompt_tokens": 10, "completion_tokens": 5}


class Units(unittest.TestCase):
    def test_units_come_from_the_blind_labels_only(self):
        us = units_mod.build()
        self.assertEqual(len(us), 251)
        self.assertEqual({u["gold"] for u in us}, {"ERROR", "OK"})
        self.assertTrue(all(u["label"] in common.ERROR_LABELS | common.OK_LABELS for u in us))
        self.assertFalse(any(u["set"] == "E010" for u in us))


class Matcher(unittest.TestCase):
    def test_normalization_and_ellipsis(self):
        page = "He said: “It’s ready — finally.” Later, much later, he added that work continues."
        self.assertTrue(common.in_text("it's ready - finally", page))
        self.assertTrue(common.in_text("It’s ready … work continues", page))
        self.assertFalse(common.in_text("work continues … It’s ready", page))  # order matters
        self.assertFalse(common.in_text("It is ready", page))
        self.assertTrue(common.in_text("important – this", "was really important—this is"))

    def test_bracketed_insertion_is_a_gap(self):
        self.assertTrue(common.in_text("[A]t a nonhub airport", "at a nonhub airport, it takes fewer"))

    def test_best_span(self):
        span, sim = common.best_span("fully funded through 2030", "They said “fully funded through 2027” and “soon”.")
        self.assertEqual(span, "fully funded through 2027")
        self.assertGreater(sim, 0.8)


class Eligibility(unittest.TestCase):
    def test_rules(self):
        text = "x" * 600 + " the plan is fully funded through 2027 and more."
        self.assertEqual(refetch.consistent(UNIT_ERR, text), (True, "ok"))
        self.assertEqual(refetch.consistent(UNIT_OK, text), (True, "ok"))
        self.assertEqual(refetch.consistent(UNIT_ERR, text.replace("2027", "2030"))[1], "error_quote_now_matched")
        self.assertEqual(refetch.consistent(UNIT_ERR, text.replace("2027", "2028"))[1], "evidence_not_matched")
        self.assertEqual(refetch.consistent(UNIT_OK, "short")[1], "unreadable")


class Tool(unittest.TestCase):
    def test_source_text_finds_the_passage(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = store_with_page(tmp)
            out = run.source_text(s, URL, "fully funded through 2030")
            self.assertIn("fully funded through 2027", out)
            self.assertIn("No copy", run.source_text(s, "https://example.org/other", "x"))


class ArmC(unittest.TestCase):
    def test_buddie_returns_a_false_quote_and_passes_a_true_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = store_with_page(tmp)
            fb, rec = run.buddie_feedback(s, UNIT_ERR["paragraph"])
            self.assertIsNotNone(fb)
            self.assertIn("sent this text back", fb)
            self.assertEqual(rec["outcome"], "FAIL")
            fb, rec = run.buddie_feedback(s, UNIT_OK["paragraph"])
            self.assertIsNone(fb)

    def test_loop_feeds_back_until_the_quote_holds(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = store_with_page(tmp)
            client = Scripted([
                {"content": UNIT_ERR["paragraph"]},          # B-style answer, still wrong
                {"content": UNIT_OK["paragraph"]},           # after buddie's feedback: fixed
            ])
            rec = run.run_arm(client, s, UNIT_ERR, "C", rounds=2)
            self.assertEqual(rec["feedback_rounds"], 1)
            self.assertEqual(rec["final"], UNIT_OK["paragraph"])
            self.assertIn("sent this text back", client.sent[1][-1]["content"])
            self.assertEqual(rec["requests"], 2)

    def test_arm_b_gets_the_tool_and_no_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = store_with_page(tmp)
            call = {"id": "c1", "type": "function",
                    "function": {"name": "source_text", "arguments": f'{{"url": "{URL}", "query": "fully funded"}}'}}
            client = Scripted([{"content": "", "tool_calls": [call]}, {"content": UNIT_ERR["paragraph"]}])
            rec = run.run_arm(client, s, UNIT_ERR, "B", rounds=2)
            self.assertEqual((rec["tool_calls"], rec["feedback_rounds"], rec["buddie"]), (1, 0, []))
            self.assertIn("2027", client.sent[1][-1]["content"])  # the tool result


class Judge(unittest.TestCase):
    def test_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = common.page_text(store_with_page(tmp), URL)[1]
        self.assertEqual(judge.judge(UNIT_ERR, UNIT_ERR["paragraph"], text, 0.6)["outcome"], "WRONG")
        self.assertEqual(judge.judge(UNIT_ERR, UNIT_OK["paragraph"], text, 0.6)["outcome"], "CORRECT")
        para = f"The committee said the plan is funded for years ([1]({URL}))."
        self.assertEqual(judge.judge(UNIT_ERR, para, text, 0.6)["outcome"], "REMOVED")
        j = judge.judge(UNIT_ERR, UNIT_ERR["paragraph"] + "\nbuddie: the 2030 quote is unverified.", text, 0.6)
        self.assertEqual((j["outcome"], j["flagged"]), ("WRONG", True))

    def test_summary_pairs_units_across_arms(self):
        rows = []
        for u, (b, c) in enumerate([("WRONG", "CORRECT")] * 4 + [("WRONG", "WRONG")] * 2):
            for arm, o in (("B", b), ("C", c)):
                rows.append({"unit": f"U{u}", "arm": arm, "model": "m", "rep": 0, "gold": "ERROR", "outcome": o,
                             "flagged": False, "requests": 1})
        s = judge.summarize(rows)
        p = s["paired"]["m | ERROR | C-B"]
        self.assertEqual((p["n"], p["diff"], p["only_a_bad"], p["only_b_bad"]), (6, -0.667, 4, 0))
        self.assertEqual(s["cells"]["m | B | ERROR"]["wrong"], 1.0)


if __name__ == "__main__":
    unittest.main()
