# Release Hardening: buddie 2.0

Whether buddie 2.0 is ready for production use, installation and distribution: what was checked, how, what was
found, and what remains. Base: `main` at `47686e5` (PR #36). No tag and no published artifact come from this stage
without explicit approval.

## Summary

| Item | Status |
|---|---|
| RH-1 intermittent Windows test failures | **Root cause found outside buddie** (the Python install manager's command shim); mitigated in buddie; recurrence detected and named |
| RH-2 pattern worker reliability | Audited; one gap closed (a test that the worker ends with buddie); the macOS limitation documented |
| RH-3 installation and distribution | Wheel and sdist, Python 3.12 and 3.14 on Windows 11: 45 of 45 checks; upgrade from 1.1.1; uninstall; plugin manifests validate |
| RH-4 security regression | Security, adversarial, freshness, provenance and policy suites pass |
| RH-5 compatibility and contracts | receipt-v0 byte-identical to the pre-hardening `main`; equal in structure to 1.1.1 (two reason strings differ); receipt-v1 schema unchanged; 819 gate scenarios unchanged |
| RH-6 documentation and versioning | Version 2.0.0 in every manifest; changelog with migration notes; this page |
| RH-7 end-to-end acceptance | 12 steps from a fresh install of the 2.0.0 wheel: all pass |

## RH-1: intermittent Windows full-suite failures

### Observations

| Run | Started by | Result |
|---|---|---|
| PR #33 work, two suites at once | `timeout 590 pytest` | 54 failed, 47 errors (`WinError 50`) |
| PR #35 work | `timeout 590 pytest` | 30 failed, 66 errors |
| PR #35 final review | `timeout 590 pytest` | 30 failed, 64 errors |
| PR #36 baseline, log kept | `timeout 590 pytest` | 11 failed, 23 errors, every one `OSError: [WinError 6]` in `subprocess.Popen._make_inheritable(p2cread)` |
| every `python -m pytest` run | `python -m pytest` | clean |

The captured run's failures begin in the first test file (`tests/test_bare.py`), and every one is a test that
starts a program without `stdin=`: Popen duplicates the test process's own standard input handle
(`GetStdHandle(STD_INPUT_HANDLE)`), and that handle was no longer valid.

### Investigation

1. **Hypotheses rejected.**
   - *Invalid at process start.* A child started with an invalid standard input handle (CreateProcess with a
     closed handle value) runs the failing files clean: pytest's fd capture replaces an unusable fd 0 with `devnull`
     at start (195 passed).
   - *`os.dup2` onto fd 0 leaves the Win32 slot stale.* It does not: under a pipe, NUL, a file or the agent's shell,
     `GetStdHandle` follows fd 0.
   - *buddie code.* buddie touches handles only through its job objects and winacl's token handles; both close what
     they open, once.
2. **Narrowing.** A probe plugin checking the handle at session start, after collection and after each test
   (`GetStdHandle`, `GetHandleInformation`) found it valid at session start and invalid after collection, on the
   first loop. Collecting each test file alone, any file could trigger it, at random: not a module.
3. **Without buddie.** The same probe on a one-line test in an empty directory, no conftest, no buddie import,
   reproduces it. By launcher, collect-only runs of that test:

   | Launcher | Standard input invalid after collection |
   |---|---|
   | `%LOCALAPPDATA%\Python\bin\pytest.exe` (the Python install manager's command shim) | **13 of 140** |
   | the same, through MSYS `timeout` | 4 of 40 (included above) |
   | pip's console launcher `pythoncore-3.14-64\Scripts\pytest.exe` | 0 of 60 |
   | `python -m pytest` (the `python` app-execution alias) | 0 of 60 |

4. **Mechanism.** Under the shim the standard input handle the child receives is a fresh high value (`3008` in every
   run), the shape of a handle duplicated into a process from outside; under the other launchers it is a low,
   inherited value (276 to 624). pytest's capture closes fd 0's handle and duplicates `devnull` into it, and under the
   shim the new handle reuses the same value every time. Closing that value inside a running pytest from another
   process (`DuplicateHandle` with `DUPLICATE_CLOSE_SOURCE`) reproduces the failure on demand: `WinError 6` and
   `WinError 50` in exactly the tests that inherit standard input (one forced close in three; in the other two the
   freed value was reused by a new handle in the child, and its children got that object as input instead, which is
   the intermittency). The shim's own source was not read: that it closes the handle it duplicated into its child,
   late, is inferred from these measurements.

### Root cause and classification

The execution environment: the Python install manager's command shim (`pytest.exe` in `%LOCALAPPDATA%\Python\bin`)
invalidates, in about one run in ten, the standard input handle of the Python process it starts, after pytest's
capture has put its own handle in that slot. Not buddie code, not buddie's tests' logic, not resource contention.
The earlier `WinError 50` failures (PR #33) are the same cause, the freed value then naming another kind of object.
CI never meets it: Windows CI runs `python -m pytest`.

### Mitigation in buddie

- **buddie never gives a child its own standard input.** `runner` (`DEVNULL`), the pattern worker (a pipe),
  `pdftotext` and `certutil` (now `DEVNULL`; before, they inherited it). `tests/test_release_hardening.py` reads every
  `subprocess` call in `buddie/` and `scripts/` and fails on one without `stdin=` or `input=`.
- **The guarantee, tested.** In a process whose standard input handle is closed under it, a child started without
  `stdin=` fails (`WinError 6`), and buddie's runner, its git and its pattern worker start and answer.
- **A recurrence names itself.** `tests/conftest.py` checks the handle after collection and after each test and
  prints `RH-1: the test process's standard input handle became unusable … first seen after …`;
  `BUDDIE_RH1_STRICT=1` fails the run. Through the shim it fired on the first try.
- **Guidance.** Run the suite with `python -m pytest` (CONTRIBUTING.md).

### Residual risk

- buddie's own entry points that read standard input (`buddie hook`, `buddie serve` over stdio, `buddie verify -`)
  are started by the plugin through `sh run.sh` (`python3`, `python`, `py -3`), by Codex as `python -I run.py`, and by
  Claude Desktop as `python run.py`: none through the shim. A person who starts `buddie serve` through an install
  manager shim (`%LOCALAPPDATA%\Python\bin\buddie.exe`) may see the server lose its input; this was not tested, since
  it needs buddie installed into the person's global interpreter. Use `python -m buddie serve` there.
- The shim's behaviour belongs to the Python install manager; it is not reported upstream from here.

## RH-2: pattern worker reliability

Three deadlines, each for its own thing:

| Deadline | Value | Covers | Past it |
|---|---|---|---|
| per match (`patterns.CALL`) | 1 s | writing one request and reading its whole answer | the worker is stopped, `PatternTimeout` |
| event budget (`hook.EVENT_PATTERNS`) | 10 s | every pattern of one hook event, worker starts included | no further match starts: `PatternTimeout` |
| startup (`patterns.STARTUP`) | 15 s, and never past the event budget | the worker saying it is ready | `PatternTimeout` |
| cleanup (`patterns.CLEANUP`) | 5 s | killing, reaping, the threads on the pipes | bounded; the caller already has its answer |

| Check | Windows (local) | Linux, macOS |
|---|---|---|
| startup, shutdown, timeouts, pipe saturation, incomplete answers, a worker that exits mid-request, repeated failures, the size limit | `tests/test_patterns_worker.py`, each case in a child under a hard limit: pass | the same tests in CI |
| no worker left after any failure | pass (and none after the full suites and acceptance) | CI |
| credential isolation | `test_adv_5_8`: no token in the worker's environment | CI |
| buddie killed mid-match | `test_the_worker_ends_with_buddies_process_mid_match`: the worker ends (job object) | Linux: ends (`PR_SET_PDEATHSIG`); macOS: recorded, not asserted |
| from an installed wheel | RH-3 and RH-7 (step 10: bounded in 1.5 s) | CI package job |

**macOS limitation.** If buddie's own process is killed while a match runs, the worker runs until its match ends or
its pipe breaks; buddie's own timeouts stop it in every other case.

## RH-3: installation and distribution

Tested here (Windows 11 10.0.26200, git 2.55), from the built 2.0.0 artifacts, each in a clean venv:

| | Python 3.14.6 | Python 3.12 |
|---|---|---|
| wheel: install, `buddie --version`, `python -m buddie --version`, `buddie-verbatim --help` | pass | pass |
| sdist: the same | pass | pass |
| a non-ASCII directory and file names under cp1251, offline | pass | pass |
| a non-UTF-8 report: exit 2, not FAIL | pass | pass |
| `buddie freshness` offline: UNKNOWN (exit 3) | pass | pass |
| `buddie snapshot` of a non-ASCII file | pass | pass |
| `buddie policy show` (absent here, discovered at `C:\ProgramData\buddie\policy.toml`), `policy template` | pass | pass |
| MCP over stdio: initialize, tools/list, verify_report with receipt-v1 | pass | pass |
| the Stop hook: a gap is not a return, a broken anchor is | pass | pass |
| uninstall: the command is gone | pass | pass |

Also: wheel contents (only `buddie` at the top, no tests, both entry points), sdist contents, `twine check --strict`;
an upgrade from the 1.1.1 wheel to 2.0.0 in place (the new modules import, a check runs); `claude plugin validate .`
and `.claude-plugin/plugin.json` (Claude Code 2.1.286) pass.

**Not tested here, not claimed:** a live `/plugin install` inside a Claude Code session; Codex and Claude Desktop
installs; macOS and Linux installs beyond CI's `pip install .` smoke runs; Python 3.11 and 3.13 beyond CI; installing
a real protected policy (it needs an administrator: the suite tests it at a test-owned location); `uvx buddie` from
the MCP registry (no release published). CI covers Linux 3.11 to 3.13, and macOS and Windows on 3.11.

## RH-4: security regression

The security (`test_security_hardening`, `test_trust_boundary`, `test_provenance_*`), adversarial
(`test_adversarial`, `test_patterns_worker`), freshness, environment and policy suites pass in both encodings, as
part of the full runs below. They cover: agent configuration not weakening the protected policy (floors, profiles,
`BUDDIE_GATES`, an invalid policy is the strictest); forged evidence never becoming collector-observed (bindings,
snapshots, MCP arguments); stale or ambiguous CI never current or passing; git running nothing a repository names
and seeing none of buddie's environment; no credential in any child; failed checks never a PASS; time and output
limits on every program and pattern. The threat model is unchanged: code already running in buddie's interpreter and
the trusted base (PATH, Python, git) are outside it ([security.md](security.md), [adversarial.md](adversarial.md)).

## RH-5: compatibility and contracts

- **receipt-v0.** A fixed corpus (the quickstart and work examples, file and commit anchors, an unlinked quote,
  prose work claims, an empty text), same paths and time: **byte-identical** to `main` at `47686e5`. Against the
  1.1.1 release: 5 of 7 cases identical; in the other 2 only the human-readable reasons in `gaps` / `why` of a path
  that leads out of the repo and of `fact=` differ (commit `8cb7273`, merged after 1.1.1); keys, statuses and outcomes
  are the same.
- **receipt-v1.** `docs/receipt-v1.schema.json` has no change since it was introduced (`0f864ec`), and
  `receipts.SCHEMA` equals it.
- **The 819 gate scenarios** are unchanged (`tests/test_gate.py`).
- **Profiles, CLI exit codes, MCP tools, the hook's registration** are covered by their suites; existing `buddie.toml`
  files keep working, except `[mandate]` patterns that backtrack exponentially or doc templates with more than
  `{name}` fields, which are refused with the reason (changelog).

## RH-6: documentation and versioning

- Version **2.0.0** in `buddie/__init__.py`, `pyproject.toml`, `CITATION.cff`, `server.json` and the Claude Code, Codex,
  ChatGPT and Desktop manifests (`tests/test_version.py`), the README's status and the skill's pinned install.
- CHANGELOG: a 2.0.0 section with migration notes from 1.1.1.
- Supported: Python 3.11 to 3.13 (CI), and 3.14 tested here on Windows; Linux, macOS, Windows.

### Release checklist (not done here)

1. Independent review of this PR, RH-1's classification above in particular.
2. CI green on the release commit.
3. `CITATION.cff` `date-released`, the CHANGELOG heading's date.
4. Tag `v2.0.0` and publish (PyPI, MCP registry, plugin catalogs, the Desktop bundle) only with explicit approval.

## RH-7: end-to-end acceptance

From a fresh venv with the 2.0.0 wheel (Windows 11, Python 3.14.6, git 2.55), in a new repository:

| # | Step | Result |
|---|---|---|
| 1 | fresh install | pass (`buddie 2.0.0`) |
| 2 | `buddie init` | pass |
| 3 | a valid, evidence-backed answer (`⚓ data.txt#<sha>`) through the Stop hook | exit 0, PASS |
| 4 | a fabricated claim: under the intro mode `init` turns on, warned; after `buddie enforce`, returned | pass, then exit 2 |
| 5 | unavailable evidence (GitHub off) | exit 0, GAPS |
| 6 | the protected policy discovered at its fixed place (installing one needs an administrator: covered by the suite) | pass |
| 7 | the Stop hook | steps 3 to 5 |
| 8 | MCP `verify_report` over stdio | FAIL for the fabricated anchor |
| 9 | freshness against GitHub: PR #36's final head CURRENT, the squash merge commit STALE | pass (exit 0, exit 1) |
| 10 | a malicious `buddie.toml` pattern | bounded: returned in 1.5 s |
| 11 | receipts: v0 by default, v1 on request, `receipts.problems()` empty | pass |
| 12 | a hook killed mid-check, then the next event | exit 0, the journal whole, no worker left |

## Known issues

- RH-1's environment: on Windows, run the suite with `python -m pytest`, not the install manager's `pytest.exe` shim.
- macOS: a worker can outlive a buddie process killed mid-match (RH-2).
- Polynomial patterns are bounded by time, not refused; a queue cell over 64 K characters is not pattern-checked.
- `clean`, repository facts and the repository's own evidence are agent-writable ([environment.md](environment.md)).
- A pattern timeout or any failed check returns the answer; a later attempt with a `buddie:` line saying it was not
  checked goes out (the hook's failsafe).
