# Reproducing the architecture audit

From repository root at `0bc048e7439ac283409fdfd05f763a506a95888a` (or this docs-only branch),
save the following block as a temporary `audit_repro.py` outside the repository.
Run `py -3.14 <absolute-path>/audit_repro.py <absolute-repo-path>` on Windows, or
`python3 <absolute-path>/audit_repro.py <absolute-repo-path>` on POSIX. No dependencies or network.
Children inherit the interpreter, use a fresh import cache, and disable the machine journal.
The parent never changes repository files. Temporary evidence is removed on exit.

```python
import ast, json, os, subprocess, sys, tempfile
from pathlib import Path

root = Path(sys.argv[1]).resolve()
graph = {}
top_graph = {}
counts = [0, 0]
class Imports(ast.NodeVisitor):
    depth = 0
    def visit_FunctionDef(self, n):
        self.depth += 1
        self.generic_visit(n)
        self.depth -= 1
    visit_AsyncFunctionDef = visit_FunctionDef
    def visit_Import(self, n):
        targets = {a.name for a in n.names if a.name.startswith('buddie.')}
        self.record(targets)
    def visit_ImportFrom(self, n):
        targets = ({'buddie.'+a.name for a in n.names} if n.module == 'buddie' else
                   {n.module} if n.module and n.module.startswith('buddie.') else set())
        self.record(targets)
    def record(self, targets):
        if targets:
            counts[bool(self.depth)] += 1
            if not self.depth:
                self.edges.update(targets)

for f in (root / 'buddie').rglob('*.py'):
    name = '.'.join(f.relative_to(root).with_suffix('').parts)
    if name.endswith('.__init__'):
        name = name[:-9]
    edges = graph.setdefault(name, set())
    visitor = Imports()
    visitor.edges = top_graph.setdefault(name, set())
    visitor.visit(ast.parse(f.read_text(encoding='utf-8')))
    for n in ast.walk(ast.parse(f.read_text(encoding='utf-8'))):
        if isinstance(n, ast.Import):
            edges.update(a.name for a in n.names if a.name.startswith('buddie.'))
        elif isinstance(n, ast.ImportFrom) and n.module:
            if n.module == 'buddie':
                edges.update('buddie.' + a.name for a in n.names)
            elif n.module.startswith('buddie.'):
                edges.add(n.module)
graph = {k: v & graph.keys() for k, v in graph.items()}

def components(g):
    def reach(start):
        seen, todo = set(), [start]
        while todo:
            v = todo.pop()
            if v not in seen:
                seen.add(v)
                todo.extend(g[v])
        return seen
    reachability = {k: reach(k) for k in g}
    remaining, result = set(g), []
    while remaining:
        k = min(remaining)
        part = {v for v in remaining if v in reachability[k] and k in reachability[v]}
        remaining -= part
        if len(part) > 1:
            result.append(sorted(part))
    return sorted(result, key=lambda c: (-len(c), c))

top_graph = {k: v & graph.keys() for k,v in top_graph.items()}
print('IMPORT_COUNTS', counts, 'TOP_LEVEL_SCC', components(top_graph))
assert not any(k in v for k,v in top_graph.items())  # no self-import cycle either
for cuts in [[], [('policy','diagnostics')],
             [('policy','diagnostics'),('anchors','summary'),('effects','freshness')]]:
    g = {k: set(v) for k,v in graph.items()}
    for a,b in cuts:
        g['buddie.'+a].discard('buddie.'+b)
    print('SCC', cuts, components(g))

def child(code):
    env = dict(os.environ, BUDDIE_LOG='0', PYTHONUTF8='1')
    run = subprocess.run([sys.executable, '-c', code], cwd=root, env=env,
                         capture_output=True, text=True, encoding='utf-8', check=True)
    print(run.stdout.strip())

# E1: identical API inputs, journal absent/present. No real machine paths printed.
child('''
import json, os, tempfile
from pathlib import Path
from buddie.verify import verify
with tempfile.TemporaryDirectory() as d:
    p = Path(d)/'journal.jsonl'
    os.environ['BUDDIE_LOG'] = str(p)
    for present in [False, True]:
        if present:
            p.write_text(json.dumps({'choice':{'id':'card42','chosen':['3']}})+'\\n')
        r = verify('Done. ⚓ `choice:card42=3`', fetch=False, mandate=False)['predicate']
        print('E1', present, r['outcome'], r['anchors'])
''')

# E2: fresh interpreter per module/text; injected import failure is intentional.
for blocked in ['summary','decisions','mandate','freshness','diagnostics','environment',
                'effects','stores','policy','verbatim.numbers']:
    for kind,text in [('quote','"A long enough literal quotation" [source](https://example.com)'),
                      ('file','⚓ `buddie/__init__.py@0bc048e`'),
                      ('choice','⚓ `choice:card42=3`'),
                      ('ci','⚓ `ci:tsyyan/buddie@0bc048e=success`'),
                      ('quote+choice','"A long enough literal quotation" [source](https://example.com) ⚓ `choice:card42=3`')]:
        child(f'''
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == {'buddie.'+blocked!r}:
            raise ImportError('audit blocked import')
sys.meta_path.insert(0, Block())
try:
    from buddie.verify import verify
    verify({text!r}, fetch=False, github=None, mandate=False)
    print('E2', {blocked!r}, {kind!r}, 'ok')
except ImportError:
    print('E2', {blocked!r}, {kind!r}, 'CRASH')
''')

# E3: print actual module names, not just counts. Root package excluded.
for label,code in [
    ('contracts','from buddie import core, modules, profiles, receipts'),
    ('file',"from buddie.verify import verify; verify('⚓ `buddie/__init__.py@0bc048e`', fetch=False, github=None, mandate=False)"),
    ('environment','from buddie import environment'),
    ('freshness','from buddie import freshness'),
    ('mcp',"from buddie.mcp import handle; handle({'jsonrpc':'2.0','id':1,'method':'tools/list'})"),
    ('verbatim',"from buddie.verbatim.check import check_claims; from buddie.verbatim.store import Store; from buddie.verbatim.report import from_markdown; import tempfile; d=tempfile.TemporaryDirectory(); check_claims(from_markdown('')[0], Store(d.name), fetch=False)")]:
    child(code + "; import sys; names=sorted(n for n in sys.modules if n.startswith('buddie.')); print('E3', "
          + repr(label) + ", len(names), names)")
```

The graph includes function imports and reports nontrivial SCCs. It does not equate lazy imports with
runtime loading. Relative imports are absent in the pinned sources; a later refactor using them must
extend the resolver. Re-run on a new main after #55, rather than assuming pinned counts remain valid.
