"""run.py with a scripted model: the four arms, the tool answered from the profile, the gate's feedback (no network)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import run  # noqa: E402

BAD = "Run:\n```bash\nnvidia-smi\n```"
GOOD = "Run:\n```bash\nsystem_profiler SPDisplaysDataType\n```"


class Scripted:
    def __init__(self, replies):
        self.replies, self.sent = list(replies), []

    def chat(self, messages, tools):
        self.sent.append(([dict(m) for m in messages], tools))
        reply = self.replies.pop(0)
        return (reply if isinstance(reply, dict) else {"content": reply}), {"prompt_tokens": 10, "completion_tokens": 2}


def call(categories):
    return {"content": "", "tool_calls": [{"id": "t1", "type": "function", "function": {
        "name": "environment_snapshot", "arguments": json.dumps({"categories": categories})}}]}


class Arms(unittest.TestCase):
    task = run.tasks()["gpu-check"]

    def test_a_has_no_tool_and_is_judged(self):
        c = Scripted([BAD])
        rec = run.run_arm(c, "macos-arm", self.task, "A", 2)
        self.assertIsNone(c.sent[0][1])
        self.assertEqual(rec["verdict"]["status"], "BROKEN")

    def test_b_answers_the_tool_from_the_profile(self):
        c = Scripted([call(["system.os", "hardware.gpu"]), GOOD])
        rec = run.run_arm(c, "macos-arm", self.task, "B", 2)
        tool_msg = c.sent[1][0][-1]
        self.assertEqual(tool_msg["role"], "tool")
        self.assertIn("system.os", json.loads(tool_msg["content"])["categories"])
        self.assertEqual((rec["tool_calls"], rec["categories_asked"]), (1, ["system.os", "hardware.gpu"]))

    def test_c_puts_the_snapshot_in_the_first_message(self):
        c = Scripted([GOOD])
        run.run_arm(c, "macos-arm", self.task, "C", 2)
        self.assertIn("environment_snapshot", c.sent[0][0][1]["content"])
        self.assertIsNone(c.sent[0][1])

    def test_d_feeds_back_wont_run_until_it_fits(self):
        c = Scripted([BAD, GOOD])
        rec = run.run_arm(c, "macos-arm", self.task, "D", 2)
        self.assertEqual(rec["feedback_rounds"], 1)
        self.assertIn("nvidia-smi", c.sent[1][0][-1]["content"])
        self.assertEqual((rec["first_verdict"], rec["verdict"]["status"] != "BROKEN"), ("BROKEN", True))

    def test_pilot_units_are_stratified_by_profile(self):
        pairs = [tuple(p) for p in json.loads((HERE / "tasks/units.json").read_text())["pairs"]]
        units = run.pilot_units(pairs, 40, 1)
        self.assertEqual(len(units), 40)
        self.assertEqual(len({p for p, _ in units}), 8)

    def test_d_does_not_feedback_a_foreign_os_alternative(self):
        answer = ('## macOS\n```bash\ngit --version\n```\n'
                  '## Windows (PowerShell)\n```powershell\nwinget install Git.Git\n```')
        c = Scripted([answer])
        result = run.run_arm(c, 'macos-arm', run.tasks()['install-git'], 'D', 2)
        self.assertEqual(result['feedback_rounds'], 0)
        self.assertEqual(result['verdict']['targeting'], 'HEDGED')
        self.assertEqual(result['verdict']['commands_total'], 2)
        self.assertEqual(result['verdict']['commands_for_profile'], 1)


if __name__ == "__main__":
    unittest.main()
