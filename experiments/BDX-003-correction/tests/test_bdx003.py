"""Model-free tests of BDX-003: units, the independent matcher, eligibility, the tool, buddie's feedback loop in
arm C (with a scripted model) and the judge. Run from the experiment directory:

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
import unittest.mock
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
        self.replies, self.sent, self.tools = list(replies), [], []

    def chat(self, messages, tools):
        self.sent.append([dict(m) for m in messages])
        self.tools.append(tools)
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

    def test_a_long_quote_is_seen(self):
        long = " ".join(f"sentence {i} of a long passage." for i in range(40))  # over 1,000 characters
        self.assertGreater(len(long), 1000)
        self.assertEqual(common.quoted_spans(f'They wrote "{long}" ([1]({URL})).'), [long])
        self.assertEqual(common.best_span(long, f"They wrote “{long}”.")[1], 1.0)
        self.assertLessEqual(max(len(u["quote"]) for u in units_mod.build()), 2000)

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

    def test_a_paragraph_without_its_link_is_excluded(self):
        self.assertTrue(refetch.linked(UNIT_ERR))
        self.assertTrue(refetch.linked(UNIT_ERR | {"url": URL + "#:~:text=fully%20funded"}))
        self.assertFalse(refetch.linked(UNIT_ERR | {"paragraph": "The plan is “fully funded through 2030”.[^3]"}))


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


class ArmD(unittest.TestCase):
    def test_a_instruction_with_the_tool_and_buddies_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = store_with_page(tmp)
            client = Scripted([{"content": UNIT_ERR["paragraph"]}, {"content": UNIT_OK["paragraph"]}])
            rec = run.run_arm(client, s, UNIT_ERR, "D", rounds=2)
            self.assertIn(run.ASK_A, client.sent[0][-1]["content"])
            self.assertNotIn("source_text tool", client.sent[0][-1]["content"])
            self.assertEqual(client.tools[0], [run.TOOL])
            self.assertEqual((rec["feedback_rounds"], rec["final"]), (1, UNIT_OK["paragraph"]))
            self.assertIn("sent this text back", client.sent[1][-1]["content"])

    def test_arm_a_still_has_no_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = Scripted([{"content": UNIT_ERR["paragraph"]}])
            rec = run.run_arm(client, store_with_page(tmp), UNIT_ERR, "A", rounds=2)
            self.assertEqual((client.tools, rec["buddie"]), ([None], []))


class Providers(unittest.TestCase):
    def test_model_ids_and_keys(self):
        c = run.Client("ovh", "openai/gpt-oss-120b", 2, 10, 30, None)
        self.assertEqual((c.model, c.key), ("gpt-oss-120b", ""))
        with unittest.mock.patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "t", "CLOUDFLARE_ACCOUNT_ID": "acc"}):
            c = run.Client("cloudflare", "openai/gpt-oss-120b", 2, 10, 30, None)
            self.assertEqual(c.model, "@cf/openai/gpt-oss-120b")
            self.assertIn("/accounts/acc/ai/v1/chat/completions", c.url)
        with unittest.mock.patch.dict(os.environ, {"CLOUDFLARE_ACCOUNT_ID": ""}):
            with self.assertRaises(SystemExit):
                run.Client("cloudflare", "openai/gpt-oss-120b", 2, 10, 30, None)

    def _run(self, tmp, stop_after):
        """arms.main with fake providers: ovh stops after stop_after requests, groq never does."""
        calls = {"ovh": 0, "groq": 0}

        class Fake:
            def __init__(self, provider, *args):
                self.provider = provider

            def chat(self, messages, tools):
                calls[self.provider] += 1
                if self.provider == "ovh" and calls["ovh"] > stop_after:
                    raise run.Stop("daily limit")
                return {"content": UNIT_OK["paragraph"]}, {}

        d = Path(tmp)
        us = [UNIT_ERR | {"id": f"T:{i}"} for i in range(3)]
        common.write_json(d / "units.json", {"units": us})
        common.write_json(d / "eligible.json", {"rows": [{"id": u["id"], "eligible": True} for u in us]})
        if not (d / "store").exists():
            store_with_page(tmp)
        with unittest.mock.patch.object(run, "Client", Fake):
            run.main(["--units", str(d / "units.json"), "--eligible", str(d / "eligible.json"),
                      "--store", str(d / "store"), "--provider", "ovh,groq", "--model", "m", "--arms", "A,B",
                      "--out", str(d / "runs.jsonl")])
        rows = common.read_jsonl(d / "runs.jsonl")
        by_unit = {}
        for r in rows:
            by_unit.setdefault(r["unit"], set()).add(r["provider"])
        return rows, by_unit

    def test_a_unit_never_changes_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows, by_unit = self._run(tmp, stop_after=3)  # ovh: one unit (2 requests) and half of the next
            self.assertTrue(all(len(p) == 1 for p in by_unit.values()), by_unit)
            started_at_ovh = [u for u, p in by_unit.items() if p == {"ovh"}]
            self.assertEqual(len(started_at_ovh), 2)
            per_unit = {u: sum(r["unit"] == u for r in rows) for u in by_unit}
            waiting = [u for u in started_at_ovh if per_unit[u] == 1]
            self.assertEqual(len(waiting), 1)  # the split unit waits for ovh
            self.assertEqual(len(rows), 5)
            rows, by_unit = self._run(tmp, stop_after=99)  # the next day: ovh again
            self.assertEqual(by_unit[waiting[0]], {"ovh"})
            self.assertEqual(len(rows), 6)

    def test_a_provider_spent_before_a_unit_begins_passes_it_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows, by_unit = self._run(tmp, stop_after=2)
            self.assertEqual(len(rows), 6)
            self.assertEqual(sorted(len(p) for p in by_unit.values()), [1, 1, 1])
            self.assertEqual(sorted(next(iter(p)) for p in by_unit.values()), ["groq", "groq", "ovh"])


class PoolMode(unittest.TestCase):
    def test_arms_with_the_endpoint_pool(self):
        import functools
        import json as json_mod

        import endpoint_pool

        def send(url, headers, body):
            reply = {"choices": [{"message": {"role": "assistant", "content": UNIT_OK["paragraph"]}}],
                     "usage": {"prompt_tokens": 20, "completion_tokens": 5}}
            return 200, {}, json_mod.dumps(reply).encode()

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            store_with_page(tmp)
            us = [UNIT_ERR | {"id": f"T:{i}"} for i in range(4)]
            common.write_json(d / "units.json", {"units": us})
            common.write_json(d / "eligible.json", {"rows": [{"id": u["id"], "eligible": True} for u in us]})
            argv = ["--units", str(d / "units.json"), "--eligible", str(d / "eligible.json"), "--store", str(d / "store"),
                    "--provider", "ovh,groq", "--model", "openai/gpt-oss-120b", "--arms", "A,B", "--rpm", "6000",
                    "--pool", "--out", str(d / "runs.jsonl")]
            pool = functools.partial(endpoint_pool.Pool, send=send, environ={"GROQ_API_KEY": "k"})
            with unittest.mock.patch.object(endpoint_pool, "Pool", pool):
                run.main(argv)
                rows = common.read_jsonl(d / "runs.jsonl")
                self.assertEqual(len(rows), 8)
                self.assertEqual({r["model"] for r in rows}, {"openai/gpt-oss-120b"})
                by_unit = {}
                for r in rows:
                    by_unit.setdefault(r["unit"], set()).add(r["provider"])
                self.assertTrue(all(len(p) == 1 and p <= {"ovh", "groq"} for p in by_unit.values()), by_unit)
                run.main(argv)  # resumed: nothing left to do
                self.assertEqual(len(common.read_jsonl(d / "runs.jsonl")), 8)


class Judge(unittest.TestCase):
    def test_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = common.page_text(store_with_page(tmp), URL)[1]
        self.assertEqual(judge.judge(UNIT_ERR, UNIT_ERR["paragraph"], text, 0.6)["outcome"], "WRONG")
        self.assertEqual(judge.judge(UNIT_ERR, UNIT_OK["paragraph"], text, 0.6)["outcome"], "CORRECT")
        para = f"The committee said the plan is funded for years ([1]({URL}))."
        self.assertEqual(judge.judge(UNIT_ERR, para, text, 0.6)["outcome"], "REMOVED")
        self.assertIsNone(judge.judge(UNIT_ERR, UNIT_ERR["paragraph"], text, 0.6)["removed_as"])
        j = judge.judge(UNIT_ERR, UNIT_ERR["paragraph"] + "\nbuddie: the 2030 quote is unverified.", text, 0.6)
        self.assertEqual((j["outcome"], j["flagged"]), ("WRONG", True))

    def test_removed_is_split(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = common.page_text(store_with_page(tmp), URL)[1]
        cases = {
            "PARAPHRASED": f"The committee said the plan is funded for years ([1]({URL})).",
            "UNQUOTED_KEPT": f"The committee said the plan is fully funded through 2030 ([1]({URL})).",
            "REPLACED_CORRECT": f"The committee said “construction will start in the spring” ([1]({URL})).",
            "NO_PARAGRAPH": "I cannot check this quotation without its source. Could you share the link?",
        }
        for expected, final in cases.items():
            j = judge.judge(UNIT_ERR, final, text, 0.6)
            self.assertEqual((j["outcome"], j["removed_as"]), ("REMOVED", expected), expected)
        # a new quote that is not in the source is not a replacement
        wrong = f"The committee said “construction will start in the autumn” ([1]({URL}))."
        self.assertEqual(judge.judge(UNIT_ERR, wrong, text, 0.6)["removed_as"], "PARAPHRASED")

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
        rows += [r | {"arm": "D", "outcome": "REMOVED", "removed_as": "PARAPHRASED"} for r in rows if r["arm"] == "B"]
        s = judge.summarize(rows)
        self.assertEqual(s["paired"]["m | ERROR | D-B"]["diff"], -1.0)
        self.assertEqual(s["cells"]["m | D | ERROR"]["paraphrased"], 1.0)
        self.assertIn("paraphrased", judge.markdown(s))
        self.assertEqual(s["providers"]["m | ? | D | ERROR"]["removed"], 1.0)
        s = judge.summarize([r | {"provider": "ovh"} for r in rows])
        self.assertEqual(s["providers"]["m | ovh | B | ERROR"]["wrong"], 1.0)
        self.assertIn("| m | ovh | B | ERROR |", judge.markdown(s))


if __name__ == "__main__":
    unittest.main()
