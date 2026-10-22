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

Receipt-v0 itself is unchanged. Its `outcome` word for a profile is computed as it always was for the checks that
ran, as with `--anchors-only`, and that is why the note and Coverage say what was left out.

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

## Limits

- A profile is chosen where the agent can write. Only the protected policy's floors bind it.
- In the hook a profile acts per gate class. `custom` with only `pr_anchor` still runs every anchor check, because the
  `anchors` class is on. Per-check selection is exact for CLI, MCP and the Python API.
- The final rule ("a final answer with no anchor") looks at the anchors in the text, so an anchor a profile does not
  check still counts as present. It is not checked.
