"""Rebuild synthetic profiles; no probes run and nothing is claimed recorded."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from buddie import __version__, diagnostics as dg, probes

STAMP = '2026-11-01T00:00:00Z'
BASE = sorted(dg.expand(['baseline']))
SPECS = [
    ('win11-pwsh-nvidia', 'windows', 'Windows', '11', 'AMD64', 'powershell',
     '3.12.7', 'winget', 'GTX 1650', '13.2', None, False),
    ('win11-cmd-nogpu', 'windows', 'Windows', '10', 'AMD64', 'cmd',
     '3.11.9', 'choco', None, None, None, False),
    ('macos-arm', 'darwin', 'macOS', '15.0', 'arm64', 'zsh',
     '3.13.0', 'brew', None, None, None, False),
    ('ubuntu2404-nvidia', 'linux', 'Ubuntu', '24.04', 'x86_64', 'bash',
     '3.12.7', 'apt', 'RTX 4090', '12.4', '12.4', False),
    ('ubuntu2204-nosudo', 'linux', 'Ubuntu', '22.04', 'x86_64', 'bash',
     '3.10.12', 'apt', None, None, None, False),
    ('wsl-ubuntu', 'linux', 'Ubuntu', '22.04', 'x86_64', 'bash',
     '3.10.12', 'apt', 'RTX 3060', '12.2', None, False),
    ('fedora40', 'linux', 'Fedora Linux', '40', 'x86_64', 'bash',
     '3.12.7', 'dnf', None, None, None, False),
    ('alpine-container', 'linux', 'Alpine Linux', '3.20', 'x86_64', 'sh',
     '3.12.7', 'apk', None, None, None, True),
]


def category(cid, values):
    """Use declared observation/method names and the collector's status convention."""
    module = dg.REGISTRY[cid]
    obs, methods = {}, []
    for name, (value, method, basis, reason) in values.items():
        obs[name] = dict(status='observed' if value is not None else 'unavailable',
                         value=value, basis=basis if value is not None else None,
                         method=method, observed_at=STAMP, reason=reason, concerns='runtime')
        record = dict(method=method, why='synthetic_collector_attempt',
                      outcome='used' if module.methods[method].kind != 'program' else
                      'ok' if value is not None else 'not_found')
        if record not in methods:
            methods.append(record)
    seen = sum(o['value'] is not None for o in obs.values())
    status = 'collected' if seen == len(obs) and seen else 'partial' if seen else 'unavailable'
    return dict(status=status, reason='nothing_observed' if not seen else None,
                tier=module.tier, methods=methods, observations=obs)


def build(spec):
    pid, platform, name, ver, arch, shell, pyver, pm, gpu, cuda, toolkit, root = spec
    win, mac = platform == 'windows', platform == 'darwin'
    ctx = 'wsl' if pid == 'wsl-ubuntu' else 'container' if root else 'native'
    cats = {}

    def put(cid, values):
        cats[cid] = category(cid, values)

    def o(v, method, basis='os_interface', reason=None):
        return v, method, basis, reason if v is None else None

    def p(v, method, reason='not_found_on_path'):
        return o(v, method, 'path_program', reason)

    osvals = {k: o(v, 'platform') for k, v in
              dict(family='Windows' if win else 'macOS' if mac else 'Linux',
                   kernel='10.0.22631' if win else '24.0.0' if mac else '6.8.0',
                   architecture=arch).items()}
    osvals.update({k: o(v, 'win32_ver' if win else 'mac_ver' if mac else 'os_release')
                   for k, v in dict(name=f'Windows {ver}' if win else name,
                                    version='10.0.22631' if win else ver).items()})
    if win:
        osvals['edition'] = o('Professional', 'win32_ver')
    # Runtime context is observed via markers on Linux, platform elsewhere.
    osvals['runtime_context'] = o(ctx, 'win32_ver' if win else 'mac_ver' if mac else 'runtime_markers')
    if platform == 'linux':
        osvals['distribution_id'] = o('alpine' if root else 'fedora' if pm == 'dnf' else 'ubuntu', 'os_release')
        if root:
            osvals['container_engine'] = o('docker', 'runtime_markers')
    put('system.os', osvals)
    shells = {n: p('5.2.26' if n == 'bash' else '5.9' if n == 'zsh' else
                   '7.4.6' if n == 'pwsh' else None, 'shell_' + n)
              for n in ('bash', 'zsh', 'fish', 'pwsh')}
    present = {'bash'} if shell == 'bash' else {'zsh'} if mac else {'pwsh'} if shell == 'powershell' else set()
    shells = {n: val if n in present else p(None, 'shell_' + n) for n, val in shells.items()}
    if win:
        shells.update(powershell=p('5.1.22621.1', 'shell_powershell'), cmd=o('present', 'cmd_present'))
    else:
        shells['default'] = o('ash' if root else shell, 'login_shell')
    put('system.shell', shells)
    put('system.permissions', dict(elevated=o(root, 'privilege'),
        scope=o("this process: a container's or WSL guest's root is not the host's", 'privilege', 'buddie')))
    cpu = {k: o(v, 'platform') for k, v in dict(architecture=arch, logical_cores=8).items()}
    cpu['model'] = o('Apple M3' if mac else 'Synthetic x86 CPU',
                     'registry_cpu' if win else 'sysctl_cpu' if mac else 'cpuinfo',
                     'fixed_program' if mac else 'os_interface')
    put('hardware.cpu', cpu)
    memory_method = 'memory_status' if win else 'sysctl_memory' if mac else 'meminfo'
    mem = dict(total_bytes=o(16 * 2**30, memory_method), available_bytes=o(8 * 2**30, memory_method))
    if mac:
        mem['available_bytes'] = o(8 * 2**30, 'vm_stat', 'fixed_program')
    if root:
        mem['cgroup_limit_bytes'] = o(2 * 2**30, 'cgroup_memory')
    put('hardware.memory', mem)
    gm = 'nvidia_smi_gpus' if gpu else 'registry_display' if win else 'system_profiler_displays' if mac else 'sysfs_drm'
    adapters = ([dict(vendor='NVIDIA', model='NVIDIA GeForce ' + gpu, source=gm,
                      vram_bytes=(4 if '1650' in gpu else 24 if '4090' in gpu else 12) * 2**30)] if gpu else
                [dict(vendor='Apple' if mac else 'Intel', model='Apple M3' if mac else 'UHD Graphics', source=gm)]
                if win or mac else None)
    gv = dict(adapters=o(adapters, gm, 'fixed_program' if gpu or mac else 'os_interface', 'none_found'))
    if ctx == 'wsl':
        gv['wsl_gpu_bridge'] = o(True, 'sysfs_drm')
    put('hardware.gpu', gv)
    facts = dict(version=pyver, implementation='cpython', bits=64, pip=True,
                 venv=pid != 'ubuntu2204-nosudo', ensurepip=pid != 'ubuntu2204-nosudo')
    launcher_only = pid == 'win11-pwsh-nvidia'
    py = dict(buddie_runtime=o(dict(version='3.12.7', implementation='cpython', pip=True, venv=True),
                              'own_interpreter', 'buddie'),
              interpreters=p(None if launcher_only else [dict(found_via=('python' if win else 'python3') + ' on PATH',
                                                            **facts)], 'python_on_path'))
    if win:
        py['py_launcher_versions'] = p(['3.12'] if launcher_only else None, 'py_launcher', 'not_found')
    put('software.python', py)
    put('software.runtimes', {n: p(None, 'runtime_' + n) for n in probes.RUNTIMES})
    put('software.package_managers', {n: p('1.0.0' if n == pm else None, 'pm_' + n)
                                     for n, (platforms, _, _) in probes.PACKAGE_MANAGERS.items() if platform in platforms})
    if mac:
        stack = {n: o(None, 'platform', reason='not_applicable_on_platform')
                 for n in ('nvidia_driver', 'cuda_driver', 'cuda_toolkit', 'rocm')}
        stack['metal'] = o('Metal 3', 'system_profiler_metal', 'fixed_program')
    else:
        stack = dict(nvidia_driver=p('580.0' if gpu else None, 'nvidia_smi_query', 'not_found'),
                     cuda_driver=p(cuda, 'nvidia_smi_query', 'not_found'), cuda_toolkit=p(toolkit, 'nvcc'),
                     rocm=o(None, 'platform' if win else 'rocm_version',
                            reason='not_probed_on_platform' if win else 'not_found'))
    put('software.gpu_stack', stack)
    tool_versions = {'git': '2.47.0', 'curl': '8.10.1', 'tar': '1.35'}
    if toolkit:
        tool_versions['nvcc'] = toolkit
    put('software.tools', {n: p(tool_versions.get(n), 'tool:' + n) for n in probes.TOOLS})
    put('development.containers', dict(docker_client=p(None, 'docker_client'),
                                      podman_client=p('5.2.0' if pm == 'dnf' else None, 'podman_client')))
    granted = BASE + (['development.containers'] if pm == 'dnf' else [])
    # Unrequested sensitive categories are omitted in real collection too.
    if pm != 'dnf':
        cats.pop('development.containers')
    doc = dict(format=dg.FORMAT, collector=dict(buddie=__version__, policy='absent', platform=platform),
               request=dict(id=pid.replace('-', ''), categories=list(cats), rejected=[],
                            tools=list(probes.TOOLS), rejected_tools=[], path_given=False),
               authorization=dict(grants='active', policy='absent', effective=sorted(cats)),
               started_at=STAMP, finished_at=STAMP, observations_concern='runtime', categories=cats,
               supplied={}, limitations=[], scopes=dg.scopes(False), snapshot=None)
    assert not dg.problems(doc), (pid, dg.problems(doc))
    metadata = dict(id=pid, description=f'{name} {ver}; {shell}; {pm}; {gpu or "no NVIDIA GPU"}',
                    provenance='hand-built', granted=granted, shell=shell,
                    assumptions=dict(sudo=platform == 'linux' and not root and pid != 'ubuntu2204-nosudo',
                                     libc='musl' if root else 'unknown',
                                     sh_semantics='busybox' if root else 'dash',
                                     launcher_python=facts if launcher_only else None))
    return doc, metadata


def main():
    folder = Path(__file__).resolve().parent
    index = []
    for spec in SPECS:
        doc, meta = build(spec)
        (folder / (meta['id'] + '.json')).write_text(json.dumps(doc, indent=2) + '\n', encoding='utf-8')
        index.append(meta)
    (folder / 'index.json').write_text(json.dumps(index, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
