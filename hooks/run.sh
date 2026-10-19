#!/bin/sh
# Hook launcher (audit/20 §5.1, NEXT №93): the first of python3, python, `py -3` that is Python 3.11+ runs run.py with
# this hook's stdin. Windows has no python3 (or a Store stub that fails) and Claude Code runs hooks there in Git Bash.
# No Python at all: say so and let the answer through, as a broken gate does.
root=$(dirname "$(printf '%s' "$0" | tr '\\' '/')")/..  # a Windows path may come with backslashes
for py in python3 python "py -3"; do
  if $py -c 'import sys; sys.exit(sys.version_info < (3, 11))' </dev/null >/dev/null 2>&1; then
    exec $py "$root/run.py" "$@"
  fi
done
echo "buddie: no Python 3.11+ (python3, python, py -3); answer not checked" >&2
exit 0
