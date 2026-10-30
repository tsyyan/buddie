"""Fetch every unit's source again and keep only units whose label still holds on what can be fetched today.

The labels were made against snapshots that are not redistributed. For each source URL this fetches the page
directly and, when that fails or the page changed, from the web archive (buddie's access cascade). A unit is
ELIGIBLE when the independent matcher (common.in_text) agrees with its blind label on the chosen snapshot:

- OK: the quote is in the page text;
- ERROR, altered: the quote is not in the page text, and the labeller's evidence (the source's real words) is;
- ERROR, absent: the quote is not in the page text, and the page has readable text.

Stratum SAME: the chosen snapshot has the SHA-256 the labels were made on; STABLE: different bytes, label still holds.
Everything else is excluded with a reason. The curated store (--store) gets exactly one snapshot per URL, the chosen
one, so the arms, buddie in arm C and the judge all read the same bytes.

    python refetch.py --units data/units.json --raw data/raw-store --store data/store --out data/eligible.json
"""
from __future__ import annotations

import argparse
from collections import Counter

from common import in_text, read_json, write_json

MIN_CHARS = 500


def consistent(unit: dict, text: str | None) -> tuple[bool, str]:
    if not text or len(text) < MIN_CHARS:
        return False, "unreadable"
    found = in_text(unit["quote"], text)
    if unit["gold"] == "OK":
        return (True, "ok") if found else (False, "ok_quote_not_matched")
    if found:
        return False, "error_quote_now_matched"
    if unit["label"] == "AGENT_ALTERED" and unit.get("evidence") and not in_text(unit["evidence"], text):
        return False, "evidence_not_matched"
    return True, "ok"


def candidates(raw, url: str) -> list[dict]:
    return [e for e in raw.index().get(url, []) if e.get("sha256")]


def main(argv=None) -> int:
    import os
    os.environ.setdefault("VERBATIM_CC_CRAWLS", "3")  # the newest crawls only: 24 take minutes per page
    from buddie.verbatim import access
    from buddie.verbatim.store import Store
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--units", required=True)
    ap.add_argument("--raw", required=True, help="every fetched snapshot")
    ap.add_argument("--store", required=True, help="curated: one chosen snapshot per URL")
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", help="comma-separated unit ids (a pilot subset)")
    ap.add_argument("--sample", type=int, help="a seeded, stratified pool of this many units (a pilot)")
    ap.add_argument("--seed", type=int, default=20261030)
    ap.add_argument("--no-archive", action="store_true")
    a = ap.parse_args(argv)
    units = read_json(a.units)["units"]
    if a.only:
        keep = set(a.only.split(","))
        units = [u for u in units if u["id"] in keep]
    if a.sample:
        import random
        rng = random.Random(a.seed)
        err = [u for u in units if u["gold"] == "ERROR"]
        good = [u for u in units if u["gold"] == "OK"]
        rng.shuffle(err)
        rng.shuffle(good)
        n_good = min(len(good), max(a.sample // 3, round(a.sample * len(good) / len(units))))
        units = err[:a.sample - n_good] + good[:n_good]
    raw, curated = Store(a.raw), Store(a.store)
    fetched: set[str] = set()
    archived: set[str] = set()
    rows = []
    for i, u in enumerate(units, 1):
        url = u["url"].split("#", 1)[0]
        if url not in fetched:
            fetched.add(url)
            if not candidates(raw, url):
                raw.fetch(url, timeout=20)
        # the web archive only when no snapshot we have bears the label out (it is slow, and a capture may be of
        # another time than the label)
        if not a.no_archive and not any(consistent(u, _text(raw, e))[0] for e in candidates(raw, url)) \
                and url not in archived:
            archived.add(url)
            try:
                access.archive(raw, url)
            except Exception as error:  # noqa: BLE001 - recorded, the unit is then judged on what exists
                print("archive failed", url, str(error)[:80])
        print(f"[{i}/{len(units)}] {u['id']}", flush=True)
        options = candidates(raw, url)
        # the labelled bytes first, then direct fetches before archive captures, newest first
        options.sort(key=lambda e: (e["sha256"] != u.get("labelled_sha256"), e.get("via") == "archive",
                                    -len(e.get("fetched_at") or "")))
        chosen, reason = None, "no_snapshot"
        for e in options:
            text = _text(raw, e)
            ok, reason = consistent(u, text)
            if ok:
                chosen = e
                break
        row = {"id": u["id"], "url": url, "gold": u["gold"], "eligible": bool(chosen), "reason": reason}
        if chosen:
            row |= {"sha256": chosen["sha256"], "via": chosen.get("via") or "direct",
                    "stratum": "SAME" if chosen["sha256"] == u.get("labelled_sha256") else "STABLE"}
            if not any(e["sha256"] == chosen["sha256"] for e in candidates(curated, url)):
                if candidates(curated, url):
                    row |= {"eligible": False, "reason": "url_has_another_chosen_snapshot"}
                else:
                    curated.add(url, raw.read(chosen["sha256"]), content_type=chosen.get("content_type"),
                                content_encoding=chosen.get("content_encoding"), fetched_at=chosen.get("fetched_at"),
                                final_url=chosen.get("final_url"), via=row["via"])
        rows.append(row)
    write_json(a.out, {"schema": "bdx-003/eligible-v1", "rows": rows})
    print("eligible", sum(r["eligible"] for r in rows), "of", len(rows),
          dict(Counter((r["gold"], r.get("stratum") or r["reason"]) for r in rows)))
    return 0


def _text(store, entry: dict) -> str | None:
    from buddie.verbatim.textlayer import Unreadable, layers
    try:
        return layers(store.read(entry["sha256"]), entry.get("content_type"), entry.get("content_encoding"))["visible"]
    except (Unreadable, OSError, KeyError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
