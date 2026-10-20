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
