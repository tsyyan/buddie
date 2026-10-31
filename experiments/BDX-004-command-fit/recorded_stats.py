"""Measure UNKNOWN commands without dropping broken answers or parser-dependent cases."""
import argparse
from collections import Counter
import json
from pathlib import Path

from judge import judge_answer
from syntax import syntax
from tool import HERE


def summarize(cases):
    """The denominator is every extracted command, not answers or decided commands."""
    answers = [judge_answer(c['answer'], c['profile'], c['task']) for c in cases]
    counts = Counter(row['status'] for answer in answers for row in answer['commands'])
    total = sum(counts.values())
    return dict(answers=len(answers), commands=total, unknown_commands=counts['UNKNOWN'],
                unknown_share=counts['UNKNOWN'] / total if total else None,
                command_outcomes=dict(counts), answer_outcomes=dict(Counter(a['status'] for a in answers)))


def compare(cases, baseline):
    """Report all current answers and also the unchanged original set to expose denominator changes."""
    before = Counter(c['status'] for r in baseline['rows'] for c in r['commands'])
    total = sum(before.values())
    original_ids = {r['id'] for r in baseline['rows']}
    if not original_ids <= {r['id'] for r in cases}:
        raise ValueError('current corpus omits baseline answer IDs')
    return dict(baseline_commit=baseline['commit'],
                before=dict(answers=len(baseline['rows']), commands=total, unknown_commands=before['UNKNOWN'],
                            unknown_share=before['UNKNOWN'] / total if total else None),
                after_all=summarize(cases),
                after_original=summarize([c for c in cases if c['id'] in original_ids]),
                parsers_available={s: syntax(s, ':') is not None for s in ('bash', 'sh', 'powershell')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--answers', type=Path, default=HERE / 'tests/answers.json')
    parser.add_argument('--baseline', type=Path, default=HERE / 'tests/unknown_before.json')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    report = compare(json.loads(args.answers.read_text(encoding='utf-8')),
                     json.loads(args.baseline.read_text(encoding='utf-8')))
    text = json.dumps(report, indent=2) + '\n'
    if args.out:
        args.out.write_text(text, encoding='utf-8')
    print(text, end='')


if __name__ == '__main__':
    main()
