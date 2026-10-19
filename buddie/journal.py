"""The gate as a closed loop (audit/13 §4.1, NEXT №55): no word of it is written by the model.

1. How a returned message got through. When the gate returns a message (exit 2), the hook keeps the lines it
   flagged (local state, never the shared journal); the next attempt of the same tool in the same session is
   compared with them, and the journal line of that attempt gets `gate`: per flagged item `proved` (the line is
   still there and now carries its proof: an anchor, a quote that matches), `removed` (the claim is gone), `kept`
   (still flagged), and the way the gate was passed: proof, removal, mixed, disclosure (a `buddie:` line), returned
   (sent back again) or other. Trust needs passes through proof, not through deleting the claim.
2. Lessons at session start. `lessons()` sums the journal of past sessions: what the gate returned messages for,
   most frequent first, each with a line that passes (a template from this code). The SessionStart hook prints it
   into the new session's context; at most ten lines.
3. `measure()`: over the first N sessions since a time, the share of sessions whose first gated message was not
   returned, and the share of passes after a return that went through proof rather than removal.

Journal lines written before 0.5 have no `reasons`: a returned FAIL counts as `fail`, a returned final answer as
`final`.
"""
from __future__ import annotations

import difflib
import json
import os
import re
from pathlib import Path

from buddie.anchors import ANCHOR, counts

# kind of a return -> what it is, and a line that passes
REASONS = {
    "final_no_anchor": ("final answer with no anchor",
                        "end the result line with `⚓ pr:OWNER/REPO#N=merged@<sha>` or `⚓ run:<command> => <output>`"),
    "final_bare": ("number with no anchor in a final answer",
                   "<number> `⚓ run:<command> => <output line with the number>` (or `⚓ path@<commit>`)"),
    "prose": ("work claimed in prose with no pr:/ci:/run: anchor in a final answer",
              "end the line with `⚓ pr:OWNER/REPO#N=merged@<sha>`, `⚓ ci:OWNER/REPO@<sha>=success` or "
              "`⚓ run:<command> => <output>`, or drop the claim"),
    "quote": ("quote not found in its source",
              "copy the quote from the snapshot text (buddie source_text URL): “…” ([source](URL))"),
    "anchor": ("anchor no longer holds",
               "refresh it: `⚓ path@<commit>`, `⚓ path#<sha256 now>`, `⚓ pr:OWNER/REPO#N=<state now>`"),
    "work": ("work claim contradicts the queue or the user's messages",
             "state the row's status as NEXT.md has it on main, with its anchor"),
    "number": ("number not found in its cited source", "copy the number from the snapshot text, or drop the link"),
    "context": ("reply past 200k tokens of context that is not the result",
                "hand in the result with «Следующий шаг:», or keep the reply with "
                "`buddie: контекст треда N тыс., дальше лучше новым тредом`"),
    "fail": ("FAIL before 0.5 (quote or anchor)", "copy quotes from the snapshot, refresh anchors"),
    "final": ("final answer without its numbers before 0.5",
              "end the result line with `⚓ run:<command> => <output>` or `⚓ pr:OWNER/REPO#N=merged@<sha>`, "
              "and anchor each count"),
}
QUOTE_MARKS = re.compile(r"[“”«»\"]")
DISCLOSED = re.compile(r"^\s*buddie\s*:", re.I | re.M)
SIMILAR = 0.6


def flagged(pred: dict, text: str, final: bool) -> list[dict]:
    """What made the gate return `text`: one item per flagged line ({kind, line, text}); line None for the whole
    answer (a final answer with no anchor at all)."""
    from buddie.anchors import BROKEN, unanchored_lines
    lines = text.splitlines()
    out = []

    def add(kind: str, n):
        if not any(i["kind"] == kind and i["line"] == n for i in out):
            out.append({"kind": kind, "line": n, "text": lines[n - 1] if n and 0 < n <= len(lines) else ""})

    for q in pred["quotes"]:
        if q["verdict"] == "NOT_FOUND":
            add("quote", q.get("line"))
    for a in pred["anchors"]:
        if a["status"] == BROKEN:
            add("anchor", a.get("line"))
    for c in pred["mandate"]:
        if c["status"] == BROKEN:
            add("work", c.get("line"))
    if any(b.startswith("number ") for b in pred["blocking"]):
        for n in pred["numbers"]:
            if n["verdict"] == "NOT_FOUND":
                add("number", n.get("line"))
    if final:
        if not pred["anchors"]:
            add("final_no_anchor", None)
        for n in unanchored_lines(text, pred.get("quote_backed", ())):
            add("final_bare", n)
        for n in pred.get("prose_lines", ()):
            add("prose", n)
    return out


def reasons(items: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in items:
        out[i["kind"]] = out.get(i["kind"], 0) + 1
    return out


def _bare(line: str) -> str:
    return " ".join(ANCHOR.sub(" ", line).split())


def _carries(kind: str, line: str) -> bool:
    """Whether a line still states the claim of its kind (else the claim was dropped from it)."""
    if kind == "final_bare":
        return bool(counts(line))
    if kind == "quote":
        return bool(QUOTE_MARKS.search(line))
    if kind == "anchor":
        return bool(ANCHOR.search(line))
    if kind == "prose":
        from buddie.effects import claims_work
        return claims_work(line)
    return True


def passage(before: list[dict], text: str, now: list[dict], code: int) -> dict:
    """How the attempt `text` (flagged items `now`, exit `code`) dealt with the items the gate returned before."""
    lines = text.splitlines()
    bare = [_bare(line) for line in lines]
    still = {(i["kind"], i["line"]) for i in now}
    disclosed = bool(DISCLOSED.search(text))
    tally = {"proved": 0, "removed": 0, "kept": 0}
    for item in before:
        if item["line"] is None:
            got = "kept" if (item["kind"], None) in still else ("proved" if ANCHOR.search(text) else "removed")
        else:
            want = _bare(item["text"])
            match = bare.index(want) + 1 if want and want in bare else None
            if match is None and want:
                score, best = max(((difflib.SequenceMatcher(None, want, b).ratio(), n)
                                   for n, b in enumerate(bare, 1) if b), default=(0, None))
                match = best if score >= SIMILAR else None
            if match is None or not _carries(item["kind"], lines[match - 1]):
                got = "removed"
            elif (item["kind"], match) in still:
                got = "kept"
            else:
                got = "proved"
        tally[got] += 1
    if code:
        way = "returned"
    elif disclosed and (tally["kept"] or not tally["proved"] and not tally["removed"]):
        way = "disclosure"
    elif tally["proved"] and tally["removed"]:
        way = "mixed"
    elif tally["proved"]:
        way = "proof"
    elif tally["removed"]:
        way = "removal"
    else:
        way = "other"
    return dict(tally, disclosed=disclosed, way=way)


# local state between a return and the next attempt: the flagged lines (text) stay on this machine only
def _state_file(session: str | None, tool: str | None) -> Path | None:
    root = os.environ.get("BUDDIE_STATE", str(Path.home() / ".cache" / "buddie" / "pending"))
    if root in ("", "0"):
        return None
    name = re.sub(r"[^\w.-]", "_", f"{session or 'nosession'}--{tool or 'answer'}")
    return Path(root) / f"{name}.json"


def take_pending(session: str | None, tool: str | None) -> list[dict] | None:
    f = _state_file(session, tool)
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f and f.is_file() else None
    except (OSError, json.JSONDecodeError):
        return None


def keep_pending(session: str | None, tool: str | None, items: list[dict] | None) -> None:
    f = _state_file(session, tool)
    if f is None:
        return
    try:
        if items:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
        elif f.exists():
            f.unlink()
    except OSError:
        pass


def entries(paths) -> list[dict]:
    """Journal lines from files and directories of *.jsonl, sorted by time; a line without session takes its file's
    name. The same line found in two places (local log and shared folder) counts once."""
    files = []
    for p in map(Path, paths):
        files += sorted(p.glob("*.jsonl")) if p.is_dir() else [p] if p.is_file() else []
    out, seen = [], set()
    for f in files:
        for raw in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                e = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(e, dict) or "exit" not in e or "at" not in e or e.get("beat"):
                continue  # a heartbeat (NEXT №118) is not a checked message
            e = dict(e, session=e.get("session") or f.stem)
            key = (e["session"], e["at"], e.get("sha256"), e.get("tool"), e["exit"])
            if key not in seen:
                seen.add(key)
                out.append(e)
    return sorted(out, key=lambda e: e["at"])


def entry_reasons(e: dict) -> dict[str, int]:
    if not e.get("exit"):
        return {}
    if e.get("reasons"):
        return e["reasons"]
    return {"fail": 1} if e.get("outcome") == "FAIL" else {"final": 1} if e.get("final") else {}


def _sessions(rows: list[dict]) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = {}
    for e in rows:
        by.setdefault(e["session"], []).append(e)
    return by


def lessons(rows: list[dict], skip_session: str | None = None, top: int = 5) -> str:
    """At most ten lines for the start of a session: what the gate returned messages for in past sessions."""
    by = _sessions([e for e in rows if e["session"] != skip_session])
    if not by:
        return ""
    returned = [e for rs in by.values() for e in rs if e.get("exit")]
    first = sum(1 for rs in by.values() if rs[0].get("exit"))
    tally: dict[str, int] = {}
    for e in returned:
        for k, n in entry_reasons(e).items():
            tally[k] = tally.get(k, 0) + n
    ways: dict[str, int] = {}
    for rs in by.values():
        for e in rs:
            if (e.get("gate") or {}).get("way") not in (None, "returned"):
                ways[e["gate"]["way"]] = ways.get(e["gate"]["way"], 0) + 1
    last = max(e["at"] for rs in by.values() for e in rs)[:10]
    out = [f"buddie, from the gate's journal ({len(by)} past sessions to {last}): {len(returned)} messages sent back; "
           f"the first checked message was sent back in {first} of {len(by)} sessions."]
    if tally:
        out.append("Most frequent returns, with a line that passes:")
        for kind, n in sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))[:top]:
            what, template = REASONS.get(kind, (kind, ""))
            out.append(f"- {what} ({n}): {template}".rstrip(": "))
    if ways:
        out.append("Passes after a return: " + ", ".join(f"{k} {v}" for k, v in sorted(ways.items(), key=lambda kv: -kv[1]))
                   + ". Pass by adding the proof, not by deleting the claim.")
    else:
        out.append("Pass by adding the proof, not by deleting the claim; or keep it with a line `buddie: <what is "
                   "unverified and why>`.")
    return "\n".join(out[:10])


def measure(rows: list[dict], since: str = "", sessions: int = 10) -> dict:
    """NEXT №55: the first `sessions` sessions that started at or after `since`."""
    by = _sessions([e for e in rows if e["at"] >= since])
    order = sorted(by, key=lambda s: by[s][0]["at"])[:sessions] if sessions else sorted(by, key=lambda s: by[s][0]["at"])
    per, ways = [], {}
    for s in order:
        rs = by[s]
        gates = [e["gate"] for e in rs if e.get("gate")]
        for g in gates:
            ways[g["way"]] = ways.get(g["way"], 0) + 1
        per.append({"session": s, "from": rs[0]["at"], "checks": len(rs), "returned": sum(1 for e in rs if e["exit"]),
                    "first_returned": bool(rs[0]["exit"]), "ways": [g["way"] for g in gates]})
    passed = sum(v for k, v in ways.items() if k != "returned")
    proof = ways.get("proof", 0)
    removal = ways.get("removal", 0)
    return {
        "since": since, "sessions": len(per),
        "first_message_passed": sum(not p["first_returned"] for p in per),
        "first_message_passed_share": round(sum(not p["first_returned"] for p in per) / len(per), 3) if per else None,
        "passes_after_return": passed, "ways": dict(sorted(ways.items())),
        "proof_share": round(proof / passed, 3) if passed else None,
        "removal_share": round(removal / passed, 3) if passed else None,
        "per_session": per,
    }
