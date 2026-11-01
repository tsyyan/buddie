"""Literal answer-local file evidence; no host filesystem inspection or answer execution."""
from pathlib import PurePosixPath
import re
import shlex
from executables import normalize

PREFIX = '@file:'


def path(text):
    if not re.fullmatch(r'[A-Za-z0-9_./-]+', text) or '..' in PurePosixPath(text).parts:
        return None
    normalized = str(PurePosixPath(text))
    if re.search(r'(?:^|/)path/to(?:/|$)|(?:^|/)full/path/to(?:/|$)|\.\.\.', normalized):
        return None
    return normalized if normalized not in ('.', '/') else None


def seed(requirements):
    return {PREFIX + p for name in requirements.get('provided_files', []) if (p := path(name))}


def known(name, proofs):
    canonical = path(name)
    return canonical is not None and PREFIX + canonical in proofs


def provide(text, shell, proofs):
    """Only bounded successful commands provide literal files; unfamiliar flags do not."""
    if shell not in ('bash', 'sh', 'zsh'):
        return
    name, text, _ = normalize(re.sub(r'^sudo\s+', '', text), shell)
    try:
        tokens = shlex.split(text)
    except ValueError:
        return
    args, destinations = tokens[1:], []
    if name == 'touch' and args and all(not a.startswith('-') for a in args):
        destinations = args
    elif name == 'chmod' and len(args) == 2 and re.fullmatch(r'(?:[ugoa]*[+=-][rwxX]+|[0-7]{3,4})', args[0]):
        destinations = args[1:]
    elif name == 'cp' and len(args) == 2 and all(not a.startswith('-') for a in args):
        destinations = args[1:]
    elif name == 'curl':
        valid, i, urls = True, 0, 0
        while i < len(args):
            arg = args[i]
            if arg in ('-o', '--output') and i + 1 < len(args):
                destinations.append(args[i + 1])
                i += 2
                continue
            # Common short flags can precede output (e.g. -fLo script.sh).
            if re.fullmatch(r'-[fsSL]*o', arg) and i + 1 < len(args):
                destinations.append(args[i + 1])
                i += 2
                continue
            if arg.startswith('-') and not re.fullmatch(r'-[fsSL]+', arg):
                valid = False
            elif not arg.startswith('-') and not re.match(r'https?://', arg):
                valid = False
            elif re.match(r'https?://', arg):
                urls += 1
            i += 1
        if not valid or urls != 1 or len(destinations) != 1:
            destinations = []
    for destination in destinations:
        if canonical := path(destination):
            proofs.add(PREFIX + canonical)
