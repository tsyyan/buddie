---
description: Turn on buddie's full checks for this project (writes buddie.toml, starts in intro mode)
---

Without `buddie.toml` buddie returns an answer only for what is false: a quote not on its page, an anchor that does
not hold. `buddie init` writes `buddie.toml` with the full checks: a final answer must carry anchors, and work claimed
in prose warns. It starts in intro mode, so for the first 20 final answers nothing is returned, only warned.

Ask the person to confirm before writing the file. Then run:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/hooks/run.sh" init
```

Show the output, and tell the person that `buddie.toml` can be edited (each class is "block", "warn" or "off") and
that `sh "${CLAUDE_PLUGIN_ROOT}/hooks/run.sh" enforce` ends the intro mode.

Then offer the environment diagnostics, as a separate question. With them an agent can ask buddie what this machine
has (OS and shell, privilege level, CPU, memory, GPU and its driver and CUDA version, Python interpreters, runtimes,
package managers, catalog tools) before suggesting commands, instead of guessing. It reads versions and model names,
never files, paths, environment variables or the network, and only when asked. Run
`sh "${CLAUDE_PLUGIN_ROOT}/hooks/run.sh" snapshot --list` to show the categories, and only if the person agrees:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/hooks/run.sh" snapshot --grant-baseline
```

It writes their grants file with the baseline categories only (never over an existing one); the sensitive ones
(storage, containers, a project, a repository) stay off unless they add them to that file.
