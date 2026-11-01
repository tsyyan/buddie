"""POSIX structures stay intact; their syntax and inner commands are both checked."""
import unittest
from test_judge import grade, judge
import commands


class Control(unittest.TestCase):
    def test_nested_structure_is_one_extracted_command(self):
        text = 'if true; then\nfor item in one two; do\necho "done; fi"\ndone\nfi'
        self.assertEqual(commands.extract(f'```bash\n{text}\n```'), [{'text': text, 'shell': 'bash'}])

    def test_all_control_forms_are_extracted_even_incomplete(self):
        for text in ['if true; then ls; fi', 'for x in one; do ls; done',
                     'while false; do ls; done', 'case value in value) ls ;; esac', 'if true; then',
                     'if true; then\necho "unterminated']:
            self.assertEqual(commands.extract(f'```sh\n{text}\n```'), [{'text': text, 'shell': 'sh'}])

    def test_control_syntax_and_children(self):
        if judge.syntax('sh', ':') is None:
            self.skipTest('dash parser absent')
        for text, status in [
                ('if true; then ls; else mkdir output; fi', 'FITS'),
                ('for item in one two; do ls && mkdir output; done', 'FITS'),
                ('while false; do ls; done', 'FITS'),
                ('case value in value) ls ;; other) mkdir output ;; esac', 'FITS'),
                ('if [ -d output ]; then ls; fi', 'FITS'),
                ('if true; then conda --version; fi', 'WONT_RUN'),
                ('if true; then python3 --imaginary; fi', 'UNKNOWN'),
                ('if true; then', 'WONT_RUN'),
                ('if [[ -d output ]]; then ls; fi', 'WONT_RUN')]:
            with self.subTest(text=text):
                result = grade('alpine-container', 'list-files', text, 'bash')
                self.assertEqual(len(result['commands']), 1)
                self.assertEqual(result['commands'][0]['status'], status)

    def test_branch_state_is_local_but_prior_answer_setup_is_visible(self):
        if judge.syntax('sh', ':') is None:
            self.skipTest('dash parser absent')
        answer = ('```sh\nif true; then python3 -m venv .venv; . .venv/bin/activate; '
                  'else . .venv/bin/activate; fi\n```\n```sh\n. .venv/bin/activate\n```')
        result = judge.judge_answer(answer, 'alpine-container', 'python-venv')
        self.assertEqual(result['commands'][0]['status'], 'UNKNOWN')
        self.assertEqual(result['commands'][1]['status'], 'UNKNOWN')
        good = 'python3 -m venv .venv && if true; then . .venv/bin/activate; fi'
        self.assertEqual(grade('alpine-container', 'python-venv', good, 'sh')['status'], 'OK')

    def test_nested_broken_command_is_not_hidden(self):
        text = 'for x in one; do if true; then conda --version; fi; done'
        result = grade('alpine-container', 'list-files', text, 'sh')
        self.assertEqual(result['status'], 'BROKEN')

    def test_dynamic_headers_are_not_approved(self):
        text = 'for x in $(python3 --imaginary); do ls; done'
        result = grade('alpine-container', 'list-files', text, 'sh')
        self.assertNotEqual(result['status'], 'OK')

    def test_dynamic_case_patterns_are_not_approved(self):
        text = 'case value in `conda --version`) ls ;; esac'
        self.assertEqual(grade('alpine-container', 'list-files', text, 'sh')['commands'][0]['status'], 'UNKNOWN')

    def test_quoted_multiline_comments_in_control_are_literal(self):
        text = 'if true; then\necho "first\n# conda --version\nlast"\nfi'
        self.assertEqual(commands.extract(f'```sh\n{text}\n```'), [{'text': text, 'shell': 'sh'}])

    def test_conditional_deletion_invalidates_an_existing_venv_proof(self):
        if judge.syntax('sh', ':') is None:
            self.skipTest('dash parser absent')
        answer = ('```sh\npython3 -m venv .venv\nif true; then rm -f .venv/bin/activate; fi\n'
                  '. .venv/bin/activate\n```')
        result = judge.judge_answer(answer, 'alpine-container', 'python-venv')
        self.assertEqual(result['commands'][-1]['status'], 'UNKNOWN')
