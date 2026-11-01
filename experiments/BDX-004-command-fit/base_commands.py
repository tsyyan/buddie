"""Scenario userland assumptions and bounded command forms, separate from observations."""
import re
from syntax import family

# Selected GNU Coreutils commands, not a claim that the entire package is present:
# https://www.gnu.org/software/coreutils/manual/coreutils.html
LINUX_COREUTILS = frozenset('ls mkdir rm cp mv cat chmod touch pwd printf echo head tail du df uname whoami'.split())
# Selected util-linux read-only tools (not coreutils or iproute2):
# https://github.com/util-linux/util-linux (misc-utils/lsblk, sys-utils/findmnt)
LINUX_UTIL_LINUX = frozenset(('lsblk', 'findmnt'))
# tar is a separate GNU package on these Linux scenarios:
# https://www.gnu.org/software/tar/manual/
LINUX_EXTRA = frozenset(('tar',))
# Selected BusyBox applets assumed enabled in the Alpine scenario; BusyBox builds are configurable:
# https://busybox.net/downloads/BusyBox.html
ALPINE_BUSYBOX = frozenset('ls mkdir rm cp mv cat chmod touch pwd printf echo head tail du df uname whoami tar'.split())
# Apple's BSD userland sources, not GNU option semantics:
# https://github.com/apple-oss-distributions/file_cmds
# https://github.com/apple-oss-distributions/shell_cmds
# https://github.com/apple-oss-distributions/libarchive (bsdtar)
MACOS_BSD = frozenset('ls mkdir rm cp mv cat chmod touch pwd printf echo head tail du df uname whoami tar'.split())
# POSIX shell builtins used by the profiles:
# https://pubs.opengroup.org/onlinepubs/9799919799/utilities/contents.html
POSIX_BUILTINS = frozenset(('export', 'echo', 'printf', 'pwd', 'cd', 'set', '.', 'true', 'false', ':', 'test', '['))
# Core Management and Utility module cmdlets; names stored case-insensitively:
# https://learn.microsoft.com/powershell/module/microsoft.powershell.management/
# https://learn.microsoft.com/powershell/module/microsoft.powershell.utility/
POWERSHELL_CORE = frozenset(n.lower() for n in (
    'Get-ChildItem', 'New-Item', 'Remove-Item', 'Get-Content', 'Get-Location', 'Set-Location',
    'Copy-Item', 'Move-Item', 'Write-Output', 'Get-Process', 'Get-Date'))
# Command-shell builtins (not all Win32 executables, and not PowerShell cmdlets):
# https://learn.microsoft.com/windows-server/administration/windows-commands/cmd
# https://learn.microsoft.com/windows-server/administration/windows-commands/windows-commands
CMD_BUILTINS = frozenset('dir mkdir md rmdir rd del erase set echo cd chdir copy move type ver'.split())
BASE_NAMES = (LINUX_COREUTILS | LINUX_UTIL_LINUX | LINUX_EXTRA | ALPINE_BUSYBOX | MACOS_BSD |
              POSIX_BUILTINS | POWERSHELL_CORE | CMD_BUILTINS)

# The lists above establish availability. These bounded forms retain known effects;
# other forms can FITS when syntax parses and no stronger task constraint is broken.
# Operands deliberately exclude options, expansions, globs and quoting we cannot model.
OPERAND = r'[A-Za-z0-9_./][A-Za-z0-9_./-]*'
POSIX_FORMS = {
    'true': r'true', 'false': r'false', ':': r':',
    'test': rf'test (?:-[def] {OPERAND}|{OPERAND} = {OPERAND})',
    '[': rf'\[ (?:-[def] {OPERAND}|{OPERAND} = {OPERAND}) \]',
    'ls': rf'ls(?: -[alh1]+)?(?: {OPERAND})?',
    'mkdir': rf'mkdir(?: -p)? {OPERAND}',
    'rm': rf'rm(?: -[f]+)? {OPERAND}',
    'cp': rf'cp {OPERAND} {OPERAND}',
    'mv': rf'mv {OPERAND} {OPERAND}',
    'cat': rf'cat {OPERAND}',
    'touch': rf'touch {OPERAND}',
    'pwd': r'pwd',
    'uname': r'uname(?: -[amsnr]+)?',
    'whoami': r'whoami',
    'df': r'df(?: -h)?',
    'du': rf'du(?: -[sh]+)?(?: {OPERAND})?',
    'head': rf'head(?: -n [0-9]+)? {OPERAND}',
    'tail': rf'tail(?: -n [0-9]+)? {OPERAND}',
    'chmod': rf'chmod u\+x {OPERAND}',
    'lsblk': r'lsblk(?: -f)?',
    'findmnt': r'findmnt',
}
CMD_FORMS = {
    'dir': rf'dir(?: /[ab])?(?: {OPERAND})?',
    'mkdir': rf'mkdir {OPERAND}', 'md': rf'md {OPERAND}',
    'del': rf'del {OPERAND}', 'erase': rf'erase {OPERAND}',
    'set': r'set(?: [A-Za-z_]\w*=[A-Za-z0-9_./-]*)?',
    'ver': r'ver', 'type': rf'type {OPERAND}',
}
POWERSHELL_FORMS = {
    'get-childitem': rf'Get-ChildItem(?: -Force)?(?: {OPERAND})?',
    'new-item': rf'New-Item -ItemType Directory {OPERAND}',
    'remove-item': rf'Remove-Item {OPERAND}',
    'get-content': rf'Get-Content {OPERAND}',
    'get-location': r'Get-Location',
    'set-location': rf'Set-Location {OPERAND}',
    'get-process': r'Get-Process',
    'get-date': r'Get-Date',
    'write-output': rf'Write-Output {OPERAND}',
}
TAR_FORM = rf'tar -(?:czf {OPERAND} {OPERAND}|xzf {OPERAND}|tzf {OPERAND})'


def programs(profile, requirements):
    """Select a scenario's base set without asserting absence outside that set."""
    platform = profile['document']['collector']['platform']
    shell = family(requirements['shell'])
    if shell == 'powershell':
        return POWERSHELL_CORE
    if shell == 'cmd':
        return CMD_BUILTINS if platform == 'windows' else frozenset()
    if shell != 'posix':
        return frozenset()
    if platform == 'darwin':
        return MACOS_BSD | POSIX_BUILTINS
    if platform == 'linux':
        distribution = profile['document']['categories'].get('system.os', {}).get('observations', {}).get(
            'distribution_id', {}).get('value')
        return (ALPINE_BUSYBOX if distribution == 'alpine' else
                LINUX_COREUTILS | LINUX_UTIL_LINUX | LINUX_EXTRA) | POSIX_BUILTINS
    return frozenset()


def rule(profile, requirements, name, text):
    """Return a complete base-command rule, never a default FITS for arbitrary flags."""
    shell = family(requirements['shell'])
    key = name.lower() if shell in ('powershell', 'cmd') else name
    forms = POWERSHELL_FORMS if shell == 'powershell' else CMD_FORMS if shell == 'cmd' else POSIX_FORMS
    pattern = TAR_FORM if key == 'tar' else forms.get(key)
    if (key in programs(profile, requirements) or key == 'tar') and pattern and re.fullmatch(
            pattern, text, re.I if shell in ('powershell', 'cmd') else 0):
        return dict(pattern=pattern, program=name, effect='FITS', os=[profile['document']['collector']['platform']])
    return None
