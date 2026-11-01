"""Recognize literal venv creation/activation without touching the filesystem."""
from pathlib import PurePosixPath
import re
from shell_lists import lex


def directory(text):
    if not re.fullmatch(r'(?:\./)?[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', text):
        return None
    if '..' in PurePosixPath(text).parts:
        return None
    return str(PurePosixPath(text))


def activation(tokens):
    if len(tokens) == 2 and tokens[0] in ('source', '.') and tokens[1].endswith('/bin/activate'):
        return directory(tokens[1][:-len('/bin/activate')])
    return None


def rule(tokens, shell):
    args = tokens[1:]
    if tokens[0] == 'py' and args and re.fullmatch(r'-\d+\.\d+', args[0]):
        args = args[1:]
    if re.fullmatch(r'python(?:3(?:\.\d+)?)?|py', tokens[0]) and len(args) == 3 and args[:2] == ['-m', 'venv']:
        if path := directory(args[2]):
            return dict(program=tokens[0], effect='FITS', python_module='venv', creates_venv=path)
    if shell in ('bash', 'sh', 'zsh') and (path := activation(tokens)):
        return dict(program=tokens[0], effect='FITS', activates_venv=path, requires_path=True)
    return None


def invalidate(text, shell, venvs):
    """Modeled removal, relocation or overwriting invalidates activation-script proofs."""
    import shlex
    try:
        tokens = shlex.split(text, posix=shell in ('bash', 'sh', 'zsh'))
    except ValueError:
        venvs.clear()
        return
    if tokens and tokens[0] == 'sudo':
        tokens = tokens[1:]
    if not tokens:
        return
    name, args = tokens[0].lower(), tokens[1:]
    operands = [a for a in args if not a.startswith('-')]
    if name in ('rm', 'rmdir', 'remove-item', 'del'):
        affected = operands
    elif name in ('mv', 'move-item'):
        affected = operands
    elif name in ('cp', 'copy-item'):
        affected = operands[-1:]
    else:
        return
    for path in affected:
        path = path.replace('\\', '/').strip('"\'')
        if '..' in PurePosixPath(path).parts:
            venvs.clear()
            return
        path = str(PurePosixPath(path))
        for root in set(venvs):
            script = root + '/bin/activate'
            if path == script or root == path or script.startswith(path.rstrip('/') + '/'):
                venvs.discard(root)


def parser_text(text, shell):
    """zsh's source builtin has the same syntax as dot for this literal activation subset."""
    if shell != 'zsh':
        return text
    tokens = lex(text, shell)
    replacements = []
    for i, token in enumerate(tokens[:-1]):
        prior = tokens[i - 1].text if i else ';'
        if token.text == 'source' and prior in (';', '\n', '&&', '||', 'then', 'else', 'do'):
            if activation(['source', tokens[i + 1].text]):
                replacements.append((token.start, token.end))
    for start, end in reversed(replacements):
        text = text[:start] + '.' + text[end:]
    return text
