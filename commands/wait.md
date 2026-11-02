---
description: Wait for CI on a PR or a commit without spending turns, then report it with a checkable anchor
argument-hint: OWNER/REPO#N or OWNER/REPO@SHA
---

Start this **in the background** (the Bash tool's `run_in_background`), then end your turn or go on with other work:
you are told when it exits. Do not poll it, do not sleep.

```bash
sh "${CLAUDE_PLUGIN_ROOT}/hooks/run.sh" wait $ARGUMENTS
```

It prints one line when CI is decided. Report that line's anchor as is: `⚓ ci:…=success` means every check on that
commit passed; `…/CHECK=failure` names the first check that failed (others may still run: look at that one first);
`=pending` means it was still running at the timeout. Exit 3 without an anchor (no checks, GitHub out of reach)
decides nothing: say so, never "CI passed".
