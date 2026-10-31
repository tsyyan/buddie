"""Replay diagnostic fixtures with real request and authorization semantics."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from buddie import diagnostics as dg, probes

TOOL = json.loads((HERE / 'tool_schema.json').read_text(encoding='utf-8'))


def load_profile(profile):
    """Accept an index id, diagnostic document, or {'document', 'granted', ...} row."""
    if isinstance(profile, dict):
        if 'document' in profile:
            return deepcopy(profile)
        if profile.get('format') == dg.FORMAT:
            index = json.loads((HERE / 'profiles/index.json').read_text(encoding='utf-8'))
            matches = [r for r in index if r['id'].replace('-', '') == profile['request']['id']]
            if not matches:
                raise ValueError('document has no profile index entry')
            return dict(deepcopy(matches[0]), document=deepcopy(profile))
        raise ValueError('profile: index id or diagnostic document')
    index = json.loads((HERE / 'profiles/index.json').read_text(encoding='utf-8'))
    row = next((r for r in index if r['id'] == profile), None)
    if row is None:
        raise ValueError('unknown profile')
    return dict(row, document=json.loads((HERE / 'profiles' / (row['id'] + '.json')).read_text(encoding='utf-8')))


def catalog(profile):
    """Describe the static registry using the fixture's platform and grants."""
    platform = profile['document']['collector']['platform']
    return dict(format=dg.CATALOG_FORMAT, platform=platform,
                grants=dict(status='active', allowed=sorted(profile['granted']), roots_count=0),
                categories=[dict(id=m.id, tier=m.tier, summary=m.summary, observations=list(m.observations),
                                 methods=sorted(m.methods), platforms=list(m.platforms), scope=m.scope,
                                 supported_here=platform in m.platforms, limits=m.limits) for m in dg.REGISTRY.values()],
                unsupported=[dict(id=k, why=v) for k, v in dg.UNSUPPORTED.items()], tools_catalog=sorted(probes.TOOLS))


def empty(cid, status, reason):
    return dict(status=status, reason=reason, tier=dg.REGISTRY[cid].tier if cid in dg.REGISTRY else None,
                methods=[], observations={})


def environment_snapshot(args, profile):
    """Return fixture data only; invalid calls raise ValueError (a tool error at the API boundary)."""
    if type(args) is not dict:
        raise ValueError('arguments: an object')
    if extra := sorted(set(args) - {'categories', 'task', 'tools', 'path', 'list'}):
        raise ValueError('unknown arguments ' + ', '.join(extra))
    p = load_profile(profile)
    if args.get('list'):
        return catalog(p)
    known, rejected, tools, bad_tools, task = dg.validate(args.get('categories'), args.get('tools'), args.get('task'))
    path = args.get('path')
    if path is not None and (type(path) is not str or not path or len(path) > 4096 or '\0' in path):
        raise ValueError('path: a directory')
    doc, out, effective = deepcopy(p['document']), {}, []
    platform = doc['collector']['platform']
    for cid in list(dg.REGISTRY) + list(dg.UNSUPPORTED):
        if cid not in known:
            continue
        if cid in dg.UNSUPPORTED:
            out[cid] = dict(empty(cid, 'unsupported', 'not_supported'), explanation=dg.UNSUPPORTED[cid])
            continue
        module = dg.REGISTRY[cid]
        if cid in p['granted']:
            effective.append(cid)
        if platform not in module.platforms:
            out[cid] = empty(cid, 'unsupported', 'unsupported_platform')
        elif cid not in p['granted']:
            out[cid] = empty(cid, 'denied', 'not_granted')
        elif module.scope == 'path':
            # Starter profiles grant no directories. Never resolve paths on the runner.
            out[cid] = empty(cid, 'unavailable' if path is None else 'denied',
                             'no_path_given' if path is None else 'path_not_granted')
        elif module.scope == 'tools' and not tools and not bad_tools:
            out[cid] = empty(cid, 'unavailable', 'no_tools_given')
        else:
            entry = deepcopy(doc['categories'].get(cid, empty(cid, 'unavailable', 'nothing_observed')))
            if cid == 'software.tools':
                entry['observations'] = {n: o for n, o in entry['observations'].items() if n in tools}
                entry['methods'] = [m for m in entry['methods'] if m['method'] in {'tool:' + n for n in tools}]
                for bad in bad_tools:
                    if bad['name']:
                        entry['observations'][bad['name']] = dict(status='unavailable', value=None, basis=None,
                            method=None, observed_at=doc['finished_at'], reason='not_in_catalog', concerns='runtime')
                seen = sum(o['status'] == 'observed' for o in entry['observations'].values())
                entry['status'] = 'collected' if seen and seen == len(entry['observations']) else 'partial' if seen else 'unavailable'
                entry['reason'] = None if seen else 'nothing_observed'
            out[cid] = entry
    doc.update(categories=out, supplied={'task': task} if task is not None else {}, limitations=[],
               authorization=dict(grants='active', policy='absent', effective=sorted(effective)))
    doc['request'] = dict(id=uuid.uuid5(uuid.NAMESPACE_URL, p['id'] + json.dumps(args, sort_keys=True)).hex,
                         categories=[c for c in args['categories'] if dg.ID.match(c)][:dg.MAX_CATEGORIES],
                         rejected=rejected, tools=tools, rejected_tools=bad_tools, path_given=path is not None)
    return doc
