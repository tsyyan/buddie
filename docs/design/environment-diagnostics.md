# Design: task-aware environment diagnostics

Status: implemented in the pull request on branch `feat/task-aware-environment-collector`. This note was written
before the code, as its contract; the user-facing description is [environment.md](../environment.md),
"Diagnostics".

## The problem

Before an agent tells a person "install CUDA 12.4" or "run `py -3.12 -m venv`", it should know the person's system
instead of guessing it. buddie already observes a small fixed set (environment-v0: the interpreter, the repository,
named files). Diagnostics extend that to what an agent needs for setup work, asked per task, observed by buddie's
own fixed code, and limited to what the person allowed.

## Architecture

```
request (agent or person)          authorization (the person's, not the request's)
  categories, task, tools, path      grants file  ∩  protected policy [environment]
            │                                   │
            ▼                                   ▼
   validate against the static registry ──► effective categories (and granted roots)
            │                                   │
            │   denied / unsupported / unknown: recorded, no collector called
            ▼
   planner: registry order, one category at a time, a deadline for all of it
            │
            ▼
   collector of the category ──► its own declared methods only (fixed argv, fixed files, OS APIs)
            │                      adaptive: later methods chosen from earlier results, same category
            ▼
   environment-diagnostics-v1 document: per category status, observations (value or reason),
   basis, method, time; the request's task kept as caller-supplied; limitations
```

- **Registry** (`buddie/diagnostics.py`): a static table. Each category has an id, a sensitivity tier
  (`baseline` or `sensitive`), the platforms it supports, whether it needs a path, the methods it may use (each a
  fixed program with fixed arguments, a fixed file, or an OS interface), budgets, and the observations it can return.
  Nothing is added at run time.
- **Authorization**: effective = requested ∩ supported here ∩ granted by the person ∩ allowed by the protected
  policy. The person grants in a local file (`environment.toml` in buddie's user config directory); `baseline`
  grants the low-sensitivity tier, every sensitive category is named one by one, and path-scoped categories also
  need the path inside a granted root. An ACTIVE protected policy is a ceiling (`[environment] allow`): it can only
  narrow; without that table it allows none; an INVALID one allows none.
- **Planner**: deterministic. Categories run in registry order; each collector may call only its own methods, and
  records each attempt with why it was made and how it ended. One deadline covers the whole request
  (`runner.deadline`), each program has its own timeout and output limit.
- **Methods**: Python's own reports and OS interfaces first (`platform`, `/proc`, `/sys`, `/etc/os-release`,
  `winreg`, `ctypes`), then programs at fixed system locations, then programs found on `PATH`. Programs get a fixed
  argument list, no shell, no stdin, stderr discarded, an environment built from an allowlist (no tokens, no
  `*_OPTIONS`, no `LD_PRELOAD`, no `DOCKER_HOST`), a neutral working directory, and only version-shaped tokens of
  their output are kept.
- **Document** (`environment-diagnostics-v1`): separate from environment-v0, which is unchanged. When the caller
  also asks for the legacy parts (artifacts, a report), the v0 snapshot is embedded as is, so freshness and receipt
  pairing keep working on it.
- **Interfaces**: `buddie snapshot --category …` (and `--list`, `--grants`, `--grant-template`) and the local MCP tool
  `environment_snapshot`. The remote HTTP server does not offer it.

## Threat model

| Actor | Can | So |
|---|---|---|
| The agent asking | choose categories, the task text, tool names, a path; claim anything in the request | the request selects, never authorizes; unknown fields (a `consent: true`) are refused; the task is caller-supplied text, not a parameter of any method |
| The agent, same OS user | write the grants file, `PATH`, the environment, project files, a fake `nvidia-smi` on `PATH` | local grants are a statement of the person's intent, not a barrier against this agent; programs found on `PATH` have basis `path_program`; observations are buddie's report of what it read, not attestation |
| An administrator | write the protected policy | the only input the agent cannot change: a ceiling on categories |
| The observed system | answer slowly, with huge or malformed output, hang | every method has a timeout and an output limit; parsing accepts only expected shapes; a malformed answer is `inconclusive`, never a value |
| Other software reading the result | see what is returned | no user names, home paths, environment variables, process lists, command lines or raw program output; values are short, sanitized, version- or model-shaped |

What it does not defend: an agent with a shell can run `nvidia-smi` itself; diagnostics do not prevent that, they give
agents without a shell (MCP-only clients) a bounded, authorized way, and every agent a structured one. A local grant
cannot tell the person from an agent running as the same user (docs/policy.md); only the protected policy can, and
only as a ceiling. A container or WSL guest reports its own view: memory limits, GPUs passed through, the host's
programs seen through WSL interop are labelled, not resolved into host facts.

## Deliberately unsupported here

Network connectivity, proxy configuration, application settings and port probing: each reaches beyond the machine's
own description (outbound connections, other programs' configuration with possible secrets, other services). They
are listed in the registry as unsupported with the reason, so a request for them gets an explicit answer and no
probe.
