"""One report in, one receipt out: quotes through verbatim, state anchors through anchors.py, claims about the course
of work (step done, next step auto, user agreed) through mandate.py when the repo has a buddie.toml.

The receipt is an in-toto Statement (audit/06, I; audit/08 §4.1): the subject is the sha256 of the report text, the
predicate holds every verdict with the snapshot hash it was judged on, so anyone with the bytes can re-check it
without this code.

Outcome, for whoever accepts the report (an orchestrator, a hook before the final answer):
  FAIL      a quote is NOT_FOUND in its own readable source, an anchor (state, or effect: pr:, ci:, run:) is
            BROKEN, or a work claim contradicts the queue or the user's messages: do not pass it on as is
  GAPS      nothing is wrong, but something could not be checked (source unavailable, quote without a link,
            uncertain miss, anchor in a repo we do not have): say so when passing it on
  PASS      every quote and every anchor checked out
  EMPTY     nothing to check: no quotes, no anchors, no work claims

Numbers and dates of cited sentences ("valued at $3.4 billion in 2022 ([Zion](url))") go through verbatim.numbers
(NEXT №42): a number NOT_FOUND on the sentence's readable source is a gap by default (`numbers="gap"`) and blocks with
`numbers="fail"`; E009/E015 measure how often that is the agent's error. NO_CONTEXT and SOURCE_UNAVAILABLE are gaps
in either mode: the number was not checked to the end, so it cannot pass.
A miss on an abstract page or on a market report rewritten for a later forecast horizon is UNCERTAIN (verbatim 0.3.6,
NEXT №66): a gap in either mode, never blocking.

Lines that state a count ("73 из 84", "11 %") with no anchor are listed under "unanchored": a reader's signal that
a number travels without a source (E003), never a failure. A line whose quote is FOUND on the page at a URL written
on that same line already carries its source (NEXT №71, E016 de7a5d): it is listed under "quote_backed", not there. Lines that claim work done ("слито", "CI зелёный", "тесты
прошли") with no pr:/ci:/run: anchor are listed under "prose_work" the same way (NEXT №43), their numbers under
"prose_lines"; the hook returns a final answer for them (NEXT №63).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from buddie import __version__, core
from buddie import anchors as anc
from buddie import effects as eff
from buddie import findings as fnd
from buddie import mandate as man
from buddie import modules as mods

PREDICATE = "https://github.com/tsyyan/buddie#receipt-v0"  # the receipt format is described in the public repo
FOUND = {"FOUND", "FOUND_NORMALIZED"}
# What each verdict means: the tables live in findings.py (core.Fact per verdict, exhaustive, an unknown word is
# never support); these names stay for the code and tests that read them here.
QUOTE_OUTCOME, NUMBER_OUTCOME = fnd.QUOTE_FACTS, fnd.NUMBER_FACTS
CONTRADICTED, OPEN = core.Fact.CONTRADICTED, (core.Fact.UNDETERMINED, core.Fact.UNRECOGNIZED)
KEEP = ("id", "line", "quote", "url", "verdict", "sha256", "fetched_at", "via", "provenance", "visible_offset",
        "raw_offset", "doubts", "error", "found_in", "archived_at", "first_read")


def _quote_row(r: dict) -> dict:
    row = {k: r[k] for k in KEEP if r.get(k) not in (None, [], "")}
    if not row.get("url") and r.get("urls"):
        row["url"] = r["urls"][0]
    if r.get("closest", {}).get("text"):
        row["closest"] = {"ratio": round(r["closest"]["ratio"], 3), "text": r["closest"]["text"][:200]}
    return row


def check_quotes(text: str, *, store=None, fetch: bool = True, access: str | None = None,
                 min_chars: int = 12) -> tuple[list[dict], int, str]:
    from buddie.verbatim import __version__ as vv
    from buddie.verbatim.access import parse
    from buddie.verbatim.check import check_claims
    from buddie.verbatim.report import from_markdown
    from buddie.verbatim.store import Store
    claims, skipped = from_markdown(text, min_chars)
    store = store if isinstance(store, Store) else Store(store)
    results = check_claims(claims, store, fetch=fetch, access=parse(access)) if claims else []
    return results, skipped, vv


def check_numbers(text: str, *, store=None, fetch: bool = True) -> list[dict]:
    from buddie.verbatim.numbers import check_report
    from buddie.verbatim.store import Store
    keep = ("id", "line", "text", "kind", "verdict", "url", "sha256", "match", "near_words", "sentence", "doubts")
    store = store if isinstance(store, Store) else Store(store)
    return [{k: r[k] for k in keep if r.get(k) not in (None, "")} for r in check_report(text, store, fetch=fetch)]


def outcome(quotes: list[dict], anchors: list[dict], claims: list[dict] = (), numbers: list[dict] = (),
            numbers_mode: str = "gap") -> str:
    """receipt-v0's outcome for these rows: core.v0_outcome of their findings under the numbers mode's policy."""
    return core.v0_outcome(fnd.from_rows(quotes, anchors, claims, numbers), core.Policy(numbers_mode == "fail"))


def blocking_findings(found: list[core.Finding], numbers: str = "gap") -> list[core.Finding]:
    """The findings behind predicate.blocking, one per item and in its order (quotes, anchors, work claims, numbers
    in numbers="fail" mode), so a gate can take each item's check from the finding instead of from its words."""
    def contradicted(*checks):
        return [f for f in found if f.check in checks and f.fact is CONTRADICTED]
    anchor_checks = [c for c in core.Check if c.name.endswith("_ANCHOR")]
    return (contradicted(core.Check.QUOTE) + contradicted(*anchor_checks) + contradicted(core.Check.WORK_CLAIM)
            + (contradicted(core.Check.NUMBER) if numbers == "fail" else []))


def quote_backed(text: str, rows: list[dict]) -> list[int]:
    """Lines with a quote FOUND on the page whose URL is written on the same line: their numbers have a source.
    A quote's `line` is the first line of its paragraph, so the paragraph's lines are searched for the one holding
    both the start of the quote and the URL."""
    lines, out = text.splitlines(), set()
    for r in rows:
        if r["verdict"] not in FOUND or not r.get("url") or not r.get("line"):
            continue
        head = " ".join(r["quote"].split())[:40]
        for n in range(r["line"], len(lines) + 1):
            if not lines[n - 1].strip():
                break
            if r["url"] in lines[n - 1] and head in " ".join(lines[n - 1].split()):
                out.add(n)
    return sorted(out)


def _count(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items()))


def verify(text: str, *, name: str = "report", repos: list[Path] | None = None, store=None,
           fetch: bool = True, access: str | None = None, quotes: bool = True, now: str | None = None,
           mandate: dict | None | bool = True, rev: str | None = None, github=None,
           transcript: str | None = None, numbers: str = "gap") -> dict:
    """The receipt (receipt-v0) for `text`, every module run; see assess_selected for the arguments."""
    return assess(text, name=name, repos=repos, store=store, fetch=fetch, access=access, quotes=quotes, now=now,
                  mandate=mandate, rev=rev, github=github, transcript=transcript, numbers=numbers)[0]


def assess(text: str, *, name: str = "report", repos: list[Path] | None = None, store=None,
           fetch: bool = True, access: str | None = None, quotes: bool = True, now: str | None = None,
           mandate: dict | None | bool = True, rev: str | None = None, github=None,
           transcript: str | None = None, numbers: str = "gap") -> tuple[dict, list[core.Finding], core.Coverage]:
    """assess_selected with every module: verify's own arguments, as they were before modules existed."""
    return assess_selected(text, None, name=name, repos=repos, store=store, fetch=fetch, access=access,
                           quotes=quotes, now=now, mandate=mandate, rev=rev, github=github, transcript=transcript,
                           numbers=numbers)


def assess_selected(text: str, modules=None, *, name: str = "report", repos: list[Path] | None = None, store=None,
                    fetch: bool = True, access: str | None = None, quotes: bool = True, now: str | None = None,
                    mandate: dict | None | bool = True, rev: str | None = None, github=None,
                    transcript: str | None = None, numbers: str = "gap", profile: str | None = None,
                    checks=None, selection=None) -> tuple[dict, list[core.Finding], core.Coverage]:
    """assessment()'s receipt-v0, findings and coverage. profile, modules, checks: what to run (buddie/profiles.py:
    developer, research, complete, or custom with modules and/or checks); none of them: every check, as before
    profiles. An unknown name raises profiles.UnknownProfile. selection: a profiles.Selection already resolved
    instead (the hook's effective one, which may hold no check: then none runs)."""
    got = assessment(text, modules, name=name, repos=repos, store=store, fetch=fetch, access=access, quotes=quotes,
                     now=now, mandate=mandate, rev=rev, github=github, transcript=transcript, numbers=numbers,
                     profile=profile, checks=checks, selection=selection)
    return got.receipt, list(got.findings), got.coverage


@dataclass(frozen=True)
class Assessment:
    """One check of one text, computed once; buddie/receipts.py renders it as receipt-v0 (`receipt`, as verify()
    always gave it) or receipt-v1. Nothing here is recomputed for a rendering, and no rendering changes it."""
    receipt: dict                          # receipt-v0
    findings: tuple                        # core.Finding, in the receipt's order
    coverage: core.Coverage
    requested: object                      # profiles.Selection asked for (None: none, so everything)
    effective: object                      # profiles.Selection run after levels and floors (None: everything)
    executed: frozenset                    # core.Check whose checker ran
    not_run: tuple                         # (core.Check, why) for every other check: selection, call_option,
                                           # unavailable (receipts.py tells profile from gate_level)
    detected: tuple                        # (core.Check, n): claims of that kind the text holds, where countable
    numbers: str                           # the numbers mode the findings were decided under


def assessment(text: str, modules=None, *, name: str = "report", repos: list[Path] | None = None, store=None,
               fetch: bool = True, access: str | None = None, quotes: bool = True, now: str | None = None,
               mandate: dict | None | bool = True, rev: str | None = None, github=None,
               transcript: str | None = None, numbers: str = "gap", profile: str | None = None, checks=None,
               selection=None, requested=None) -> Assessment:
    """The Assessment of `text` under one reading of the protected policy (the event's inside the hook, its own
    outside), so the GitHub API asked and the one a finding's provenance names are the same. Arguments as
    assess_selected; requested: the profile asked for when `selection` is what it came to (the hook's
    ResolvedEventContext.profile and .effective()), else the selection itself."""
    from buddie import policy, profiles
    if selection is None:
        selection = profiles.resolve(profile, modules, checks)
    elif profile is not None or modules is not None or checks is not None:
        raise profiles.UnknownProfile("give a selection or a profile with its modules and checks, not both")
    with policy.held():
        receipt, found, covered, ran = _assess(text, selection, name=name, repos=repos, store=store, fetch=fetch,
                                               access=access, quotes=quotes, now=now, mandate=mandate, rev=rev,
                                               github=github, transcript=transcript, numbers=numbers)
    return Assessment(receipt, tuple(found), covered, requested if requested is not None else selection, selection,
                      **ran)


def _assess(text: str, selection=None, *, name: str = "report", repos: list[Path] | None = None, store=None,
            fetch: bool = True, access: str | None = None, quotes: bool = True, now: str | None = None,
            mandate: dict | None | bool = True, rev: str | None = None, github=None,
            transcript: str | None = None,
            numbers: str = "gap") -> tuple[dict, list[core.Finding], core.Coverage]:
    """The receipt for `text`, with the typed findings (core.Finding) its outcome comes from and the coverage
    (core.Coverage: what was not judged, and why); the findings stay internal, receipt-v0 is unchanged. repos: where state anchors are resolved (default: none, so they are UNCHECKABLE).
    mandate: claims about the course of work, judged by the config of the first repo with buddie.toml (True), by
    the given config (dict), or not at all (False/None); rev: the commit whose queue the claims are judged against.
    github: GET function for pr:/ci: anchors (effects.github_get; None leaves them UNCHECKABLE); transcript: the
    Claude Code session jsonl for run: anchors. numbers: "gap" (a number NOT_FOUND in its readable source is a gap),
    "fail" (it blocks) or "off". selection: the profiles.Selection to run (None: every check); the checks it leaves
    out are not run, and Coverage names them with the claims of those kinds the text holds."""
    from datetime import datetime, timezone

    from buddie import evidence
    from buddie.verbatim.store import Store
    asked_mandate = mandate  # the call's own option, before a selection without work claims turns it off
    selected = selection.modules if selection is not None else mods.REGISTRY
    on = selection.checks if selection is not None else mods.checks(mods.REGISTRY)
    clean = evidence.network_clean()  # asked again after the check: a collector may start or end meanwhile
    run_numbers = quotes and core.Check.NUMBER in on  # quotes=False (anchors only) has always meant no numbers
    quotes = quotes and core.Check.QUOTE in on
    numbers = numbers if run_numbers else "off"
    if core.Check.WORK_CLAIM not in on:
        mandate = False
    store = store if isinstance(store, Store) else Store(store)  # one instance: what it fetched is known (collected)
    # what this check fetched counts as collected only with buddie's own store classes (a subclass may record any
    # bytes as fetched) and only what was added to `collected` during the check (a caller may fill it beforehand)
    from buddie.stores import UnionStore
    own_store = type(store) in (Store, UnionStore) and type(store.collected) is set
    before = frozenset(store.collected) if own_store else frozenset()
    q_results, skipped, vv = check_quotes(text, store=store, fetch=fetch, access=access) if quotes else ([], 0, None)
    keep = None if selected == mods.REGISTRY else (lambda a: fnd.anchor_check(a) in on)
    a_results = anc.check_text(text, repos or [], {"github": github, "transcript": transcript}, keep=keep)
    prose, prose_examples = eff.prose_work(text, anc.ANCHOR)
    # words in quotation marks with no link and no speaker are a term or an example, not a citation (134 of 164
    # unlinked "quotes" in lab's own reports): counted, not judged
    terms = sum(r["verdict"] == "NO_SOURCE" and not r.get("attributed", True) for r in q_results)
    rows = [_quote_row(r) for r in q_results if r["verdict"] != "NO_SOURCE" or r.get("attributed", True)]
    backed = quote_backed(text, rows)
    bare, bare_examples = anc.unanchored(text, backed=backed)
    cfg = man.find_config(repos or []) if mandate is True else (mandate or None)
    claims = man.check_text(text, cfg, rev) if cfg else []
    n_rows = check_numbers(text, store=store, fetch=fetch) if numbers != "off" else []
    clean = clean and evidence.network_clean()
    observed = frozenset(store.collected) - before if clean and own_store else frozenset()
    found = fnd.from_rows(rows, a_results, claims, n_rows, observed=observed,
                          github_collected=clean and eff.own_get(github))
    result = core.v0_outcome(found, core.Policy(numbers == "fail"))
    covered = fnd.coverage(found, quotes=quotes, numbers=numbers, mandate_off=mandate is False or mandate is None,
                           mandate_config=cfg is not None, short_quotes=skipped, unlinked_terms=terms,
                           unanchored_lines=bare, prose_claims=prose,
                           modules_off=[m.id for m in mods.REGISTRY if m not in selected],
                           excluded=_excluded(text, selection))
    blocking = [f"quote {r['id']} not found in {r.get('url')}: “{r['quote'][:120]}”"
                + (f" (closest {r['closest']['ratio']:.2f}: “{r['closest']['text'][:120]}”)" if r.get("closest") else "")
                for r in rows if fnd.quote_fact(r["verdict"]) is CONTRADICTED]
    blocking += [f"anchor line {a['line']} ⚓ {a['anchor']}: {a.get('why')}" for a in a_results if a["status"] == anc.BROKEN]
    gaps = [f"quote {r['id']} {r['verdict']}" + (f" ({', '.join(r['doubts'])})" if r.get("doubts") else "")
            + (f": {r['url']}" if r.get("url") else "") for r in rows if fnd.quote_fact(r["verdict"]) in OPEN]
    gaps += [f"anchor line {a['line']} ⚓ {a['anchor']}: {a.get('why')}" for a in a_results if a["status"] == anc.UNCHECKABLE]
    gaps += [f"anchor line {a['line']} ⚓ {a['anchor']}: unknown status {a['status']}" for a in a_results
             if fnd.status_fact(a["status"]) is core.Fact.UNRECOGNIZED]
    blocking += [f"{c['kind']} line {c['line']}: {c.get('why')}" for c in claims if c["status"] == man.BROKEN]
    gaps += [f"{c['kind']} line {c['line']} {c['status']}: {c.get('why')}" for c in claims
             if c["status"] in (man.UNSUPPORTED, man.UNCHECKABLE)
             or fnd.status_fact(c["status"]) is core.Fact.UNRECOGNIZED]
    missing = [f"number {n['id']} “{n['text']}” not found in {n.get('url')}" for n in n_rows
               if fnd.number_fact(n["verdict"]) is CONTRADICTED]
    (blocking if numbers == "fail" else gaps).extend(missing)
    gaps += [f"number {n['id']} “{n['text']}” {n['verdict']}" + (f" ({', '.join(n['doubts'])})" if n.get("doubts") else "")
             + f": {n.get('url')}" for n in n_rows if fnd.number_fact(n["verdict"]) in OPEN]
    receipt = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": name, "digest": {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}}],
        "predicateType": PREDICATE,
        "predicate": {
            "tool": {"buddie": __version__, "verbatim": vv},
            "checked_at": now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "outcome": result,
            "line": line(result, rows, a_results, skipped, bare, claims, prose, n_rows),
            "summary": {"quotes": _count(r["verdict"] for r in rows), "short_quotes_skipped": skipped,
                        "unlinked_terms": terms, "numbers": _count(n["verdict"] for n in n_rows),
                        "anchors": _count(a["status"] for a in a_results), "unanchored_count_lines": bare,
                        "mandate": _count(f"{c['kind']}:{c['status']}" for c in claims),
                        "work": {"anchored": sum(1 for a in a_results if a.get("kind")),
                                 "broken": sum(1 for a in a_results if a.get("kind") and a["status"] == anc.BROKEN),
                                 "prose": prose}},
            "notes": [eff.NOTE] if any(a.get("kind") in ("ci", "run") for a in a_results) else [],
            "unanchored": bare_examples,
            "quote_backed": backed,
            "prose_work": prose_examples,
            "prose_lines": eff.prose_lines(text, anc.ANCHOR),
            "blocking": blocking,
            "gaps": gaps,
            "quotes": rows,
            "numbers": n_rows,
            "anchors": a_results,
            "mandate": claims,
        },
    }
    ran = {c for c in on if c.name.endswith("_ANCHOR")}  # anchors of a selected kind are always parsed and judged
    ran |= {core.Check.QUOTE} if quotes else set()
    ran |= {core.Check.NUMBER} if numbers != "off" else set()
    ran |= {core.Check.WORK_CLAIM} if core.Check.WORK_CLAIM in on and cfg is not None else set()
    not_run = []
    for c in core.Check:
        if c in ran:
            continue
        if c not in on:
            why = "selection"
        elif c is core.Check.WORK_CLAIM and asked_mandate not in (False, None) and cfg is None:
            why = "unavailable"  # asked for, but no buddie.toml [mandate] says what the queue is
        else:
            why = "call_option"  # quotes=False (anchors only), numbers="off", mandate=False
        not_run.append((c, why))
    detected = tuple(sorted(_detected(text).items(), key=lambda kv: list(core.Check).index(kv[0])))
    return receipt, found, covered, {"executed": frozenset(ran), "not_run": tuple(not_run), "detected": detected,
                                     "numbers": numbers}


def _detected(text: str) -> dict:
    """Claims of each countable kind the text holds, without checking them: quotations (verbatim's own reading of
    a report) and anchors by kind. Numbers and work claims are not counted here: what counts as one takes the check."""
    from buddie.verbatim.report import from_markdown
    # every countable kind gets a count, 0 included: an absent kind is "none in the text", not "cannot tell"
    out: dict = {c: 0 for c in core.Check if c is core.Check.QUOTE or c.name.endswith("_ANCHOR")}
    out[core.Check.QUOTE] = len(from_markdown(text, 12)[0])
    for found in (anc.ANCHOR.findall(line) for line in text.splitlines()):
        for a in found:
            out[fnd.anchor_check(a)] = out.get(fnd.anchor_check(a), 0) + 1
    return out


def _excluded(text: str, selection) -> list[tuple[str, str, int | None]]:
    """What a selection leaves out, for Coverage: each check off in a module that is otherwise selected, and the
    claims of the left-out kinds this text holds (quotations, anchors), counted without checking them, so that a
    smaller check says what it did not look at."""
    if selection is None:
        return []
    out = [(f"check:{c.value}", f"not in profile {selection.profile}", None) for c in core.Check
           if c not in selection.checks and any(c in m.checks for m in selection.modules)]
    if core.Check.QUOTE not in selection.checks:
        from buddie.verbatim.report import from_markdown
        if n := len(from_markdown(text, 12)[0]):
            out.append(("excluded:quote", f"quotations in the text, not checked (profile {selection.profile})", n))
    anchors: dict[str, int] = {}
    for found in (anc.ANCHOR.findall(line) for line in text.splitlines()):
        for a in found:
            if (kind := fnd.anchor_check(a)) not in selection.checks:
                anchors[kind.value] = anchors.get(kind.value, 0) + 1
    out += [(f"excluded:{k}", f"anchors in the text, not checked (profile {selection.profile})", n)
            for k, n in sorted(anchors.items())]
    return out


def line(result: str, rows: list[dict], anchors: list[dict], skipped: int = 0, bare: int = 0,
         claims: list[dict] = (), prose: int = 0, numbers: list[dict] = ()) -> str:
    """The one line an orchestrator puts next to a report it passes on."""
    ok = sum(r["verdict"] in ("FOUND", "FOUND_NORMALIZED") for r in rows)
    effects = [a for a in anchors if a.get("kind")]
    anchors = [a for a in anchors if not a.get("kind")]
    held = sum(a["status"] == anc.HOLDS for a in anchors)
    parts = []
    if rows:
        miss = sum(r["verdict"] == "NOT_FOUND" for r in rows)
        parts.append(f"quotes {ok}/{len(rows)} found" + (f", {miss} not found" if miss else ""))
    if numbers:
        miss = sum(n["verdict"] == "NOT_FOUND" for n in numbers)
        parts.append(f"numbers {sum(n['verdict'].startswith('FOUND') for n in numbers)}/{len(numbers)} found"
                     + (f", {miss} not found" if miss else ""))
    if anchors:
        broken = sum(a["status"] == anc.BROKEN for a in anchors)
        parts.append(f"anchors {held}/{len(anchors)} hold" + (f", {broken} broken" if broken else ""))
    if effects:
        broken = sum(a["status"] == anc.BROKEN for a in effects)
        parts.append(f"effects {sum(a['status'] == anc.HOLDS for a in effects)}/{len(effects)} hold"
                     + (f", {broken} broken" if broken else ""))
    if claims:
        broken = sum(c["status"] == man.BROKEN for c in claims)
        parts.append(f"work claims {sum(c['status'] == man.HOLDS for c in claims)}/{len(claims)} hold"
                     + (f", {broken} broken" if broken else ""))
    if bare:
        parts.append(f"{bare} lines with counts and no anchor")
    if prose:
        parts.append(f"{prose} work claims in prose")
    return f"buddie {result}: " + ("; ".join(parts) or "nothing to check")
