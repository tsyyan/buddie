---
name: environment
description: Before telling the person to run commands on their own machine (install, set up, configure, GPU, Python, Docker), ask buddie's environment_snapshot for the categories those commands depend on, instead of guessing the OS, shell or versions.
---

# environment: look before you suggest a command

A command written for another machine fails on the person's: `apt` on Windows, a bash block for a PowerShell user,
`py -3.12` where only 3.11 is installed, a CUDA 12.4 wheel on a driver that supports 12.2. buddie's
`environment_snapshot` tool tells you what this machine has, for the categories the person granted.

1. **Only when the commands depend on the machine.** Skip it for anything you run yourself in a shell you can see,
   and for questions that do not end in commands for the person to run.
2. **Ask for what the commands need**, not everything: `{"categories": ["system.os", "system.shell"], "task": "..."}`;
   add `hardware.gpu` and `software.gpu_stack` for GPU work, `software.python` for Python environments,
   `software.package_managers` for installs, `software.containers` for Docker or Podman (add
   `development.containers` only when it matters whether the daemon answers). `{"list": true}` shows the
   categories and what is granted.
3. **Use what it says, and what it does not.** A `denied` category was not granted: do not guess it, say which
   commands depend on it, or ask the person. `unavailable` is not "absent": `not_found_on_path` means not found where
   buddie looked.
4. **Write the commands for that machine**: its shell's syntax, its package manager, versions it can take. When a
   command installs what is missing, put the install first.
5. **Anchor what you say about the machine**, so it is checked, not taken on your word: after the sentence, ⚓ and in
   backticks `env:CATEGORY.OBSERVATION=VALUE` with the value the snapshot gave, e.g. "You have Python 3.12 ⚓
   `env:software.python.interpreters=3.12` and bash ⚓ `env:system.shell.default=bash`". `verify_report` and the hook
   observe the machine again under the same grants: a value that differs returns the text, a category not granted
   stays unchecked.

Nothing is granted until the person says so: `/buddie:init` offers the baseline categories, and
`buddie snapshot --grants` shows what is granted. The snapshot is buddie's report of what it read, not proof of the
machine (docs/environment.md).
