"""Extract likely runnable Markdown, retaining shell and answer order."""
import re
import shlex
from base_commands import BASE_NAMES
from control import complete as control_complete, has_control
from shell_lists import lex

LANGUAGES = {'bash': 'bash', 'sh': 'sh', 'zsh': 'zsh', 'fish': 'fish', 'csh': 'csh', 'powershell': 'powershell',
             'pwsh': 'powershell', 'ps1': 'powershell', 'cmd': 'cmd', 'bat': 'cmd',
             'console': 'posix', 'shell': 'posix', '': 'unknown'}
PROGRAMS = set(('python python3 py pip pip3 uv conda pipx node npm npx git curl curl.exe wget '
                'tar unzip zip ffmpeg nvidia-smi nvcc apt apt-get dnf apk brew winget choco '
                'sudo docker podman bash sh zsh pwsh powershell cmd env export set echo source . '
                'chmod chown ls dir mkdir rm del cd cp mv touch cat type printf ss lsof netstat '
                'systemctl service rc-service sc launchctl icacls uname make cmake gcc '
                'Get-ChildItem New-Item Remove-Item Write-Output Get-NetTCPConnection '
                'Get-Service Restart-Service Invoke-WebRequest system_profiler').lower().split())
PROGRAMS.update(BASE_NAMES)
PROGRAMS.add('nvm')
PROMPT = re.compile(r'^(?:\$\s+|PS(?:\s+[^>\n]*)?>\s*|[A-Za-z]:\\[^>\n]*>\s*)')
FENCE = re.compile(r'^\s{0,3}(`{3,}|~{3,})\s*([^\s`]*)\s*$')


def uncomment(line, shell):
    """Remove shell comments without damaging quoted hashes or URL fragments."""
    if re.match(r'(?i)^(?:rem\b|::)', line):
        return ''
    quote, escaped, out, i = None, False, [], 0
    while i < len(line):
        char = line[i]
        if escaped:
            escaped = False
        elif char == ('`' if shell == 'powershell' else '\\') and quote != "'":
            escaped = True
        elif quote:
            if char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == '#' and shell != 'cmd' and (i == 0 or line[i - 1].isspace()):
            end = line.find('\n', i)
            if end < 0:
                break
            i = end
            continue
        out.append(char)
        i += 1
    return ''.join(out).rstrip()


def starts_program(line):
    """A bounded vocabulary filters prose/output; unknown programs with flags survive."""
    if not line:
        return False
    if re.fullmatch(r'(?:\.\\)?[\w.-]+\\Scripts\\activate(?:\.bat|\.ps1)?', line, re.I):
        return True
    if re.match(r'(?i)^(?:(?:git|docker|podman|ffmpeg) version |Python \d|'
                r'curl \d+\.\d+[^ ]* \(|pip \d+\.\d+[^ ]* from |'
                r'Successfully |Requirement already |Collecting |Downloading )', line):
        return False
    if line.startswith('& '):
        return starts_program(line[2:].lstrip())
    if has_control(line):
        return True
    if re.match(r'^(?:\[\[\s|[A-Za-z_]\w*=\()', line):
        return True  # Keep shell constructs so incompatible profiles can reject them.
    assignment = re.match(r'^[A-Za-z_]\w*=(?:"[^"\n]*"|\x27[^\x27\n]*\x27|[^\s]+)\s+(.+)$', line)
    if assignment:
        return starts_program(assignment[1])
    quoted = re.match(r'^("[^"\n]+"|\x27[^\x27\n]+\x27)(?:\s|$)', line)
    if quoted:
        executable = quoted[1][1:-1]
        return (executable.lower() in PROGRAMS or
                re.match(r'^(?:\.?\.?[/\\]|[A-Za-z]:[/\\])', executable) is not None)
    first = re.split(r'[;&|]', line.split()[0], maxsplit=1)[0]
    return (first.lower() in PROGRAMS or re.match(r'^python3\.\d+$', first) is not None or
            re.match(r'^\$env:\w+\s*=', line, re.I) is not None or
            re.match(r'^(?:\.?\.?[/\\]|[A-Za-z]:[/\\])\S+', first) is not None or
            re.match(r'^[A-Za-z][\w.+-]*\s+--?[\w]', line) is not None)


def block_commands(lines, shell):
    """Join physical continuations before deciding whether a line is command or output."""
    pending, structure, quote_open, join_newline = '', '', False, False
    for physical in lines:
        prompted = None if quote_open else PROMPT.match(physical.strip())
        raw = physical.rstrip() if quote_open else PROMPT.sub('', physical.strip())
        line = uncomment(pending + ('\n' if join_newline else '') + raw, shell)
        pending, join_newline = '', False
        if not line:
            continue
        tokens = lex(line, shell)
        quote_open = bool(tokens and not tokens[-1].closed)
        if quote_open:
            pending, join_newline = line, True
            continue
        marker = '^' if shell == 'cmd' else '`' if shell == 'powershell' else '\\'
        trailing = len(line) - len(line.rstrip(marker))
        continued = trailing % 2 == 1
        if continued:
            pending = line[:-1].rstrip() + ' '
            continue
        if shell != 'cmd' and tokens and tokens[-1].operator and tokens[-1].text in ('&&', '||', '|'):
            pending, join_newline = line, True
            continue
        pending = line
        if structure or (shell in ('bash', 'sh', 'zsh', 'posix', 'unknown') and has_control(pending)):
            structure += ('\n' if structure else '') + pending
            pending = ''
            if control_complete(structure):
                yield {'text': structure, 'shell': shell}
                structure = ''
            continue
        if prompted or starts_program(pending):
            yield {'text': pending.strip(), 'shell': shell}
        pending = ''
    if structure:
        if pending:
            structure += '\n' + pending
        yield {'text': structure, 'shell': shell}
    elif pending and starts_program(pending):
        yield {'text': pending.strip(), 'shell': shell}


def inline_command(candidate, prefix):
    """Inline references need an invocation, not merely a familiar tool or path name."""
    if re.search(r"(?i)\b(?:do not|don't|never)\s+(?:run|type|execute)\b[^.!?]*$", prefix):
        return False
    instructed = bool(re.search(r'(?i)\b(?:run|type|execute)(?:\s+(?:the|this|following|command|commands))*\s*:?\s*$', prefix))
    try:
        tokens = shlex.split(candidate, posix=False)
    except ValueError:
        return instructed
    if not tokens:
        return False
    first = tokens[0].strip('"\'')
    if instructed:
        return bool(re.match(r'^(?:\.{0,2}[/\\]|[A-Za-z]:[/\\]|[A-Za-z_][\w.+-]*(?:$|\s))', first))
    if not starts_program(candidate):
        return False
    if '/' in first or '\\' in first:
        name = re.split(r'[/\\]', first)[-1].lower()
        if name not in PROGRAMS and not re.search(r'\.(?:exe|bat|cmd|ps1|sh)$', name):
            return False
    return instructed or len(tokens) >= 2


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
                if inline_command(candidate, line[:match.start()]):
                    out.append({'text': candidate, 'shell': 'unknown'})
    if opened and language in LANGUAGES:
        out.extend(block_commands(lines, LANGUAGES[language]))
    return out


def table_cells(line):
    """Markdown delimiters outside backtick spans; pipeline bars stay inside cells."""
    if not line.lstrip().startswith('|'):
        return None
    cells, start, fence, i = [], 0, '', 0
    while i < len(line):
        if line[i] == '`':
            end = i + 1
            while end < len(line) and line[end] == '`':
                end += 1
            mark = line[i:end]
            fence = '' if fence == mark else mark if not fence else fence
            i = end
            continue
        if line[i] == '|' and not fence and (not i or line[i - 1] != '\\'):
            cells.append(line[start:i].strip())
            start = i + 1
        i += 1
    cells.append(line[start:].strip())
    return cells[1:-1] if not cells[-1] else cells[1:]


def inline_rows(line, force=False):
    """Retain a local trailing audience label for the surrounding section parser."""
    for match in re.finditer(r'(?<!`)(`+)([^`\n]+)\1(?!`)', line):
        candidate = PROMPT.sub('', match[2].strip())
        if inline_command(candidate, line[:match.start()]) or force and (starts_program(candidate) or re.match(r'^[A-Za-z_][\w.-]*(?:\s|$)', candidate)):
            suffix = re.match(r'\s*\(([^)]+)\)', line[match.end():])
            yield dict(text=candidate, shell='unknown', audience=suffix[1] if suffix else None)
