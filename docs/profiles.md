# Verification profiles

A profile names which of buddie's checks to run. It is a preset of configuration, not a separate engine: every
profile goes through the same modules ([architecture.md](architecture.md)) and the same `verify` code, and a check
that runs gives the same verdict under any profile. A profile cannot make a claim more verified than its evidence,
grant a source, or change where evidence counts as coming from.

## The profiles

| Profile | Modules | Checks | For |
|---|---|---|---|
| `developer` | `github`, `execution` | `file_anchor`, `commit_anchor`, `fact_anchor`, `pr_anchor`, `ci_anchor`, `run_anchor`, `choice_anchor`, `work_claim`, `other_anchor` | software work: repos, commits, PRs, CI, what the session ran, work claims |
| `research` | `sources` | `quote`, `number` | reports that cite sources: quotations and the numbers of cited sentences |
| `complete` | all | all | everything buddie checks, the same as no profile |
| `custom` | what you list | what you list | any other set |

`buddie profiles` prints this table from the code, and `buddie modules` prints the modules and what each one reads.

Resolution is deterministic. The same names always give the same set, and the order you write them in doesn't
matter: checks come out in `core.Check` order, modules in registry order. A built-in profile takes no modules or
checks of its own: `--profile developer --modules sources` is an error, so `developer` always means the same set.

## Selecting one

**One check** (CLI, MCP, Python):

```bash
buddie verify report.md --profile research
```

```bash
buddie verify report.md --profile custom --modules github --checks run_anchor
```

`--modules` or `--checks` without `--profile` mean `custom`. MCP `verify_report` takes `profile`, `modules` and
`checks`. In Python, use `verify.assess_selected(text, profile="developer")`, or
`assess_selected(text, ["github"], checks=["run_anchor"])`. `verify()` and `assess()` keep their signatures and run
everything. The remote MCP server takes none of these: its argument contract is unchanged.

**A project** (the hook), in `buddie.toml`:

```toml
[verify]
profile = "developer"
```

```toml
[verify]
profile = "custom"
modules = ["sources"]
checks = ["pr_anchor", "ci_anchor"]
```

There is no new environment variable: a project's profile lives with its other settings.

## What a profile does in the hook

The gate works by class (`anchors`, `quotes`, `numbers`, `work`, `prose`, and the form classes `final`, `summary`,
`promises`, `context`), each `block`, `warn` or `off`. In the hook, a profile is a preset of those levels. It sets
to `off` each class that none of its checks feed: `developer` turns off `quotes` and `numbers`; `research` turns
off `anchors`, `work` and `prose`. It never touches the form classes. The hook then runs only the checks whose class
is still on, so `developer` doesn't fetch the pages of quotes nobody will judge.

### Precedence

From weakest to strongest:

1. buddie's defaults;
2. the profile, which turns classes off;
3. `buddie.toml` `[gates]`;
4. `BUDDIE_GATES` and the plugin options;
5. the protected policy's floors ([policy.md](policy.md)).

An explicit level beats the profile: `profile = "developer"` with `[gates] quotes = "block"` checks quotes. A
floor beats everything below it: `profile = "research"` under a policy with `anchors = "block"` checks anchors,
and the refusal is journaled (`gates.anchors`). A class that ends up on is run, whatever the profile said.

### No profile, and a profile with nothing left

Two different states:

- **No profile** (`ResolvedEventContext.run_checks()` is `None`). The hook runs every check through `verify.assess`,
  exactly as before profiles.
- **A profile whose effective selection is empty** (`run_checks()` is `()`). The profile and the levels above it
  turned off every class a check feeds, for example `profile = "research"` with `[gates] quotes = "off"` and
  `numbers = "off"`. Then no check runs: no page is fetched and GitHub is not asked. The receipt holds no rows, and
  its outcome is `EMPTY` ("nothing to check"), never `PASS`. The journal line says
  `"profile": {"name": "research", "checks": []}`. `buddie status` says
  `the hook runs: no verification check (…): nothing an answer claims is verified`, and the note (Python:
  `profiles.note`) begins `No verification checks ran under the effective profile research and gate levels`.

An empty selection can only come from levels. A person asking for `custom` with nothing in it gets an error.

### Who can choose

`buddie.toml`, the hook's environment and CLI or MCP arguments are all within the agent's reach (policy.md, "Who
can set what"). A profile chosen there is the same as writing those levels in `[gates]`: the agent could do that
already, and the protected policy is what stops it from going below a floor. The host can't tell a trusted choice of
profile from the agent's, so no profile is trusted. Only the policy's floors are binding. There is no policy key for
profiles: a floor already brings back anything a profile turns off, and a policy written before profiles existed
decides exactly as it did.

## Excluded, unverified, verified

Three different things:

- **Excluded**: the profile left the check out, so it did not run. A receipt from CLI or MCP holds no rows for it.
  Coverage names the check (`module:<id>` or `check:<id>`, a capability off, so the core outcome is GAPS, never
  PASS), and the claims of that kind the text holds are counted. The CLI prints them as a note, for example
  `note  profile research: modules sources; not checked: …; in the text and not checked: 1 file_anchor, 1
  pr_anchor`, and MCP puts the same line in its text. In the hook an excluded class is `off`: the gate does not speak
  about it.
- **Unverified**: the check ran and could not conclude. The source was unavailable, the repo absent, GitHub offline:
  a gap (`UNCHECKABLE`, `SOURCE_UNAVAILABLE`). A profile keeps it a gap; it never becomes a pass.
- **Verified**: the check ran and the evidence holds. That says the claim matches its evidence: the quote is on the
  page, the PR is in that state. It doesn't say the evidence is right.

### What receipt-v0 says, and what it does not

Receipt-v0 is unchanged. Its `outcome` is computed as it always was, from the checks that ran:
- `PASS` means the checks that ran established no failure and found nothing open. It does not certify that every
  claim in the report was checked: under a profile, or with `--anchors-only`, a kind of claim may not have been
  looked at.
- `EMPTY` means nothing was checked, never "verified".
- The scope (what ran, what a profile left out, how many claims of the left-out kinds the text holds) lives outside
  the receipt: in Coverage (`core.outcome` gives GAPS for a smaller check, UNKNOWN for an empty one), in the CLI's
  `note` line, in MCP's text beside the receipt, in the hook's journal line and in `buddie status`.

A consumer that reads only the receipt cannot tell a complete check from a partial one. The CLI's exit code is
unchanged too (1 only on FAIL). Making scope part of the receipt is left to the receipt contract (PR #31), which
has to answer one question: **how should a receipt keep the verification outcome, the executed scope, the excluded
checks and completeness apart, so that PASS is never read as full coverage?**

## Unknown names

An unknown profile, module or check is an error naming the known ones: CLI exit 2, an MCP tool error, a
`profiles.UnknownProfile` in Python. It never falls back to a weaker set. In `buddie.toml` the same mistake, or a
`[verify]` that isn't a table of strings, makes the file unusable: the gate returns each answer with the reason
until the file is fixed, as for any broken `buddie.toml`.

## Examples

A software project whose final answers are about code:

```toml
[verify]
profile = "developer"
[gates]
anchors = "block"   # already the default; written down for readers of the file
```

A research project that also wants PR links checked:

```toml
[verify]
profile = "custom"
modules = ["sources"]
checks = ["pr_anchor"]
```

## Migration

Nothing changes until you choose a profile. Without one, the CLI, MCP, the hook and the Python API run every check,
and the receipts, levels, journal and golden gate scenarios are identical to before. #29's `--modules` and MCP
`modules` still work and now mean `custom`.

## Decisions (approved for #30)

- **No protected-policy key for profiles.** The policy's floors are the enforcement: a floor brings back any class a
  profile turns off (tested for `quotes` under `developer` and `anchors` under `research`). No profile allowlist,
  no second mechanism.
- **The hook selects by gate class.** `custom` with only `pr_anchor` turns the `anchors` class on, and the hook then
  runs every anchor check of that class; its journal line lists them (tested). CLI, MCP and the Python API select
  exactly the checks named.
- **Receipt evolution belongs to PR #31.** Receipt-v0 and its guarantees stay as they are.

## Limits

- A profile is chosen where the agent can write. Only the protected policy's floors bind it.
- In the hook a profile acts per gate class. `custom` with only `pr_anchor` still runs every anchor check, because the
  `anchors` class is on. Per-check selection is exact for CLI, MCP and the Python API.
- The final rule ("a final answer with no anchor") looks at the anchors in the text, so an anchor a profile does not
  check still counts as present. It is not checked.
