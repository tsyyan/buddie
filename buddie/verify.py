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

Lines that state a count ("73 из 84", "11 %") with no anchor are listed under "unanchored": a reader's signal that
a number travels without a source (E003), never a failure. Lines that claim work done ("слито", "CI зелёный", "тесты
прошли") with no pr:/ci:/run: anchor are listed under "prose_work" the same way (NEXT №43).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from buddie import __version__
from buddie import anchors as anc
from buddie import effects as eff
from buddie import mandate as man

PREDICATE = "https://github.com/tsyyan/buddie#receipt-v0"  # the receipt format is described in the public repo
QUOTE_GAPS = {"UNCERTAIN", "SOURCE_UNAVAILABLE", "NO_SOURCE", "HIDDEN_ONLY", "FOUND_IN_COPY"}
KEEP = ("id", "line", "quote", "url", "verdict", "sha256", "fetched_at", "via", "provenance", "visible_offset",
        "raw_offset", "doubts", "error", "found_in", "archived_at", "first_read")


def _quote_row(r: dict) -> dict:
    row = {k: r[k] for k in KEEP if r.get(k) not in (None, [], "")}
    if not row.get("url") and r.get("urls"):
        row["url"] = r["urls"][0]
    if r.get("closest", {}).get("text"):
        row["closest"] = {"ratio": round(r["closest"]["ratio"], 3), "text": r["closest"]["text"][:200]}
    return row


def check_quotes(text: str, *, store: str | None = None, fetch: bool = True, access: str | None = None,
                 min_chars: int = 12) -> tuple[list[dict], int, str]:
    from verbatim import __version__ as vv
    from verbatim.access import parse
    from verbatim.check import check_claims
    from verbatim.report import from_markdown
    from verbatim.store import Store
    claims, skipped = from_markdown(text, min_chars)
    results = check_claims(claims, Store(store), fetch=fetch, access=parse(access)) if claims else []
    return results, skipped, vv


def outcome(quotes: list[dict], anchors: list[dict], claims: list[dict] = ()) -> str:
    if not quotes and not anchors and not claims:
        return "EMPTY"
    if any(q["verdict"] == "NOT_FOUND" for q in quotes) or any(a["status"] == anc.BROKEN for a in anchors) \
            or any(c["status"] == man.BROKEN for c in claims):
        return "FAIL"
    if any(q["verdict"] in QUOTE_GAPS for q in quotes) or any(a["status"] == anc.UNCHECKABLE for a in anchors) \
            or any(c["status"] in (man.UNSUPPORTED, man.UNCHECKABLE) for c in claims):
        return "GAPS"
    return "PASS"


def _count(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items()))


def verify(text: str, *, name: str = "report", repos: list[Path] | None = None, store: str | None = None,
           fetch: bool = True, access: str | None = None, quotes: bool = True, now: str | None = None,
           mandate: dict | None | bool = True, rev: str | None = None, github=None,
           transcript: str | None = None) -> dict:
    """The receipt for `text`. repos: where state anchors are resolved (default: none, so they are UNCHECKABLE).
    mandate: claims about the course of work, judged by the config of the first repo with buddie.toml (True), by
    the given config (dict), or not at all (False/None); rev: the commit whose queue the claims are judged against.
    github: GET function for pr:/ci: anchors (effects.github_get; None leaves them UNCHECKABLE); transcript: the
    Claude Code session jsonl for run: anchors."""
    from datetime import datetime, timezone
    q_results, skipped, vv = check_quotes(text, store=store, fetch=fetch, access=access) if quotes else ([], 0, None)
    a_results = anc.check_text(text, repos or [], {"github": github, "transcript": transcript})
    bare, bare_examples = anc.unanchored(text)
    prose, prose_examples = eff.prose_work(text, anc.ANCHOR)
    # words in quotation marks with no link and no speaker are a term or an example, not a citation (134 of 164
    # unlinked "quotes" in lab's own reports): counted, not judged
    terms = sum(r["verdict"] == "NO_SOURCE" and not r.get("attributed", True) for r in q_results)
    rows = [_quote_row(r) for r in q_results if r["verdict"] != "NO_SOURCE" or r.get("attributed", True)]
    cfg = man.find_config(repos or []) if mandate is True else (mandate or None)
    claims = man.check_text(text, cfg, rev) if cfg else []
    result = outcome(rows, a_results, claims)
    blocking = [f"quote {r['id']} not found in {r.get('url')}: “{r['quote'][:120]}”"
                + (f" (closest {r['closest']['ratio']:.2f}: “{r['closest']['text'][:120]}”)" if r.get("closest") else "")
                for r in rows if r["verdict"] == "NOT_FOUND"]
    blocking += [f"anchor line {a['line']} ⚓ {a['anchor']}: {a.get('why')}" for a in a_results if a["status"] == anc.BROKEN]
    gaps = [f"quote {r['id']} {r['verdict']}" + (f" ({', '.join(r['doubts'])})" if r.get("doubts") else "")
            + (f": {r['url']}" if r.get("url") else "") for r in rows if r["verdict"] in QUOTE_GAPS]
    gaps += [f"anchor line {a['line']} ⚓ {a['anchor']}: {a.get('why')}" for a in a_results if a["status"] == anc.UNCHECKABLE]
    blocking += [f"{c['kind']} line {c['line']}: {c.get('why')}" for c in claims if c["status"] == man.BROKEN]
    gaps += [f"{c['kind']} line {c['line']} {c['status']}: {c.get('why')}" for c in claims
             if c["status"] in (man.UNSUPPORTED, man.UNCHECKABLE)]
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": name, "digest": {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}}],
        "predicateType": PREDICATE,
        "predicate": {
            "tool": {"buddie": __version__, "verbatim": vv},
            "checked_at": now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "outcome": result,
            "line": line(result, rows, a_results, skipped, bare, claims, prose),
            "summary": {"quotes": _count(r["verdict"] for r in rows), "short_quotes_skipped": skipped,
                        "unlinked_terms": terms,
                        "anchors": _count(a["status"] for a in a_results), "unanchored_count_lines": bare,
                        "mandate": _count(f"{c['kind']}:{c['status']}" for c in claims),
                        "work": {"anchored": sum(1 for a in a_results if a.get("kind")),
                                 "broken": sum(1 for a in a_results if a.get("kind") and a["status"] == anc.BROKEN),
                                 "prose": prose}},
            "notes": [eff.NOTE] if any(a.get("kind") in ("ci", "run") for a in a_results) else [],
            "unanchored": bare_examples,
            "prose_work": prose_examples,
            "blocking": blocking,
            "gaps": gaps,
            "quotes": rows,
            "anchors": a_results,
            "mandate": claims,
        },
    }


def line(result: str, rows: list[dict], anchors: list[dict], skipped: int = 0, bare: int = 0,
         claims: list[dict] = (), prose: int = 0) -> str:
    """The one line an orchestrator puts next to a report it passes on."""
    ok = sum(r["verdict"] in ("FOUND", "FOUND_NORMALIZED") for r in rows)
    effects = [a for a in anchors if a.get("kind")]
    anchors = [a for a in anchors if not a.get("kind")]
    held = sum(a["status"] == anc.HOLDS for a in anchors)
    parts = []
    if rows:
        miss = sum(r["verdict"] == "NOT_FOUND" for r in rows)
        parts.append(f"quotes {ok}/{len(rows)} found" + (f", {miss} not found" if miss else ""))
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
