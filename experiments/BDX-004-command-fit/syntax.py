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


def family(shell):
    return 'posix' if shell in ('bash', 'sh', 'zsh', 'shell', 'console', 'posix') else shell


def non_posix(text):
    """dash -n accepts [[ as a command name, so explicitly reject these extensions too."""
    plain, quote, escaped = [], None, False
    for char in text:
        if escaped:
            plain.append(' ')
            escaped = False
        elif char == '\\' and quote != "'":
            plain.append(' ')
            escaped = True
        elif quote:
            plain.append(' ')
            if char == quote:
                quote = None
        elif char in ('"', "'"):
            plain.append(' ')
            quote = char
        else:
            plain.append(char)
    return bool(re.search(r'(?:^|[;\n])\s*(?:\[\[\s|source\s|[A-Za-z_]\w*=\()', ''.join(plain)))


@lru_cache(maxsize=8)
def parser(shell):
    """Find a local parser without invoking Windows' WSL launch aliases."""
    candidates = ['pwsh'] if shell == 'powershell' else ['bash'] if shell == 'bash' else ['dash'] if shell in ('sh', 'zsh') else []
    for name in candidates:
        exe = shutil.which(name)
        if exe and os.name == 'nt' and ('windowsapps' in exe.lower() or
                                       Path(exe).parent.name.lower() in ('system32', 'sysnative')):
            continue
        if exe:
            return [exe, '-NoProfile', '-NonInteractive', '-Command', PS_PARSE] if name == 'pwsh' else \
                   [exe, '--noprofile', '--norc', '-n'] if name == 'bash' else [exe, '-n']
    return None


@lru_cache(maxsize=2048)
def syntax(shell, text):
    """True/False if parsed, None when no applicable parser can be used."""
    if shell == 'cmd':
        if re.fullmatch(r'(?:\.\\)?[\w.-]+\\Scripts\\activate(?:\.bat)?', text, re.I):
            return True
        # Only these explicit forms are decided. Cmd has no parse-only API.
        if re.search(r'(?i)^(?:export |source |\$env:)', text):
            return False
        if re.fullmatch(r'(?:set [A-Za-z_]\w*=[^&|<>\r\n]*|echo [^&|<>\r\n]*|'
                        r'[A-Za-z][\w.-]*(?: [^&|<>\r\n]*)?)', text):
            return True
        return None
    if shell in ('sh', 'zsh') and non_posix(text):
        return False if shell == 'sh' else None
    if shell not in ('bash', 'sh', 'zsh', 'powershell'):
        return None
    argv = parser(shell)
    if not argv:
        return None
    env = dict(os.environ)
    for key in ('BASH_ENV', 'ENV', 'SHELLOPTS', 'BASHOPTS', 'CDPATH'):
        env.pop(key, None)
    try:
        # Binary stdin preserves LF: Windows text-mode CRLF turns fi into the word fi\r for dash.
        result = subprocess.run(argv, input=(text + '\n').encode('utf-8'),
                                capture_output=True, timeout=8, env=env)
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return None
    # 0/1/2 are parser success/syntax failures; other failures are not about the answer.
    return True if result.returncode == 0 else False if shell != 'zsh' and result.returncode in (1, 2) else None
