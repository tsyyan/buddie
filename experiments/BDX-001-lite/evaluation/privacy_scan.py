"""Model-free heuristic scan of committed BDX-001 data; never print matched values.

python experiments/BDX-001-lite/evaluation/privacy_scan.py [REF ...]
Pass every PR commit to inspect public history; default HEAD. Code/test samples excluded.
Not a proof that arbitrary secrets, hostnames or nonstandard paths are absent.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PATTERNS = {
    'profile': re.compile(r'(?:Users(?:\\+|/)+|/home/)([A-Za-z0-9_.@-]+)|C--Users-([A-Za-z0-9_.@]+)', re.I),
    'email': re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', re.I),
    'credential': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-ant-[A-Za-z0-9_-]{20,})'),
}
GENERIC = {'user', 'runner', 'root', 'public', 'default', 'username', 'you', '...'}


def git(*args):
    return subprocess.check_output(['git', *args], cwd=REPO)


def scan(ref):
    findings = []
    paths = ['experiments/BDX-001-lite/fixtures/raw', 'experiments/BDX-001-lite/results']
    for line in git('ls-tree', '-r', ref, '--', *paths).decode().splitlines():
        meta, path = line.split('\t')
        sha = meta.split()[2]
        data = git('cat-file', 'blob', sha).decode('utf-8', 'replace')
        counts = {}
        for kind, pattern in PATTERNS.items():
            matches = pattern.findall(data)
            if kind == 'profile':
                matches = [next((p for p in m if p), '') for m in matches]
                matches = [m for m in matches if m.lower() not in GENERIC]
            if matches:
                counts[kind] = len(matches)
        if counts:
            findings.append({'path': path, 'blob': sha, 'counts': counts})
    return {'ref': ref, 'findings': findings}


if __name__ == '__main__':
    results = [scan(ref) for ref in sys.argv[1:] or ['HEAD']]
    print(json.dumps(results, indent=1))
    raise SystemExit(1 if any(r['findings'] for r in results) else 0)
