"""New audience outcomes survive the model-free summary; legacy runs stay unrecorded."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from test_judge import HERE, judge
import summarize


class Summary(unittest.TestCase):
    def render(self, verdict):
        row = dict(model='fixture', arm='A', profile='macos-arm', task='install-git', verdict=verdict,
                   tool_calls=0, requests=1, sent_chars=10, final='offline fixture')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'rows.jsonl'
            path.write_text(json.dumps(row) + '\n', encoding='utf-8')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(summarize.main([str(path)]), 0)
            return out.getvalue()

    def test_targeting_and_read_counts_are_reported(self):
        case = json.loads((HERE / 'tests/multi_section_answers.json').read_text())[0]
        output = self.render(judge.judge_answer(case['answer'], 'macos-arm', 'install-git'))
        self.assertIn("'HEDGED': 1", output)
        self.assertIn('offered 8.0, for profile 2.0', output)

    def test_old_rows_are_not_relabelled_targeted(self):
        output = self.render(dict(status='OK', commands=[]))
        self.assertIn('UNRECORDED', output)
