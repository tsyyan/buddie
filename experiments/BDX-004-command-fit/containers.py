"""Keep Docker client-only commands separate from commands needing daemon evidence."""

# These verbs/groups use the Engine API; local context/help/client-version commands do not.
# This is static classification only, never a Docker invocation.
DAEMON_COMMANDS = frozenset('attach build builder checkpoint commit config container cp create diff events exec export history image images import info inspect kill load logs network node pause plugin port ps pull push rename restart rm rmi run save search secret service stack start stats stop swarm system tag top unpause update version volume wait'.split())
GROUPS = frozenset('builder checkpoint config container image network node plugin secret service stack swarm system volume context'.split())
CLIENT_COMMANDS = frozenset(('help', 'context', 'completion', 'login', 'logout'))
# Docker documents global option values, client help and context/host overrides here:
# https://docs.docker.com/reference/cli/docker/
GLOBAL_VALUES = frozenset(('--context', '-c', '--host', '-H', '--config', '--log-level', '-l', '--tlscacert', '--tlscert', '--tlskey'))
GLOBAL_FLAGS = frozenset(('--debug', '-D', '--tls', '--tlsverify', '--version', '-v', '--help', '-h'))


def global_options(tokens):
    i, values = 1, {}
    while i < len(tokens) and tokens[i].startswith('-'):
        flag, equal, value = tokens[i].partition('=')
        if flag in GLOBAL_VALUES:
            if not equal:
                if i + 1 >= len(tokens):
                    return None, values
                i += 1
                value = tokens[i]
            values[flag] = value
        elif flag not in GLOBAL_FLAGS:
            return None, values
        i += 1
    return i, values


def needs_daemon(tokens):
    """True/False for known forms, None when the judge cannot classify the CLI."""
    i, _ = global_options(tokens)
    if i is None:
        return None
    if i == len(tokens):
        return False
    command = tokens[i]
    rest = tokens[i + 1:]
    if rest[:1] == ['--help'] or command in GROUPS and len(rest) >= 2 and rest[1] == '--help':
        return False
    if command in DAEMON_COMMANDS:
        return True
    return False if command in CLIENT_COMMANDS else None


def default_target(tokens):
    _, values = global_options(tokens)
    return not any(k in values for k in ('--host', '-H', '--config')) and all(
        values.get(k, 'default') == 'default' for k in ('--context', '-c'))
