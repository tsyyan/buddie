"""Preparation and safe usage import only. No enabled model or live GitHub executor."""
import argparse
import hashlib
import json
import random
from pathlib import Path

from instrumentation import usage

ROOT = Path(__file__).resolve().parent


def prepare(seed=20261026):
    cases = json.loads((ROOT / 'cases.json').read_text(encoding='utf-8'))['cases']
    tasks = [{'case': c['id'], 'arm': arm, 'hooks': False, 'task': c['task'], 'locators': c['locators']}
             for c in cases for arm in ('A_direct', 'B_core')]
    random.Random(seed).shuffle(tasks)
    return {'schema': 'bdx-002/preparation-v1', 'paid_execution_enabled': False,
            'model': None, 'usd_ceiling': None, 'repetitions': None,
            'seed': seed, 'tasks': tasks, 'sha256': {
                name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                for name in ('cases.json', 'evaluation/expected.json')},
            'limits': 'Preparation only; no results. Citation and hook strata need separately frozen manifests.'}


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--out', required=True)
    p.add_argument('--seed', type=int, default=20261026)
    p = sub.add_parser('import-runtime')
    p.add_argument('--result', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--manifest', required=True, help='frozen, separately approved comparison manifest')
    sub.add_parser('run')
    args = parser.parse_args(argv)
    if args.command == 'run':
        print('REFUSED: paid execution is disabled; separate user approval and reviewed runner required.')
        return 2
    try:
        if args.command == 'prepare':
            data = prepare(args.seed)
        else:
            # Bounded read; write only validated counters, never raw runtime payload.
            with Path(args.result).open('rb') as source:
                raw = source.read(16 * 2**20 + 1)
            if len(raw) > 16 * 2**20:
                raise ValueError('runtime_result_too_large')
            with Path(args.manifest).open('rb') as source:
                manifest_raw = source.read(2**20 + 1)
            if len(manifest_raw) > 2**20:
                raise ValueError('manifest_too_large')
            manifest = json.loads(manifest_raw)
            if not isinstance(manifest, dict) or manifest.get('schema') != 'bdx-002/frozen-run-v1' \
                    or not all(manifest.get(k) for k in ('runtime', 'model', 'sampling_sha', 'tool_schemas_sha', 'approval_ref')):
                raise ValueError('frozen_manifest_required')
            data = {**usage(json.loads(raw)), 'result_sha256': hashlib.sha256(raw).hexdigest(),
                    'manifest_sha256': hashlib.sha256(manifest_raw).hexdigest(),
                    'binding': 'caller_supplied_manifest_not_runtime_authentication'}
        with Path(args.out).open('x', encoding='utf-8') as target:
            json.dump(data, target, ensure_ascii=False, indent=1, allow_nan=False)
        return 0
    except (OSError, ValueError, TypeError, RecursionError, OverflowError):
        print('REFUSED: invalid input or output already exists; no raw input is printed.')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
