# Release Hardening: open items

Items that must be resolved, or their remaining risk documented, before Buddie 2.0 is approved for release. Not
closed because CI passes.

## RH-1: intermittent Windows full-suite failures (release blocker)

**Status: open. Root cause not identified.**

Not to be confused with the HTTP early-answer connection reset (`WinError 10053` in `test_remote`), a separate
defect fixed in PR #35.

### Observations

| When | Run | Result |
|---|---|---|
| PR #35 work, Windows 11, Python 3.14, git 2.55 | full suite, cp1251 | 30 failed, 66 errors (no log kept) |
| PR #35 final review | full suite, cp1251 | 30 failed, 64 errors (no log kept) |
| between them and after | full suites, both encodings, sequential and two at once | clean, many times |
| PR #36 baseline on `ef7e1de` | full suite, cp1251, `-rfE` log kept | **11 failed, 23 errors**: the first captured signature |
| after it | the same command with a diagnostic probe, and 12 runs of the first seven test files | clean |

### The captured signature

Every failure and error of the captured run is the same exception:

```
subprocess.py: Popen._get_handles -> self._make_inheritable(p2cread)
    _winapi.DuplicateHandle(GetCurrentProcess(), handle, ...)
OSError: [WinError 6] The handle is invalid
```

`p2cread` is the pytest process's own standard input handle (`GetStdHandle(STD_INPUT_HANDLE)`), which Popen
duplicates for a child started without `stdin=`. So at that point **the test process's standard input handle was no
longer valid**. That explains the shape of the failures:
- only tests that start a program without `stdin=` fail (test helpers' `subprocess.run(["git", ...])`, `test_core`'s
  interpreter check, …), in fixtures (errors) or in the test (failures);
- everything started through `buddie/runner.py` passes, because it gives `stdin=subprocess.DEVNULL`;
- the counts vary between runs, because the handle becomes invalid at different points.

The first failing test of the captured run was `tests/test_core.py::test_core_imports_only_the_standard_library`,
the first test after `test_bare`, `test_buddie`, `test_catalog`, `test_codex`, `test_config`, `test_context` that
starts a program inheriting standard input.

### Ruled out so far

- Shared ports: every test server binds port 0.
- Leftover processes: none remain after the runs (the runner's tree stop).
- pytest's numbered temporary directories: two full suites at once both pass; they are lock-protected.
- Windows Defender: its log shows no detection or block at those times.
- A direct `os.close(0)`, `dup2` onto 0 or `sys.stdin` closing in buddie or its tests: none exist.

### Hypotheses to test

1. A handle closed twice somewhere in the process (buddie's job-object handles in `runner.py`, a pipe closed by a
   finalizer while a reader thread still uses it), after pytest's stdin capture moved standard input to a new handle
   value that the stale close then hits. The first observed failures came after PR #34 introduced job objects.
2. The way the run was started: the parent of pytest (an agent's shell tool) closing or replacing the handle it gave
   as standard input.
3. pytest's file-descriptor capture of standard input on Windows, under Python 3.14.

### For the Release Hardening stage

1. Reproduce or capture: run the full suite with `-rfE` and the logs kept, with a probe that checks the standard input
   handle after every test (`GetStdHandle` and `GetHandleInformation` in a `pytest_runtest_logreport` hook) and names
   the first test after which it is invalid. Repeat under the launch modes of CI and of a person's terminal.
2. Keep the complete pytest logs and the environment (OS build, Python, pytest, git, how pytest was started).
3. Classify: product code (a double close in `runner.py` or elsewhere), test isolation, resource contention or the
   Windows environment.
4. Fix what is confirmed. If it is a product defect, the hook and the MCP server are affected wherever they start a
   program without `stdin=` (`verbatim/textlayer.py`'s pdftotext, `verbatim/access.py`'s certutil).
5. Document the outcome and the remaining risk before release approval.
