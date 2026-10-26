# Verification: what buddie checks

How buddie checks the claims in an agent's report, with two examples you can run from a clone, the kinds of
claim it recognises, the four outcomes, and the research behind the quote check. The overview is the
[README](../README.md); how the checks are divided and where evidence comes from is in
[architecture.md](architecture.md).

## See it work

A report quotes a status page wrongly twice. buddie checks each quotation against a snapshot of the page it links to
(from a clone of this repository, no network):

<!-- doc-example: quickstart -->
```bash
cd buddie/examples/quickstart
buddie-verbatim add https://status.example.com/incidents/42 page.html
buddie verify report.md --no-fetch
```

```
BLOCK quote L3.1 not found in https://status.example.com/incidents/42: “elevated error rates on the API between 14:58 and 15:41 UTC” (closest 0.98: “elevated error rates on the API between 14:59 and 15:41 UTC”)
BLOCK quote L7.1 not found in https://status.example.com/incidents/42: “the root cause was a misconfigured load balancer” (closest 0.50: “. The rest of the article discusses unrelated bac”)
buddie FAIL: quotes 1/3 found, 2 not found
```

The exit code is 1. A wrong digit shows up as a close passage (0.98), an invented sentence as a distant one (0.50).
With `--json receipt.json` the same check is also written as a receipt: an
[in-toto Statement](https://github.com/in-toto/attestation) whose predicate gives each verdict and the snapshot it was
read from. An excerpt:

<!-- doc-receipt: quickstart -->
```json
{
  "predicateType": "https://github.com/tsyyan/buddie#receipt-v0",
  "predicate": {
    "outcome": "FAIL",
    "line": "buddie FAIL: quotes 1/3 found, 2 not found",
    "quotes": [
      {
        "id": "L3.1",
        "verdict": "NOT_FOUND",
        "url": "https://status.example.com/incidents/42",
        "sha256": "cc696ce5cfcc04abf2aeef81f82f0b5a668dd0953f9c9f36c02748ed0fdeb2b1",
        "closest": {"ratio": 0.983, "text": "elevated error rates on the API between 14:59 and 15:41 UTC"}
      }
    ]
  }
}
```

A claim about work, checked against the session's own record of the command:

<!-- doc-example: work -->
```bash
cd buddie/examples/work
buddie verify report.md --transcript session.jsonl --no-github
```

```
BLOCK anchor line 3 ⚓ run:pytest -q => 41 passed: output has no '41 passed'; it ends: ….......................................... 1 failed, 40 passed in 3.1s
note  pr:/ci:/run: anchors show what happened (PR state, checks on a commit, a command and its output), not that the code is correct
buddie FAIL: effects 0/1 hold, 1 broken
```

Both examples print exactly this with 1.1.1 and with 2.0.0, and `tests/test_readme.py` runs them on Linux, macOS and
Windows.

**Checking again.** A receipt names the evidence a verdict rests on: a snapshot's SHA-256, a commit, a check run, the
time. Running the check again reproduces the verdict only while that evidence is unchanged and still at hand. A stored
snapshot can be re-read for as long as you keep it, but a live page, a PR's state or a branch can change, and a session
transcript exists only on the machine that wrote it. The receipt does not contain the page.

## What buddie checks

| The report says | Checked against |
|---|---|
| a quotation, in quotation marks, with its link | the visible text of a SHA-256 snapshot of **that** link |
| a number in a sentence with a link | the same snapshot |
| `⚓ path#sha256` or `⚓ path@commit` | the file in your repository, or at that commit |
| `⚓ pr:OWNER/REPO#N=merged@SHA` | GitHub: the PR's state and merge commit |
| `⚓ ci:OWNER/REPO@SHA=success` | GitHub: every check run and status on that commit |
| `⚓ run:CMD => OUTPUT` | the Claude Code transcript: a call that ran `CMD` and printed `OUTPUT` |
| "step 3 is done", "the user agreed" (opt-in) | the project's task queue, accepted plans and the user's own messages |

The agent writes the anchors, and buddie's [skill](../skills/buddie/SKILL.md) teaches it how. Every result is one of four
outcomes:

| Outcome | Means | Is not |
|---|---|---|
| `PASS` | everything that was checked holds | proof that the report is true |
| `FAIL` | a quotation is not in its source, or an anchor does not hold | a judgement on the rest |
| `GAPS` | something could not be checked, and the receipt names it | a pass |
| `EMPTY` | there was nothing buddie checks | a pass |

A claim buddie does not recognise (paraphrase, work stated without an anchor) is not checked at all. Lines that state
work in prose are listed in the receipt as such, so you can see what went unchecked.

## What you get

| Capability | What it does for you |
|---|---|
| Quotation checks | catch a quote that was altered, invented or taken from another page, with the closest real passage |
| Source snapshots | store each cited page by the SHA-256 of its bytes, so a verdict names exactly what was read |
| Repository anchors | tie "this file" and "that commit" to the bytes in your checkout |
| PR and CI checks | confirm merged or open, passing or failing, on the commit the claim names |
| Execution evidence | confirms that the session transcript shows a command printing what the report says (Claude Code) |
| Typed findings | each blocking item says what failed and why, so the agent can fix or disclose it |
| The gate | returns an answer with a false claim to the agent before you read it, with the reasons (Claude Code, Codex) |
| Verification profiles *(2.0)* | run only the checks you need: `developer`, `research`, `complete` or `custom` |
| Protected policy *(2.0)* | an administrator's file that settings the agent can write cannot weaken |
| Receipt v1 *(2.0)* | adds what ran, what did not and why, coverage and provenance; v0 stays the default |
| Evidence freshness *(2.0)* | says whether CI or repository evidence is about the revision a claim concerns |
| Environment snapshots *(2.0)* | record what buddie itself observed of where a check ran |
| Hardened execution *(2.0)* | no repository code runs; git ignores repository hooks and filters; patterns are time-limited |

<details>
<summary>Which interface has what</summary>

| | Claude Code plugin | Codex plugin | Desktop, stdio MCP | CLI | Remote server |
|---|---|---|---|---|---|
| quotes, numbers | yes | yes | yes | yes | yes |
| `path#`, `path@` | yes | yes, given `repos` | yes, given `repos` | yes | no |
| `pr:`, `ci:` | yes | yes | yes | yes | public repos |
| `run:` | yes | unchecked | unchecked | with `--transcript` | no |
| gate before you read | yes | at `Stop` | no | exit code | no |
| receipt v1 *(2.0)* | MCP tool | MCP tool | yes | `--receipt v1` | no (v0) |
| protected policy *(2.0)* | enforced | enforced | not a gate | not a gate | not a gate |

Every surface in detail: [integrations.md](integrations.md).

</details>

## Research

In 929 checkable quotations from published deep-research reports, **212 (22.8 %) were altered or absent from the page
they cited**; buddie flagged 207 of them. Out of sample, its quote check wrongly reports `NOT_FOUND` for 2.3 % of real
quotations, and for 6.9 % on a new genre (Search Arena answers), mostly words the agent itself put in quotation marks.
The labellers were Claude subagents working blind to the verdicts.

<details>
<summary>The data sets</summary>

| Finding | Result | Data |
|---|---|---|
| quotations altered or absent (o3 Deep Research, Perplexity, Grok, Doubao, Claude 3.7 Sonnet) | 212 of 929 (22.8 %, 95 % CI 20–26 %) | [E008](../results/E008-drb2-fresh), [E010](../results/E010-ydc-o3), [E011](../results/E011-drb1-claude), [E012](../results/E012-search-misses) |
| cited numbers not in their source | 28 of 103 (27.2 %) | [E009](../results/E009-drb1-numbers) |
| false `NOT_FOUND`, out of sample | 10 of 440 (2.3 %) | [method](verbatim-method.md) |
| false `NOT_FOUND`, Search Arena | 29 of 423 (6.9 %) | [E014](../results/E014-search-arena) |
| plugin evals: a false quote, `pr:` or `ci:` claim passed on | the truth reached the person in every trap run with buddie, in none without | [evals](../evals/README.md) |

</details>

Method, limits and how to reproduce: [research.md](research.md).

## GitHub citations

The same report workflow also checks literal quotations and code linked to GitHub files at full commit SHAs,
PR descriptions and addressed diff lines. See [GitHub citations](github-citations.md) for report examples, strict
matching, revision binding, replay, supported Markdown and source limits. A matching quote does not establish the
truth of its surrounding explanation.
