# Codex brief: the BDX-004 starter set

You work in the repository `tsyyan/buddie`, on the branch `experiment/bdx-004-command-fit`. Read
`experiments/BDX-004-command-fit/README.md` and `PROTOCOL.md` first, then `docs/environment.md` (section
"Diagnostics"), `buddie/diagnostics.py`, `buddie/probes.py` and `tests/test_diagnostics.py` (its recorded answers show
what real observations look like on each platform).

## Goal

Build the material and the model-free judge of BDX-004, so that the experiment can later run by adding only the
model calls. **Do not call any model, do not add provider code, do not change anything under `buddie/`, `skills/`,
`hooks/`, other experiments, or the release files.** Everything goes under `experiments/BDX-004-command-fit/`, plus
one workflow file (item 7).

## Deliverables

1. **Profiles** (`profiles/<id>.json`), at least 8, each an `environment-diagnostics-v1` document as
   `buddie.diagnostics.collect` would return it, with every baseline category `collected` or honestly `partial` /
   `unavailable`, and `buddie.diagnostics.problems(doc) == []`. Add `profiles/index.json` listing for each profile:
   `id`, one-line description, `provenance` (`hand-built`; `recorded` only for a document actually collected on a
   machine, with the date), and `granted` (the categories the tool stand-in may return). Cover at least:
   - `win11-pwsh-nvidia`: Windows 11, PowerShell 7 and Windows PowerShell, NVIDIA GTX 1650 4 GiB, driver supporting
     CUDA 13.2, no CUDA toolkit on PATH, Python 3.12 via `py`, winget, no conda;
   - `win11-cmd-nogpu`: Windows 10/11, cmd and Windows PowerShell only, integrated GPU, Python 3.11 only, choco;
   - `macos-arm`: macOS 15 on Apple Silicon, zsh, Homebrew, python3.13, no NVIDIA (CUDA not applicable);
   - `ubuntu2404-nvidia`: Ubuntu 24.04, bash, apt, sudo available, RTX 4090 24 GiB, driver for CUDA 12.4, nvcc 12.4,
     python3.12 with venv;
   - `ubuntu2204-nosudo`: Ubuntu 22.04, bash, not root and no sudo, no GPU, python3.10 without `venv` module;
   - `wsl-ubuntu`: Ubuntu under WSL 2 (`runtime_context: wsl`), the Windows host's NVIDIA visible, bash, apt;
   - `fedora40`: Fedora 40, dnf, bash, python3.12, podman not docker;
   - `alpine-container`: Alpine in a container (`runtime_context: container`), ash/sh only (no bash), apk, musl,
     root, python3.12, memory limit from cgroup.
2. **Tasks** (`tasks/tasks.json`), at least 24. Each: `id`; `prompt` (what a person asks, with no word about their
   machine, in English); `categories` (what `environment_snapshot` should be asked for); `applies_to` (profile ids, or
   `"all"`); and `requirements`: per profile, what a fitting command must satisfy, as data the judge reads (for
   example required program or one of several, shell family, a version bound such as "CUDA wheel <= driver CUDA",
   "needs admin"). Mix: Python environments, PyTorch/CUDA, GPU checks, installing a tool (ffmpeg, git, node 20),
   containers, environment variables for one session, finding the process on a port, archives, downloading a file,
   permissions, services. At least a third must have a command whose correct form differs by shell (bash vs
   PowerShell vs cmd vs sh).
3. **Command extraction** (`commands.py`): from an answer in markdown, the commands a person is told to run: fenced
   blocks (language tag `bash`, `sh`, `zsh`, `powershell`, `pwsh`, `ps1`, `cmd`, `bat`, `console`, `shell`, or none)
   and single-line inline code that starts with a program; prompts (`$ `, `PS> `, `C:\>`) stripped; comments and
   output lines left out; line continuations joined; each command with the shell its block implies (or `unknown`).
4. **Tool stand-in** (`tool.py`): `environment_snapshot(args, profile)` taking the MCP tool's arguments
   (`categories`, `task`, `tools`, `path`, `list`; any other key is an error, as in `buddie/mcp.py`) and returning
   the profile's document restricted to the requested categories, with categories outside `granted` as `denied`
   (`not_granted`) exactly as the real tool reports them; `{"list": true}` answers like the real catalog. Plus the
   tool's JSON schema for a chat API (name, description, parameters), copied from `buddie/mcp.py`.
5. **Judge** (`judge.py`): per command FITS, INSTALLS, WONT_RUN with a reason (`program_missing`,
   `wrong_shell_syntax`, `wrong_os`, `version_mismatch`, `needs_admin`), or UNKNOWN; per answer OK, BROKEN, ASKED
   (asks about the machine and gives no command), NO_COMMANDS. Rules come from the profile and the task's
   requirements only. Syntax: `bash -n` / `sh -n` (dash or busybox semantics for `sh` profiles) when present;
   PowerShell through `pwsh -NoProfile -Command` with `[System.Management.Automation.Language.Parser]::ParseInput`
   when `pwsh` is on PATH, otherwise UNKNOWN; cmd by a small explicit rule set. A program that a previous command in
   the same answer installs counts as present after it. **Conservative**: when a rule does not decide, UNKNOWN; never
   FITS by default. CLI: `python judge.py --profile P --task T --answer FILE` prints JSON.
6. **Recorded answers and tests** (`tests/`): for at least 12 (profile, task) pairs, hand-written answers (a fitting
   one, a broken one, a question-only one, and tricky ones: an install step before use, a bash block for a PowerShell
   user, `nvidia-smi` on a Mac, `sudo` without sudo, `python3 -m venv` without the venv module, a `cu124` wheel on a
   CUDA 12.2 driver), each with the judge's expected outcome; plus tests for extraction, the tool stand-in (denied
   categories, unknown arguments) and that every profile passes `problems`. `unittest`, stdlib only, no network; tests
   needing `pwsh` or `bash` skip when they are absent.
7. **CI**: `.github/workflows/bdx004.yml` running those tests on a pull request that touches the folder, on
   ubuntu-latest and windows-latest, Python 3.12, actions pinned to the same commit SHAs as
   `.github/workflows/bdx003.yml` on the branch `experiment/bdx-003-correction` (checkout `11d5960…`, setup-python
   `a26af69…`), `permissions: contents: read`.
8. **README**: fill in what was built, how many profiles, tasks and units (pairs where the task applies), and the
   judge's known limits (what it marks UNKNOWN and why).

## How to work

- Python 3.11+, stdlib only. Small modules, plain functions, short docstrings that say what and why, as in
  `experiments/BDX-003-correction` (on its branch) and `buddie/`.
- Commit in reviewable steps (profiles, tasks, extraction, tool, judge, tests, CI), each with a clear message.
- Run the tests and `python -c "import json,sys; ..."`-style checks of every profile against
  `buddie.diagnostics.problems` before each commit; state in the PR description what you ran and the results.
- Open a pull request into `main` titled `experiments: BDX-004 starter set (profiles, tasks, model-free judge)`,
  as a draft. Do not merge it.
- If something in this brief conflicts with what `buddie/diagnostics.py` actually does, follow the code, and say so
  in the PR description.
