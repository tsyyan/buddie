"""Write task requirements and reproducibly shuffle all eligible pairs."""
import json
from pathlib import Path
import random

HERE = Path(__file__).resolve().parents[1]
DEFINITIONS = [
    ('python-venv', 'Create a virtual environment for this project.', ['software.python'], True),
    ('activate-venv', 'Activate the virtual environment named .venv.', ['software.python'], True),
    ('install-requests', 'Install requests into the current Python environment.', ['software.python'], False),
    ('python-version', 'Show the Python version I can use.', ['software.python'], False),
    ('pytorch-gpu', 'Install PyTorch with GPU acceleration if it is supported.', ['software.python', 'hardware.gpu', 'software.gpu_stack'], False),
    ('gpu-check', 'Show my GPU and driver information.', ['hardware.gpu', 'software.gpu_stack'], True),
    ('cuda-toolkit', 'Show the installed CUDA compiler version.', ['software.gpu_stack', 'software.tools'], False),
    ('install-ffmpeg', 'Install ffmpeg so I can convert a video.', ['software.package_managers', 'system.permissions'], False),
    ('install-git', 'Install Git for this project.', ['software.package_managers', 'system.permissions'], False),
    ('install-node20', 'Install Node.js version 20.', ['software.package_managers', 'software.runtimes', 'system.permissions'], False),
    ('container-run', 'Run an ephemeral Alpine container.', ['development.containers'], False),
    ('container-version', 'Show the container client version.', ['development.containers'], False),
    ('session-variable', 'Set APP_MODE to development for this session.', [], True),
    ('show-variable', 'Print APP_MODE from this session.', [], True),
    ('port-process', 'Find the process listening on port 8000.', [], True),
    ('archive-create', 'Archive the folder data as data.tar.gz.', ['software.tools'], False),
    ('archive-extract', 'Extract data.tar.gz into the current directory.', ['software.tools'], False),
    ('download-file', 'Download https://example.org/data.txt to data.txt.', ['software.tools'], True),
    ('permissions', 'Allow my user to execute script.sh.', [], True),
    ('service-status', 'Show whether the SSH service is running.', ['system.permissions'], True),
    ('service-restart', 'Restart the SSH service.', ['system.permissions'], True),
    ('make-directory', 'Create a folder named output.', [], True),
    ('list-files', 'List files in the current directory.', [], True),
    ('remove-temp', 'Delete the file temp.txt.', [], True),
]


def rule(pattern, program, *, installs=None, admin=False, os=None, **checks):
    return dict(pattern=pattern, program=program, effect='INSTALLS' if installs else 'FITS',
                installs=installs or [], needs_admin=admin, os=os or ['windows', 'linux', 'darwin'], **checks)


def requirements(task, profile):
    """Each row spells out its shell, assumptions, and bounded accepted command forms."""
    pid, shell = profile['id'], profile['shell']
    win, mac = pid.startswith('win'), pid == 'macos-arm'
    alpine, noadmin = pid == 'alpine-container', pid == 'ubuntu2204-nosudo'
    py = r'py -3\.12' if pid == 'win11-pwsh-nvidia' else 'python' if win else 'python3'
    py_program = 'py' if py.startswith('py ') else py
    pm = 'winget' if pid == 'win11-pwsh-nvidia' else 'choco' if win else 'brew' if mac else 'apk' if alpine else 'dnf' if pid == 'fedora40' else 'apt'
    posix = ['linux', 'darwin']
    client = 'podman' if pid == 'fedora40' else 'docker'
    table = {
        'python-venv': [rule(py + r' -m venv \.venv', py_program, python_module='venv')],
        'activate-venv': [rule(r'\.\\\.venv\\Scripts\\Activate\.ps1', 'Activate.ps1',
                               requires_path=True)] if shell == 'powershell' else
                         [rule(r'\.venv\\Scripts\\activate(?:\.bat)?', 'activate.bat', requires_path=True)] if win else
                         [rule(r'(?:source|\.) \.venv/bin/activate', 'source', requires_path=True)],
        'install-requests': [rule(py + r' -m pip install requests', py_program, python_module='pip')],
        'python-version': [rule(py + r' --version', py_program)],
        'pytorch-gpu': [rule(py + r' -m pip install torch --index-url https://download\.pytorch\.org/whl/cu\d{3}',
                             py_program, python_module='pip', cuda_wheel=True, nvidia=True),
                        rule(py + r' -m pip install torch --index-url https://download\.pytorch\.org/whl/cpu',
                             py_program, python_module='pip')],
        'gpu-check': [rule(r'nvidia-smi(?: --query-gpu=name,memory.total --format=csv)?', 'nvidia-smi',
                           os=['windows', 'linux'], nvidia=True)] +
                     ([rule(r'system_profiler SPDisplaysDataType', 'system_profiler', os=['darwin'])] if mac else []),
        'cuda-toolkit': [rule(r'nvcc --version', 'nvcc', os=['windows', 'linux'])],
        'container-run': [rule(client + r' run --rm alpine(?::3\.20)? echo hello', client,
                               daemon=client == 'docker')],
        'container-version': [rule(client + r' --version', client)],
        'session-variable': [rule(r'\$env:APP_MODE\s*=\s*[\'\"]development[\'\"]', '$env:APP_MODE')] if shell == 'powershell' else
                            [rule(r'set APP_MODE=development', 'set')] if win else
                            [rule(r'export APP_MODE=development', 'export', os=posix)],
        'show-variable': [rule(r'(?:Write-Output|echo) \$env:APP_MODE', 'Write-Output')] if shell == 'powershell' else
                         [rule(r'echo %APP_MODE%', 'echo')] if win else
                         [rule(r'echo "?\$APP_MODE"?', 'echo', os=posix)],
        'port-process': [rule(r'Get-NetTCPConnection -LocalPort 8000', 'Get-NetTCPConnection', os=['windows'])] if shell == 'powershell' else
                        [rule(r'netstat -ano', 'netstat', os=['windows'])] if win else
                        [rule(r'lsof -i :8000', 'lsof', os=['darwin'])] if mac else
                        [rule(r'ss -ltnp(?: [\'\"]sport = :8000[\'\"])?', 'ss', os=['linux'])],
        'archive-create': [rule(r'tar -czf data\.tar\.gz data', 'tar')],
        'archive-extract': [rule(r'tar -xzf data\.tar\.gz', 'tar')],
        'download-file': [rule((r'curl\.exe' if shell == 'powershell' else r'curl(?:\.exe)?') +
                               r' -o data\.txt https://example\.org/data\.txt', 'curl'),
                          rule(r'Invoke-WebRequest https://example\.org/data\.txt -OutFile data\.txt',
                               'Invoke-WebRequest', os=['windows'])],
        'permissions': [rule(r'icacls script\.sh /grant "\$\{env:USERNAME\}:RX"', 'icacls', os=['windows'])] if shell == 'powershell' else \
                       [rule(r'icacls script\.sh /grant "%USERNAME%:RX"', 'icacls', os=['windows'])] if win else
                       [rule(r'chmod u\+x script\.sh', 'chmod', os=posix)],
        'service-status': [rule(r'Get-Service sshd', 'Get-Service', os=['windows'])] if shell == 'powershell' else
                          [rule(r'sc query sshd', 'sc', os=['windows'])] if win else
                          [rule(r'launchctl list', 'launchctl', os=['darwin'])] if mac else
                          [rule(r'rc-service sshd status', 'rc-service', os=['linux'])] if alpine else
                          [rule(r'systemctl status sshd?', 'systemctl', os=['linux'])],
        'service-restart': [rule(r'Restart-Service sshd', 'Restart-Service', os=['windows'], admin=True)] if shell == 'powershell' else
                           [rule(r'sc stop sshd', 'sc', os=['windows'], admin=True),
                            rule(r'sc start sshd', 'sc', os=['windows'], admin=True)] if win else
                           [rule(r'launchctl kickstart -k system/com.openssh.sshd', 'launchctl', os=['darwin'], admin=True)] if mac else
                           [rule(r'rc-service sshd restart', 'rc-service', os=['linux'], admin=True)] if alpine else
                           [rule(r'systemctl restart sshd?', 'systemctl', os=['linux'], admin=True)],
        'make-directory': [rule(r'New-Item -ItemType Directory output', 'New-Item')] if shell == 'powershell' else
                          [rule(r'mkdir output', 'mkdir')],
        'list-files': [rule(r'Get-ChildItem', 'Get-ChildItem')] if shell == 'powershell' else
                      [rule(r'dir', 'dir')] if win else [rule(r'ls', 'ls')],
        'remove-temp': [rule(r'Remove-Item temp\.txt', 'Remove-Item')] if shell == 'powershell' else
                       [rule(r'del temp\.txt', 'del')] if win else [rule(r'rm temp\.txt', 'rm')],
    }
    if task.startswith('install-') and task not in table:
        target = task.removeprefix('install-')
        package = 'nodejs' if target == 'node20' else target
        patterns = {'winget': ('winget install ' + {'ffmpeg': 'Gyan.FFmpeg', 'git': 'Git.Git', 'node20': 'OpenJS.NodeJS --version 20.18.0'}[target]),
                    'choco': 'choco install ' + ('nodejs --version=20.18.0' if target == 'node20' else package),
                    'brew': 'brew install ' + ('node@20' if target == 'node20' else package),
                    'apt': 'apt install ' + (r'nodejs=20\.[\w.+~-]+' if target == 'node20' else package),
                    'dnf': 'dnf install ' + (r'nodejs-20\.[\w.+~-]+' if target == 'node20' else package),
                    'apk': 'apk add ' + (r'nodejs=20\.[\w.+~-]+' if target == 'node20' else package)}
        table[task] = [rule(patterns[pm], pm, installs=['node' if target == 'node20' else target],
                            admin=pm in ('apt', 'dnf', 'apk', 'choco'),
                            **({'installed_versions': {'node': '20.0.0'}} if target == 'node20' else {}))]
        table[task].append(rule(('node' if target == 'node20' else target) +
                                (r' -version' if target == 'ffmpeg' else r' (?:--version|-v)' if target == 'node20' else r' --version'),
                                'node' if target == 'node20' else target,
                                **({'min_version': '20.0', 'major_version': 20} if target == 'node20' else {})))
    # These are scenario assumptions: the diagnostics catalog cannot observe these programs.
    assumed = (['Get-ChildItem', 'New-Item', 'Remove-Item', 'Write-Output', 'echo', '$env:APP_MODE',
                'Get-NetTCPConnection', 'Get-Service', 'Restart-Service', 'Invoke-WebRequest', 'icacls']
               if shell == 'powershell' else ['set', 'echo', 'dir', 'del', 'mkdir', 'netstat', 'sc', 'icacls'] if win else
               ['echo', 'export', 'mkdir', 'ls', 'rm', 'chmod', 'source', '.', 'system_profiler', 'launchctl', 'lsof'] if mac else
               ['echo', 'export', 'mkdir', 'ls', 'rm', 'chmod', 'source', '.'])
    if pid in ('ubuntu2404-nvidia', 'ubuntu2204-nosudo', 'fedora40'):
        assumed += ['ss', 'systemctl']
    return dict(shell=shell, sudo=profile['assumptions']['sudo'], assumed_programs=assumed,
                missing_programs=['sudo'] if noadmin or alpine else [], commands=table[task])


def main():
    profiles = json.loads((HERE / 'profiles/index.json').read_text())
    tasks, pairs = [], []
    for tid, prompt, categories, dependent in DEFINITIONS:
        tasks.append(dict(id=tid, prompt=prompt, categories=list(dict.fromkeys(
            ['system.os', 'system.shell'] + categories)), applies_to='all', shell_dependent=dependent,
            requirements={p['id']: requirements(tid, p) for p in profiles}))
        pairs.extend([[p['id'], tid] for p in profiles])
    random.Random(4).shuffle(pairs)
    for name, value in [('tasks.json', tasks), ('units.json', dict(seed=4, pairs=pairs))]:
        (HERE / 'tasks' / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
