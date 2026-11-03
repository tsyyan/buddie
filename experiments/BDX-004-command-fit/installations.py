"""Literal installation intent; packages are evidence of an attempt, not of success."""
import re
import shlex
from facts import python_args
from executables import normalize as normalize_executable

ALIASES = {'nodejs': 'node', 'node@20': 'node', 'git.git': 'git',
           'gyan.ffmpeg': 'ffmpeg', 'openjs.nodejs': 'node', 'openjs.nodejs.lts': 'node',
           'docker.io': 'docker', 'docker-ce': 'docker', 'docker-ce-cli': 'docker',
           'docker-desktop': 'docker', 'docker.dockerdesktop': 'docker', 'moby-cli': 'docker'}
MANAGERS = {'apt', 'apt-get', 'dnf', 'apk', 'brew', 'winget', 'choco', 'pip', 'pip3', 'npm', 'conda'}


def intent(text, shell):
    try:
        invocation = re.sub(r'^\s*&(?!&)\s*', '', text) if shell == 'powershell' else text
        tokens = shlex.split(invocation, posix=shell in ('bash', 'sh', 'zsh'))
    except ValueError:
        return None
    if tokens[:1] == ['sudo']:
        tokens = tokens[1:]
    if not tokens:
        return None
    normalized_name, _, _ = normalize_executable(re.sub(r'^sudo\s+', '', text), shell)
    tokens[0] = normalized_name
    if re.fullmatch(r'python(?:3(?:\.\d+)?)?|py', tokens[0]):
        args = python_args(tokens)
        if args[:2] != ['-m', 'pip']:
            return None
        tokens = ['pip'] + args[2:]
    manager = tokens[0].lower()
    if manager == 'nvm' and len(tokens) >= 3 and tokens[1] == 'install':
        return dict(manager='nvm', installs=['node', 'npm'], needs_admin=False)
    if manager not in MANAGERS:
        return None
    action = next((i for i, t in enumerate(tokens[1:], 1) if t in ('install', 'add')), None)
    if action is None or tokens[action] == 'add' and manager != 'apk':
        return None
    packages, skip = [], False
    for token in tokens[action + 1:]:
        if skip:
            skip = False
            continue
        if token.startswith('-'):
            # --id is winget's package operand; the other options below take values.
            skip = token in ('--version', '--prefix', '--target', '-t', '-r', '--requirement',
                             '--index-url', '--extra-index-url', '-i', '-n', '--name', '-c', '--channel')
            continue
        if not re.fullmatch(r'[A-Za-z0-9_.@+-]+(?:[=<>!~]+[A-Za-z0-9_.+-]+)?', token):
            continue
        package = re.split(r'[=<>!~]', token)[0]
        package = ALIASES.get(package.lower(), package)
        if '@' in package:
            package = package.split('@')[0]
        packages.append(package)
        if package == 'node':
            packages.append('npm')  # Node distributions bundle npm; success remains unproved.
    return dict(manager=manager, installs=packages,
                needs_admin=manager in ('apt', 'apt-get', 'dnf', 'apk', 'choco')) if packages else None


def uncertain(installed, names):
    for name in names:
        installed.setdefault(name, {'pending': True})


def pending(installed):
    return {name: v for name, v in installed.items() if isinstance(v, dict) and v.get('pending')}
