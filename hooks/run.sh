#!/bin/sh
# Hook launcher (audit/20 §5.1, NEXT №93): the first of python3, python, `py -3` that is Python 3.11+ runs run.py with
# this hook's stdin. Windows has no python3 (or a Store stub that fails) and Claude Code runs hooks there in Git Bash.
#
# -I runs Python isolated: PYTHONPATH, PYTHONSTARTUP and the user's site-packages, which a project's settings can set
# for the hook, do not load code into buddie. The interpreter itself is found on PATH, which they can set too: this
# launcher cannot rule out a replaced python3 (docs/policy.md, "A trusted launcher").
#
# No Python 3.11+: nothing is checked, and that is not let pass as a check. A Stop's answer goes back once with the
# reason (exit 2); the Stop Claude Code re-enters with (stop_hook_active) goes on, and the person is told by a
# systemMessage, so this never loops. Every other event goes on with the reason on stderr. This path uses shell
# builtins only: without Python the tools on PATH cannot be relied on either. It does not read the protected
# policy (that takes Python), so it holds the answer whether or not one is installed.
root=$(dirname "$(printf '%s' "$0" | tr '\\' '/' 2>/dev/null)" 2>/dev/null)/..  # a Windows path may come with backslashes
for py in python3 python "py -3"; do
  if $py -I -c 'import sys; sys.exit(sys.version_info < (3, 11))' </dev/null >/dev/null 2>&1; then
    exec $py -I "$root/run.py" "$@"
  fi
done
event=""
while IFS= read -r line || [ -n "$line" ]; do
  event="$event$line "
done
case "$event" in
  *'"hook_event_name":"Stop"'* | *'"hook_event_name": "Stop"'*) stop=1 ;;
  *) stop=0 ;;
esac
case "$event" in
  *'"stop_hook_active":true'* | *'"stop_hook_active": true'*) active=1 ;;
  *) active=0 ;;
esac
why="buddie: no Python 3.11+ (python3, python, py -3) for the hook, so nothing was checked"
if [ "$stop" = 1 ] && [ "$active" = 0 ]; then
  echo "$why. This answer goes back once and was not checked: say so to the reader in a line starting with 'buddie:'. Installing Python 3.11+ restores the checks." >&2
  exit 2
fi
if [ "$stop" = 1 ]; then
  printf '%s\n' '{"systemMessage": "buddie: this answer was not checked (no Python 3.11+ for the hook)."}'
fi
echo "$why." >&2
exit 0
