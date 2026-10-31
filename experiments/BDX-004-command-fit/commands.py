"""Extract likely runnable Markdown, retaining shell and answer order."""
import re

LANGUAGES = {'bash': 'bash', 'sh': 'sh', 'zsh': 'zsh', 'powershell': 'powershell',
             'pwsh': 'powershell', 'ps1': 'powershell', 'cmd': 'cmd', 'bat': 'cmd',
             'console': 'unknown', 'shell': 'unknown', '': 'unknown'}
PROGRAMS = set(('python python3 py pip pip3 uv conda pipx node npm npx git curl curl.exe wget '
                'tar unzip zip ffmpeg nvidia-smi nvcc apt apt-get dnf apk brew winget choco '
                'sudo docker podman bash sh zsh pwsh powershell cmd env export set echo source . '
                'chmod chown ls dir mkdir rm del cd cp mv touch cat type printf ss lsof netstat '
                'systemctl service rc-service sc launchctl icacls uname make cmake gcc '
                'Get-ChildItem New-Item Remove-Item Write-Output Get-NetTCPConnection '
                'Get-Service Restart-Service Invoke-WebRequest system_profiler').lower().split())
PROMPT = re.compile(r'^(?:\$\s+|PS(?:\s+[^>\n]*)?>\s*|[A-Za-z]:\\[^>\n]*>\s*)')
FENCE = re.compile(r'^\s{0,3}(`{3,}|~{3,})\s*([^\s`]*)\s*$')


def uncomment(line, shell):
    """Remove shell comments without damaging quoted hashes or URL fragments."""
    if re.match(r'(?i)^(?:rem\b|::)', line):
        return ''
    quote, escaped = None, False
    for i, char in enumerate(line):
        if escaped:
            escaped = False
        elif char in ('`', '\\') and quote != "'":
            escaped = True
        elif quote:
            if char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == '#' and shell != 'cmd' and (i == 0 or line[i - 1].isspace()):
            return line[:i].rstrip()
    return line.rstrip()


def starts_program(line):
    """A bounded vocabulary filters prose/output; unknown programs with flags survive."""
    if not line:
        return False
    if re.match(r'(?i)^(?:(?:git|docker|podman|ffmpeg) version |Python \d|'
                r'curl \d+\.\d+[^ ]* \(|pip \d+\.\d+[^ ]* from |'
                r'Successfully |Requirement already |Collecting |Downloading )', line):
        return False
    if line.startswith('& '):
        return starts_program(line[2:].lstrip())
    assignment = re.match(r'^[A-Za-z_]\w*=(?:"[^"\n]*"|\x27[^\x27\n]*\x27|[^\s]+)\s+(.+)$', line)
    if assignment:
        return starts_program(assignment[1])
    quoted = re.match(r'^("[^"\n]+"|\x27[^\x27\n]+\x27)(?:\s|$)', line)
    if quoted:
        executable = quoted[1][1:-1]
        return (executable.lower() in PROGRAMS or
                re.match(r'^(?:\.?\.?[/\\]|[A-Za-z]:[/\\])', executable) is not None)
    first = line.split()[0]
    return (first.lower() in PROGRAMS or re.match(r'^python3\.\d+$', first) is not None or
            re.match(r'^\$env:\w+\s*=', line, re.I) is not None or
            re.match(r'^(?:\.?\.?[/\\]|[A-Za-z]:[/\\])\S+', first) is not None or
            re.match(r'^[a-z][\w.+-]*\s+--?[\w]', line) is not None)


def block_commands(lines, shell):
    """Join physical continuations before deciding whether a line is command or output."""
    pending = ''
    for physical in lines:
        prompted = PROMPT.match(physical.strip())
        line = PROMPT.sub('', physical.strip())
        line = uncomment(line, shell)
        if not line:
            continue
        marker = '^' if shell == 'cmd' else '`' if shell == 'powershell' else '\\'
        trailing = len(line) - len(line.rstrip(marker))
        continued = trailing % 2 == 1
        pending += line[:-1].rstrip() + ' ' if continued else line
        if continued:
            continue
        if prompted or starts_program(pending):
            yield {'text': pending.strip(), 'shell': shell}
        pending = ''
    if pending and starts_program(pending):
        yield {'text': pending.strip(), 'shell': shell}


def extract(answer):
    """Return {'text', 'shell'} rows; extraction never runs answer text."""
    out, opened, lines, language = [], None, [], ''
    for line in answer.splitlines():
        fence = FENCE.match(line)
        if opened:
            if fence and fence[1][0] == opened[0] and len(fence[1]) >= len(opened) and not fence[2]:
                if language in LANGUAGES:
                    out.extend(block_commands(lines, LANGUAGES[language]))
                opened, lines = None, []
            else:
                lines.append(line)
        elif fence:
            opened, language = fence[1], fence[2].lower()
        else:
            for match in re.finditer(r'(?<!`)(`+)([^`\n]+)\1(?!`)', line):
                candidate = PROMPT.sub('', match[2].strip())
                if starts_program(candidate):
                    out.append({'text': candidate, 'shell': 'unknown'})
    if opened and language in LANGUAGES:
        out.extend(block_commands(lines, LANGUAGES[language]))
    return out
