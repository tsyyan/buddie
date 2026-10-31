"""Conservative, model-free command fit judge; no suggested command is executed."""
import argparse
import json
from pathlib import Path
import re
import shlex

from commands import extract
from base_commands import rule as base_rule
from facts import observation, program, python_facts, value, version
from syntax import family, non_posix, syntax
from tool import HERE, load_profile


def load_task(task):
    if isinstance(task, dict):
        return task
    tasks = json.loads((HERE / 'tasks/tasks.json').read_text(encoding='utf-8'))
    found = next((t for t in tasks if t['id'] == task), None)
    if found is None:
        raise ValueError('unknown task')
    return found


def wrong_syntax(text, shell, profile):
    """Recognize cross-shell idioms even when the relevant parser is absent."""
    if shell in ('powershell', 'cmd') and re.match(r'^(?:export |source |\.[ ]+)', text):
        return True
    if shell != 'powershell' and re.match(r'\$env:', text, re.I):
        return True
    if shell in ('bash', 'sh', 'zsh') and re.match(r'set \w+=', text, re.I):
        return True
    if shell == 'sh' and non_posix(text):
        return True
    # Windows PowerShell 5.1 cannot parse PowerShell 7 pipeline-chain operators.
    if shell == 'powershell' and value(profile, 'system.shell', 'pwsh') is None and ('&&' in text or '||' in text):
        return True
    return False


def simple(text):
    """Reject compounds, redirection and expansions before applying positive rules."""
    quote = None
    for char in text:
        if quote:
            if char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char in ';&|<>`(){}':
            return False
    return quote is None and '$(' not in text


def judge_command(command, profile, req, installed):
    text, hint, target = command['text'], command['shell'], req['shell']

    def verdict(status, reason=None, detail=None, **extra):
        return dict(command, status=status, reason=reason, detail=detail, **extra)

    try:
        tokens = shlex.split(text, posix=target in ('bash', 'sh', 'zsh'))
    except ValueError:
        # shlex does not implement PowerShell backtick or cmd quotation rules.
        if syntax(target, text) is False:
            return verdict('WONT_RUN', 'wrong_shell_syntax', 'target shell parser rejected the command')
        return verdict('UNKNOWN', detail='quotation cannot be modeled by this tokenizer')
    if not tokens:
        return verdict('UNKNOWN', detail='empty command')
    elevated = value(profile, 'system.permissions', 'elevated')
    sudo = tokens[0] == 'sudo'
    if sudo:
        if req.get('sudo') is False:
            return verdict('WONT_RUN', 'needs_admin', 'sudo unavailable in this scenario')
        if req.get('sudo') is not True:
            return verdict('UNKNOWN', detail='sudo access unobserved')
        tokens = tokens[1:]
        text = re.sub(r'^sudo\s+', '', text)
        if not tokens or tokens[0].startswith('-'):
            return verdict('UNKNOWN', detail='sudo options are not modeled')
    name = tokens[0]
    if name.lower().endswith('.exe'):
        name = name[:-4]
    if name.lower().startswith('$env:'):
        name = '$env:APP_MODE'
    platform = profile['document']['collector']['platform']
    relevant = [r for r in req['commands'] if r['program'].lower() == name.lower()]
    if name in ('nvidia-smi', 'nvcc') and observation(profile, 'software.gpu_stack', 'cuda_driver').get('reason') == 'not_applicable_on_platform':
        return verdict('WONT_RUN', 'wrong_os', 'NVIDIA/CUDA tools are not applicable on this platform')
    if relevant and all(platform not in r['os'] for r in relevant):
        return verdict('WONT_RUN', 'wrong_os', f'{name} is not applicable on {platform}')
    found, found_version = program(profile, req, name, installed)
    if found is False:
        return verdict('WONT_RUN', 'program_missing', f'{name} not found on the scenario PATH')
    if name in ('py', 'python', 'python3') or re.fullmatch(r'python3\.\d+', name):
        py = python_facts(profile, name, text)
        if py.get('version_mismatch'):
            return verdict('WONT_RUN', 'version_mismatch', 'requested Python launcher version is not listed')
        args = tokens[1:]
        if name == 'py' and args and re.fullmatch(r'-\d+\.\d+', args[0]):
            args = args[1:]
        module = args[1] if len(args) >= 2 and args[0] == '-m' else None
        if module in ('venv', 'pip') and py.get(module) is False:
            return verdict('WONT_RUN', 'program_missing', f'Python {module} module unavailable')
    wheel = re.search(r'/whl/cu(\d{2})(\d)(?:\b|/)', text)
    if wheel:
        driver = value(profile, 'software.gpu_stack', 'cuda_driver')
        if observation(profile, 'software.gpu_stack', 'cuda_driver').get('reason') == 'not_applicable_on_platform':
            return verdict('WONT_RUN', 'wrong_os', 'CUDA is not applicable on this platform')
        if driver and version(f'{wheel[1]}.{wheel[2]}') > version(driver):
            return verdict('WONT_RUN', 'version_mismatch', f'wheel CUDA {wheel[1]}.{wheel[2]} exceeds driver CUDA {driver}')
    if hint != 'unknown' and family(hint) != family(target):
        return verdict('WONT_RUN', 'wrong_shell_syntax', f'{family(hint)} block for a {family(target)} scenario')
    if wrong_syntax(text, target, profile):
        return verdict('WONT_RUN', 'wrong_shell_syntax', 'explicit cross-shell syntax')
    if not simple(text):
        return verdict('UNKNOWN', detail='compound command, expansion, or redirection outside the rule set')
    flags = re.I if target in ('powershell', 'cmd') else 0
    rule = next((r for r in relevant if re.fullmatch(r['pattern'], text, flags)), None)
    if rule is None:
        rule = base_rule(profile, req, name, text)
    if not rule:
        return verdict('UNKNOWN', detail='no complete task rule for this command form')
    if rule.get('needs_admin') and not sudo:
        if elevated is False:
            return verdict('WONT_RUN', 'needs_admin', 'requires elevation or available sudo')
        if elevated is None:
            return verdict('UNKNOWN', detail='elevation unobserved')
    if rule.get('requires_path'):
        return verdict('UNKNOWN', detail='the profile cannot establish that the activation script exists')
    if rule.get('nvidia'):
        adapters = value(profile, 'hardware.gpu', 'adapters')
        if adapters and not any(a.get('vendor') == 'NVIDIA' for a in adapters):
            return verdict('WONT_RUN', 'wrong_os', 'task requires an NVIDIA GPU')
        if adapters is None:
            return verdict('UNKNOWN', detail='GPU unobserved; none_found does not establish absence')
    if rule.get('cuda_wheel') and value(profile, 'software.gpu_stack', 'cuda_driver') is None:
        return verdict('UNKNOWN', detail='driver CUDA compatibility unobserved')
    if rule.get('python_module'):
        py = python_facts(profile, name, text)
        if py.get(rule['python_module']) is not True:
            return verdict('UNKNOWN', detail='Python module availability unobserved')
    if rule.get('daemon'):
        daemon = value(profile, 'development.containers', 'docker_daemon')
        if not daemon or not daemon.get('reachable'):
            return verdict('UNKNOWN', detail='Docker daemon availability not established')
    if rule.get('min_version') or rule.get('major_version') is not None:
        if not found_version:
            return verdict('UNKNOWN', detail='program version unobserved')
        if rule.get('major_version') is not None and version(found_version)[0] != rule['major_version']:
            return verdict('WONT_RUN', 'version_mismatch', 'program has the wrong major version')
        if rule.get('min_version') and version(found_version) < version(rule['min_version']):
            return verdict('WONT_RUN', 'version_mismatch', 'program below task minimum version')
    if found is None:
        return verdict('UNKNOWN', detail='program availability unobserved')
    parsed = syntax(target, command['text'])
    if parsed is False:
        return verdict('WONT_RUN', 'wrong_shell_syntax', 'syntax parser rejected the command')
    if parsed is None:
        return verdict('UNKNOWN', detail=f'{target} parser unavailable or form outside parser rules')
    if rule['effect'] == 'INSTALLS':
        for installed_name in rule['installs']:
            installed[installed_name] = rule.get('installed_versions', {}).get(installed_name)
        return verdict('INSTALLS', detail='recognized installation; subsequent commands assume success',
                       installs=rule['installs'])
    return verdict('FITS', detail='explicit task rule, program and syntax checks satisfied')


def judge_answer(answer, profile, task):
    """OK requires all FITS/INSTALLS; undecided commands cannot establish success."""
    p, t = load_profile(profile), load_task(task)
    if p['id'] not in t['requirements']:
        raise ValueError('task does not apply to this profile')
    rows, installed = [], {}
    for command in extract(answer):
        rows.append(judge_command(command, p, t['requirements'][p['id']], installed))
    if rows:
        status = ('BROKEN' if any(r['status'] == 'WONT_RUN' for r in rows) else
                  'UNDECIDED' if any(r['status'] == 'UNKNOWN' for r in rows) else 'OK')
    else:
        question = '?' in answer and re.search(r'(?i)\b(?:operating system|OS|shell|Python|GPU|driver|sudo|'
                                               r'Windows|macOS|Linux|machine|computer|version|admin|package manager)\b', answer)
        status = 'ASKED' if question else 'NO_COMMANDS'
    return dict(profile=p['id'], task=t['id'], status=status, commands=rows,
                all_commands_decided=bool(rows) and all(r['status'] != 'UNKNOWN' for r in rows),
                unknown_commands=sum(r['status'] == 'UNKNOWN' for r in rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True, help='profile id')
    parser.add_argument('--task', required=True, help='task id')
    parser.add_argument('--answer', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = judge_answer(args.answer.read_text(encoding='utf-8'), args.profile, args.task)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
