"""Parse answer text as data; never execute a suggested command."""
from functools import lru_cache
import os
from pathlib import Path
import re
import shutil
import subprocess

# The script is constant. Answer bytes are read from stdin only by ParseInput.
PS_PARSE = ('$t=$null; $e=$null; $s=[Console]::In.ReadToEnd(); '
            '$null=[System.Management.Automation.Language.Parser]::ParseInput($s,[ref]$t,[ref]$e); '
            'if ($e.Count -gt 0) { exit 1 }; exit 0')


@lru_cache(maxsize=8)
def parser(shell):
    """Find a local parser without invoking Windows' WSL launch aliases."""
    candidates = ['pwsh'] if shell == 'powershell' else ['bash'] if shell == 'bash' else ['dash', 'busybox'] if shell == 'sh' else []
    for name in candidates:
        exe = shutil.which(name)
        if exe and os.name == 'nt' and ('windowsapps' in exe.lower() or
                                       Path(exe).parent.name.lower() in ('system32', 'sysnative')):
            continue
        if exe:
            return [exe, '-NoProfile', '-NonInteractive', '-Command', PS_PARSE] if name == 'pwsh' else \
                   [exe, 'sh', '-n'] if name == 'busybox' else [exe, '--noprofile', '--norc', '-n'] if name == 'bash' else [exe, '-n']
    return None


@lru_cache(maxsize=2048)
def syntax(shell, text):
    """True/False if parsed, None when no applicable parser can be used."""
    if shell == 'cmd':
        # Only these explicit forms are decided. Cmd has no parse-only API.
        if re.search(r'(?i)^(?:export |source |\$env:)', text):
            return False
        if re.fullmatch(r'(?:set [A-Za-z_]\w*=[^&|<>\r\n]*|echo [^&|<>\r\n]*|'
                        r'[A-Za-z][\w.-]*(?: [^&|<>\r\n]*)?)', text):
            return True
        return None
    if shell not in ('bash', 'sh', 'powershell'):
        return None  # bash -n is not a zsh parser.
    argv = parser(shell)
    if not argv:
        return None
    env = dict(os.environ)
    for key in ('BASH_ENV', 'ENV', 'SHELLOPTS', 'BASHOPTS', 'CDPATH'):
        env.pop(key, None)
    try:
        result = subprocess.run(argv, input=text + '\n', text=True, encoding='utf-8',
                                capture_output=True, timeout=8, env=env)
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return None
    # 0/1/2 are parser success/syntax failures; other failures are not about the answer.
    return True if result.returncode == 0 else False if result.returncode in (1, 2) else None
