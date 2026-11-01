"""Serialize human-labelled examples; expectations do not come from the judge."""
import json
from pathlib import Path

# profile, task, shell, fitting command, broken command, literal broken reason
PAIRS = [
    ('win11-pwsh-nvidia', 'python-version', 'powershell', 'py -3.12 --version',
     'python3 --version', 'program_missing'),
    ('win11-cmd-nogpu', 'python-version', 'cmd', 'python --version',
     'py -3.12 --version', 'program_missing'),
    ('macos-arm', 'gpu-check', 'zsh', 'system_profiler SPDisplaysDataType',
     'nvidia-smi', 'wrong_os'),
    ('ubuntu2404-nvidia', 'python-venv', 'bash', 'python3 -m venv .venv',
     'conda create -n project python=3.12', 'program_missing'),
    ('ubuntu2204-nosudo', 'python-version', 'bash', 'python3 --version',
     'conda --version', 'program_missing'),
    ('wsl-ubuntu', 'pytorch-gpu', 'bash',
     'python3 -m pip install torch --index-url https://download.pytorch.org/whl/cu122',
     'python3 -m pip install torch --index-url https://download.pytorch.org/whl/cu124', 'version_mismatch'),
    ('fedora40', 'container-version', 'bash', 'podman --version',
     'docker --version', 'program_missing'),
    ('alpine-container', 'session-variable', 'sh', 'export APP_MODE=development',
     '$env:APP_MODE="development"', 'wrong_shell_syntax'),
    ('win11-cmd-nogpu', 'session-variable', 'cmd', 'set APP_MODE=development',
     'export APP_MODE=development', 'wrong_shell_syntax'),
    ('win11-pwsh-nvidia', 'download-file', 'powershell',
     'curl.exe -o data.txt https://example.org/data.txt',
     'wget -O data.txt https://example.org/data.txt', 'program_missing'),
    ('ubuntu2204-nosudo', 'install-git', 'bash', 'git --version',
     'sudo apt install git', 'needs_admin'),
    ('ubuntu2404-nvidia', 'archive-create', 'bash', 'tar -czf data.tar.gz data',
     'wget --help', 'program_missing'),
    ('ubuntu2404-nvidia', 'service-restart', 'bash', 'sudo systemctl restart ssh',
     'systemctl restart ssh', 'needs_admin'),
    ('fedora40', 'install-ffmpeg', 'bash', 'sudo dnf install ffmpeg\nffmpeg -version',
     'ffmpeg -version', 'program_missing'),
    ('macos-arm', 'session-variable', 'zsh', 'export APP_MODE=development',
     '$env:APP_MODE="development"', 'wrong_shell_syntax'),
    ('win11-pwsh-nvidia', 'session-variable', 'powershell', '$env:APP_MODE="development"',
     'export APP_MODE=development', 'wrong_shell_syntax'),
]


def expected(status, *commands):
    return dict(status=status, commands=[dict(status=s, reason=r) for s, r in commands])


def main():
    rows = []
    for n, (pid, tid, shell, good, bad, reason) in enumerate(PAIRS, 1):
        fit = expected('OK', ('FITS', None))
        no_parser = expected('UNDECIDED', ('UNKNOWN', None))
        if n == 14:
            fit = expected('OK', ('INSTALLS', None), ('FITS', None))
            no_parser = expected('BROKEN', ('UNKNOWN', None), ('WONT_RUN', 'program_missing'))
        rows.append(dict(id=f'{n:02}-fitting', profile=pid, task=tid, kind='fitting',
                         answer=f'Run these commands:\n```{shell}\n{good}\n```',
                         expected=fit, parser=shell, parser_probe='echo ok' if shell != 'powershell' else 'Write-Output ok',
                         without_parser=no_parser))
        rows.append(dict(id=f'{n:02}-broken', profile=pid, task=tid, kind='broken',
                         answer=f'Run:\n```{shell}\n{bad}\n```',
                         expected=expected('BROKEN', ('WONT_RUN', reason))))
        rows.append(dict(id=f'{n:02}-question', profile=pid, task=tid, kind='question',
                         answer='Which operating system and shell are you using, and what Python version is installed?',
                         expected=expected('ASKED')))
    extras = [
        ('bash-for-powershell', 'win11-pwsh-nvidia', 'session-variable',
         '```bash\nexport APP_MODE=development\n```', expected('BROKEN', ('WONT_RUN', 'wrong_shell_syntax'))),
        ('bash-for-ash', 'alpine-container', 'session-variable',
         '```bash\nexport APP_MODE=development\n```', expected('BROKEN', ('WONT_RUN', 'wrong_shell_syntax'))),
        ('missing-venv-module', 'ubuntu2204-nosudo', 'python-venv',
         '```bash\npython3 -m venv .venv\n```', expected('BROKEN', ('WONT_RUN', 'program_missing'))),
        ('explanation-only', 'win11-cmd-nogpu', 'python-version',
         'Python is a programming language.', expected('NO_COMMANDS')),
        ('not-environment-question', 'macos-arm', 'gpu-check',
         'Would you like me to help?', expected('NO_COMMANDS')),
        ('unknown-flags', 'win11-cmd-nogpu', 'python-version',
         '```cmd\npython --imaginary\n```', expected('UNDECIDED', ('UNKNOWN', None))),
        ('installer-not-elevated', 'win11-cmd-nogpu', 'install-ffmpeg',
         '```cmd\nchoco install ffmpeg\nffmpeg -version\n```',
         expected('BROKEN', ('WONT_RUN', 'needs_admin'), ('WONT_RUN', 'program_missing'))),
    ]
    for cid, pid, tid, answer, want in extras:
        rows.append(dict(id=cid, profile=pid, task=tid, kind='tricky', answer=answer, expected=want))
    # A bash fence is a POSIX-family hint, not a demand that Alpine run bash itself.
    ash = next(r for r in rows if r['id'] == 'bash-for-ash')
    ash.update(expected=expected('OK', ('FITS', None)), parser='sh', parser_probe='echo ok',
               without_parser=expected('UNDECIDED', ('UNKNOWN', None)))
    for cid, pid, tid, text, target in [
            ('bash-on-macos', 'macos-arm', 'list-files', 'ls -la', 'zsh'),
            ('bash-on-alpine', 'alpine-container', 'make-directory', 'mkdir -p output', 'sh')]:
        rows.append(dict(id=cid, profile=pid, task=tid, kind='tricky', answer=f'```bash\n{text}\n```',
                         expected=expected('OK', ('FITS', None)), parser=target, parser_probe='echo ok',
                         without_parser=expected('UNDECIDED', ('UNKNOWN', None))))
    for cid, pid, tag, text in [
            ('alpine-double-brackets', 'alpine-container', 'bash', '[[ -d output ]]'),
            ('alpine-array', 'alpine-container', 'bash', 'items=(one two)')]:
        rows.append(dict(id=cid, profile=pid, task='list-files', kind='tricky',
                         answer=f'```{tag}\n{text}\n```',
                         expected=expected('BROKEN', ('WONT_RUN', 'wrong_shell_syntax'))))
    # PROTOCOL v1 (owner, 2026-11-01): Windows PowerShell is on this machine, so a PowerShell block is no wrong shell;
    # the task has no PowerShell requirements for it yet, so the command is undecided
    rows.append(dict(id='powershell-on-cmd', profile='win11-cmd-nogpu', task='list-files', kind='tricky',
                     answer='```powershell\nGet-ChildItem\n```', expected=expected('UNDECIDED', ('UNKNOWN', None))))
    # Literal expectations for parent and recursively evaluated child commands.
    list_cases = [
        ('list-posix', 'ubuntu2404-nvidia', 'list-files', 'bash',
         'ls && mkdir output; rm -f temp.txt', 'FITS', None, ['FITS'] * 3),
        ('list-powershell', 'win11-pwsh-nvidia', 'list-files', 'powershell',
         'Get-ChildItem; Get-Location', 'FITS', None, ['FITS'] * 2),
        ('venv-and-source', 'ubuntu2404-nvidia', 'python-venv', 'bash',
         'python3 -m venv .venv &&\nsource .venv/bin/activate', 'FITS', None, ['FITS'] * 2),
        ('venv-and-dot', 'alpine-container', 'python-venv', 'sh',
         'python3 -m venv .venv; . .venv/bin/activate', 'FITS', None, ['FITS'] * 2),
        ('venv-source-zsh', 'macos-arm', 'python-venv', 'zsh',
         'python3 -m venv .venv && source .venv/bin/activate', 'FITS', None, ['FITS'] * 2),
        ('list-broken-and-unknown', 'ubuntu2404-nvidia', 'list-files', 'bash',
         'ls; python3 --imaginary; conda --version', 'WONT_RUN', 'program_missing', ['FITS', 'UNKNOWN', 'WONT_RUN']),
        ('control-if', 'alpine-container', 'list-files', 'sh',
         'if [ -d output ]; then ls; else mkdir output; fi', 'FITS', None, ['FITS'] * 3),
        ('control-for', 'alpine-container', 'list-files', 'sh',
         'for item in one two; do ls && mkdir output; done', 'FITS', None, ['FITS'] * 2),
        ('control-while', 'alpine-container', 'list-files', 'sh',
         'while false; do ls; done', 'FITS', None, ['FITS'] * 2),
        ('control-case', 'alpine-container', 'list-files', 'sh',
         'case value in value) ls ;; other) conda --version ;; esac', 'WONT_RUN', 'program_missing', ['FITS', 'WONT_RUN']),
        ('control-unknown', 'alpine-container', 'list-files', 'sh',
         'if true; then python3 --imaginary; fi', 'UNKNOWN', None, ['FITS', 'UNKNOWN']),
        ('control-dynamic-pattern', 'alpine-container', 'list-files', 'sh',
         'case value in `conda --version`) ls ;; esac', 'UNKNOWN', None, ['FITS', 'UNKNOWN']),
        ('venv-removed', 'ubuntu2404-nvidia', 'python-venv', 'bash',
         'python3 -m venv .venv; rm -f .venv/bin/activate; source .venv/bin/activate',
         'UNKNOWN', None, ['FITS', 'FITS', 'UNKNOWN']),
        ('multiline-literal', 'ubuntu2404-nvidia', 'list-files', 'bash',
         'echo "first\nconda --version\nlast"', 'UNKNOWN', None, ['UNKNOWN']),
        ('venv-failed-before-source', 'ubuntu2204-nosudo', 'python-venv', 'bash',
         'python3 -m venv .venv && source .venv/bin/activate', 'WONT_RUN', 'program_missing', ['WONT_RUN', 'UNKNOWN']),
        ('control-branch-state', 'alpine-container', 'python-venv', 'sh',
         'if true; then python3 -m venv .venv; . .venv/bin/activate; else . .venv/bin/activate; fi',
         'UNKNOWN', None, ['FITS', 'FITS', 'FITS', 'UNKNOWN']),
    ]
    for cid, pid, tid, shell, text, verdict, reason, leaves in list_cases:
        status = 'BROKEN' if verdict == 'WONT_RUN' else 'UNDECIDED' if verdict == 'UNKNOWN' else 'OK'
        no_parser = expected('BROKEN', ('WONT_RUN', reason)) if verdict == 'WONT_RUN' else expected('UNDECIDED', ('UNKNOWN', None))
        rows.append(dict(id=cid, profile=pid, task=tid, kind='lists-control',
                         answer=f'```{shell}\n{text}\n```', expected=expected(status, (verdict, reason)),
                         parser=shell, parser_probe='Write-Output ok' if shell == 'powershell' else 'echo ok',
                         without_parser=no_parser, expected_leaf_statuses=leaves))
    Path(__file__).with_name('answers.json').write_text(json.dumps(rows, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
