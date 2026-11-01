"""Resolve command identity without consulting or executing host filesystem paths."""
import re


def normalize(text, shell):
    """Return (program, rule text, supplied path); keep original bytes for syntax/output."""
    stripped = text.lstrip()
    if shell == 'powershell' and stripped.startswith('& '):
        stripped = stripped[1:].lstrip()
    match = re.match(r'''(?:"[^"]*"|'[^']*'|[^\s]+)''', stripped)
    if not match:
        return '', text, None
    raw = match[0]
    token = raw[1:-1] if len(raw) >= 2 and raw[0] in ('"', "'") and raw[-1] == raw[0] else raw
    windows = bool(re.match(r'^[A-Za-z]:[/\\]|^\\\\', token))
    absolute = windows or token.startswith('/')
    path = token if absolute or token.startswith(('./', '../', '.\\', '..\\')) else None
    name = re.split(r'[/\\]', token)[-1] if absolute else token
    if windows:
        name = name.lower()
    if name.lower().endswith('.exe'):
        name = name[:-4]
    return name, name + stripped[match.end():], path


# Selected conventional cmdlet verbs from the official approved-verb list:
# https://learn.microsoft.com/powershell/scripting/developer/cmdlet/approved-verbs-for-windows-powershell-commands
# Do not treat every hyphenated POSIX tool name (nvidia-smi, apt-get) as a cmdlet.
CMDLET_VERBS = frozenset('Get Set Write Read New Remove Select Where Format Out Start Stop Restart Test Invoke Add Clear Copy Move Join Split Convert ConvertTo ConvertFrom Measure ForEach Export Import Enable Disable'.lower().split())


def cmdlet(name):
    parts = name.split('-', 1)
    return len(parts) == 2 and parts[0].lower() in CMDLET_VERBS and bool(re.fullmatch(r'[A-Za-z][A-Za-z0-9]*', parts[1]))
