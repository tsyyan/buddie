# Harness failure: `claude -p` injects host context (2026-10-26)

**What happened.** The first smoke run (`CTX-3-A-r1`, condition A, no tools) answered "your machine runs Windows 11".
Condition A is meant to know nothing about the device.

**Probe.** One extra `claude -p` call used the same flags as the harness (`--system-prompt`, `--tools ""`,
`--strict-mcp-config`, `--setting-sources ""`, `--disable-slash-commands`, `--no-session-persistence`, empty working
directory). It asked the model to quote every piece of context it had besides the system prompt and the message. The
model quoted two blocks that Claude Code attached on its own. Paths and the e-mail are redacted here:

- a `system-reminder` holding the account's e-mail address;
- an `# Environment` block: working directory `C:\Users\<user>\AppData\Local\Temp\bdx-run-…\work`, `Platform: win32`,
  `Shell: PowerShell (primary)…`, `OS Version: Windows 11 Education 10.0.26200`, a scratchpad path, the model name,
  and `Today's date is 2026-10-26`.

The probe cost USD 0.0175, as `claude -p` reported it.

**Why this invalidates the backend.** These facts describe the harness machine. That machine is the `win-laptop`
recording, so every condition receives the Windows/PowerShell facts for free:

- for the Windows scenarios (OS-1, RT-2, RT-3, HW-1, CTX-2, CTX-3, and device-1 of CTX-1) A gets the answer that only
  B and C should be able to find;
- for the Linux scenarios (OS-2, OS-3, RT-1, HW-2, HW-3) every condition is pushed toward the wrong OS;
- the injected date also contradicts CTX-2's `today` (2026-12-14).

The init event's tool list was correct (no tools, no MCP servers), so the harness's isolation check passed. It
checks tools, not prompt context.

**What does not work.** `--exclude-dynamic-system-prompt-sections` is ignored with `--system-prompt`. `--bare`, and
`CLAUDE_CODE_SIMPLE=1` which `--bare` sets, remove these sections but accept only `ANTHROPIC_API_KEY`. Under OAuth they
fail with "Not logged in". No API key is set on this machine.

**Consequence.**
- The smoke test was stopped after 1 of the 9 approved runs.
- `runs/CTX-3-A-r1.json` is kept and marked `harness_failure`, and is excluded from all rates.
- The backend now refuses to run without `--bare` unless `--allow-host-context` is passed explicitly, and records
  `host_context_injected` in each run.
