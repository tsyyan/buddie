"""Measure UNKNOWN commands without dropping broken answers or parser-dependent cases."""
import argparse
from collections import Counter
import json
from pathlib import Path

from judge import judge_answer, leaf_commands
from syntax import syntax
from tool import HERE


def summarize(cases):
    """The denominator is every extracted command, not answers or decided commands."""
    answers = [judge_answer(c['answer'], c['profile'], c['task']) for c in cases]
    counts = Counter(row['status'] for answer in answers for row in answer['commands'])
    total = sum(counts.values())
    leaves = Counter(row['status'] for answer in answers for row in leaf_commands(answer['commands']))
    leaf_total = sum(leaves.values())
    return dict(answers=len(answers), commands=total, unknown_commands=counts['UNKNOWN'],
                commands_total=sum(a['commands_total'] for a in answers),
                commands_for_profile=sum(a['commands_for_profile'] for a in answers),
                targeting=dict(Counter(a['targeting'] for a in answers)),
                unknown_share=counts['UNKNOWN'] / total if total else None,
                leaf_commands=leaf_total, unknown_leaf_commands=leaves['UNKNOWN'],
                unknown_leaf_share=leaves['UNKNOWN'] / leaf_total if leaf_total else None,
                leaf_outcomes=dict(leaves),
                command_outcomes=dict(counts), answer_outcomes=dict(Counter(a['status'] for a in answers)))


def compare(cases, baseline):
    """Report all current answers and also the unchanged original set to expose denominator changes."""
    before = Counter(c['status'] for r in baseline['rows'] for c in r['commands'])
    before_leaves = Counter(c['status'] for r in baseline['rows'] for c in leaf_commands(r['commands']))
    total = sum(before.values())
    original_ids = {r['id'] for r in baseline['rows']}
    if not original_ids <= {r['id'] for r in cases}:
        raise ValueError('current corpus omits baseline answer IDs')
    return dict(baseline_commit=baseline['commit'],
                before=dict(answers=len(baseline['rows']), commands=total, unknown_commands=before['UNKNOWN'],
                            commands_total=sum(r.get('commands_total', len(r['commands'])) for r in baseline['rows']),
                            commands_for_profile=total,
                            unknown_share=before['UNKNOWN'] / total if total else None,
                            leaf_commands=sum(before_leaves.values()), unknown_leaf_commands=before_leaves['UNKNOWN'],
                            unknown_leaf_share=before_leaves['UNKNOWN'] / sum(before_leaves.values()) if before_leaves else None),
                after_all=summarize(cases),
                after_original=summarize([c for c in cases if c['id'] in original_ids]),
                parsers_available={s: syntax(s, ':') is not None for s in ('bash', 'sh', 'powershell')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--answers', type=Path, default=HERE / 'tests/answers.json')
    parser.add_argument('--baseline', type=Path, default=HERE / 'tests/unknown_before.json')
    parser.add_argument('--multi-section', type=Path, help='additional audience fixtures with per-profile checks')
    parser.add_argument('--extra-answers', type=Path, action='append', default=[], help='additional recorded answer files')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    cases = json.loads(args.answers.read_text(encoding='utf-8'))
    for path in args.extra_answers:
        cases.extend(json.loads(path.read_text(encoding='utf-8')))
    extra = []
    if args.multi_section:
        extra = [dict(id=c['id'] + ':' + check['profile'], profile=check['profile'], task=c['task'], answer=c['answer'])
                 for c in json.loads(args.multi_section.read_text(encoding='utf-8')) for check in c['checks']]
    report = compare(cases + extra, json.loads(args.baseline.read_text(encoding='utf-8')))
    if extra:
        report['after_existing'] = summarize(cases)
        report['after_multi_section'] = summarize(extra)
    text = json.dumps(report, indent=2) + '\n'
    if args.out:
        args.out.write_text(text, encoding='utf-8')
    print(text, end='')


if __name__ == '__main__':
    main()
