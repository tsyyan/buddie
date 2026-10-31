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
        no_parser = expected('OK', ('UNKNOWN', None))
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
         '```cmd\npython --imaginary\n```', expected('OK', ('UNKNOWN', None))),
        ('installer-not-elevated', 'win11-cmd-nogpu', 'install-ffmpeg',
         '```cmd\nchoco install ffmpeg\nffmpeg -version\n```',
         expected('BROKEN', ('WONT_RUN', 'needs_admin'), ('WONT_RUN', 'program_missing'))),
    ]
    for cid, pid, tid, answer, want in extras:
        rows.append(dict(id=cid, profile=pid, task=tid, kind='tricky', answer=answer, expected=want))
    # A bash fence is a POSIX-family hint, not a demand that Alpine run bash itself.
    ash = next(r for r in rows if r['id'] == 'bash-for-ash')
    ash.update(expected=expected('OK', ('FITS', None)), parser='sh', parser_probe='echo ok',
               without_parser=expected('OK', ('UNKNOWN', None)))
    Path(__file__).with_name('answers.json').write_text(json.dumps(rows, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
