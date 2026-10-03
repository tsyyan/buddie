"""Claims about the course of work and the mandate for it (audit/10 §5.1): the third class next to quotes (the outside
world) and anchors (repo state).

An orchestrator that starts the next step by itself rests on three claims, and each can be checked without a model:

  done      «шаг N выполнен» / "step N done"     the queue row N is done and its status carries an anchor that holds
  verdict   «№N: вердикт auto»                   recomputed from the queue and the list of accepted plans: a step is
                                                 `auto` only when it continues a finished parent of the same accepted
                                                 plan (the rule of lab's tools/chain.py, here driven by config)
  consent   «пользователь согласился …»          the line quotes the user («…») with a date, and the quote is in a
                                                 message of the user's exported messages at that time

Plus the final answer's «Следующий шаг:» line: it names its queue row (№N), whose verdict is reported.

Statuses: HOLDS; BROKEN (the claim contradicts the queue or the messages: FAIL); UNSUPPORTED (no evidence given:
no anchor, no quote, no date, no row: GAPS); UNCHECKABLE (evidence given but nothing to check it against: GAPS).

Where the queue lives, which plans are accepted and what a basis looks like is config, `buddie.toml` at the repo
root, section [mandate]; without it this class is off. lab's own config reproduces tools/chain.py verdict for verdict
(tests/test_mandate.py). `rev` reads the queue as of a commit, to judge a claim against the state it was made in.
"""
from __future__ import annotations

import json
import re
import subprocess
import tomllib
from datetime import datetime, timedelta
from pathlib import Path

from buddie import anchors as anc

HOLDS, BROKEN, UNCHECKABLE = anc.HOLDS, anc.BROKEN, anc.UNCHECKABLE
UNSUPPORTED = "UNSUPPORTED"
CONFIG = "buddie.toml"

DEFAULTS = {
    "queue": "NEXT.md", "accepted": "ACCEPTED.md", "columns": {"n": 0, "text": 1, "basis": 3, "status": 4},
    "width": 5, "done": "выполнено", "proposed": "предложено", "fix": "fix", "none": "—",
    "parent": r"\s*←\s*№(?P<parent>\d+)$", "max_fix_chain": 2, "ask_words": r"(?!)", "refs": [],
    "messages": None, "messages_complete": False, "time_slack_minutes": 10, "final_mark": "Следующий шаг:",
}

ROW = re.compile(r"№\s?(\d+)")
NOT = r"(?<!не )(?<!not )(?<!ещё не )"
DONE = re.compile(NOT + r"\b(выполнен[аоы]?|сделан[аоы]?|завершён|завершен[аоы]?|done|completed|finished)\b", re.I)
AUTO = re.compile(r"(вердикт\w*|verdict)\W{0,4}`?(auto|ask)\b(?!/)`?", re.I)
CONSENT = re.compile(r"(пользовател\w*|user)\W+(\w+\W+){0,2}?(согласил\w*|принял\w*|одобрил\w*|разрешил\w*|решил\w*|"
                     r"approved|agreed|accepted|authori[sz]ed)\b|(согласи\w+|слов\w*|решени\w*|разрешени\w*)\s+"
                     r"пользовател\w*|(одобрен\w*|принят\w*|разрешен\w*)\s+пользователем", re.I)
QUOTE = re.compile(r"«([^«»]{8,})»|“([^“”]{8,})”")
WHEN = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})(?:[ T](?P<time>\d{2}:\d{2})(?::\d{2})?\s*(?:UTC|Z)?)?")


# --- config and sources -------------------------------------------------------------------------------------------

def load_config(repo: Path) -> dict | None:
    path = repo / CONFIG
    if not path.is_file():
        return None
    section = tomllib.loads(path.read_text(encoding="utf-8")).get("mandate")
    return None if section is None else {**DEFAULTS, **section, "repo": str(repo)}


def find_config(repos: list[Path]) -> dict | None:
    for repo in repos:
        if cfg := load_config(repo):
            return cfg
    return None


def read(cfg: dict, path: str, rev: str | None = None) -> str:
    repo = Path(cfg["repo"])
    if rev is None:
        return (repo / path).read_text(encoding="utf-8")
    out = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{path}"], capture_output=True, text=True)
    if out.returncode:
        raise FileNotFoundError(f"{path} at {rev}: {out.stderr.strip()}")
    return out.stdout


def messages(cfg: dict) -> list[dict] | None:
    """The user's messages, one JSON object per line: id, at (ISO, UTC), optional edited_at, author, text."""
    if not cfg.get("messages"):
        return None
    path = Path(cfg["repo"]) / cfg["messages"]
    if not path.is_file():
        return None
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            m = json.loads(line)
            if m.get("author", "user") == "user":
                out.append(m)
    return out


# --- the queue and the accepted plans (the generic form of lab's tools/chain.py) ------------------------------------

def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def rows(cfg: dict, text: str) -> dict[int, dict]:
    col, out = cfg["columns"], {}
    for line in text.splitlines():
        if not re.match(r"^\|\s*\d+\s*\|", line):
            continue
        cells = _cells(line)
        ok = len(cells) == cfg["width"]
        n = int(cells[col["n"]])
        out[n] = {"n": n, "cells": cells, "text": cells[col["text"]] if len(cells) > col["text"] else "",
                  "basis": cells[col["basis"]] if ok else "", "status": cells[col["status"]] if ok else ""}
    return out


def parse(cfg: dict, basis: str) -> dict | None:
    """`<ref>` or `<ref> ← №<parent>`; ref is one of cfg refs, `fix` or `none`."""
    parent = None
    if m := re.search(cfg["parent"], basis):
        parent, basis = int(m["parent"]), basis[:m.start()]
    basis = basis.strip()
    if basis == cfg["fix"]:
        return {"kind": "fix", "doc": None, "parent": parent, "groups": {}}
    if basis == cfg["none"]:
        return {"kind": "none", "doc": None, "parent": parent, "groups": {}}
    for ref in cfg["refs"]:
        if m := re.fullmatch(ref["pattern"], basis):
            groups = m.groupdict()
            return {"kind": "ref", "doc": ref["doc"].format(**groups), "parent": parent, "groups": groups,
                    "level": ref.get("level"), "ref": basis}
    return None


def accepted(cfg: dict, text: str) -> list[dict]:
    """Scopes: the first column of the accepted list's table, in backticks, written like a basis."""
    out = []
    for line in text.splitlines():
        if (m := re.match(r"^\|\s*`([^`]+)`\s*\|", line)) and (s := parse(cfg, m.group(1))) and s["kind"] == "ref":
            out.append(dict(s, line=line))
    return out


def _range(value: str) -> tuple[int, int] | None:
    m = re.fullmatch(r"(\d+)[–-](\d+)", value)
    return (int(m[1]), int(m[2])) if m else None


def in_scope(plan: dict, scopes: list[dict]) -> bool:
    for s in scopes:
        if s["doc"] != plan["doc"]:
            continue
        ok = True
        for key, want in s["groups"].items():
            if want is None or key in ("nn",):
                continue
            have = plan["groups"].get(key)
            if have is None:
                ok = False
            elif (r := _range(want)) and have.isdigit():
                ok = r[0] <= int(have) <= r[1]
            elif "." in have or "." in want or key == "sec":
                ok = have == want or have.startswith(want + ".")
            else:
                ok = have == want
            if not ok:
                break
        if ok:
            return True
    return False


def plan_of(cfg: dict, table: dict, n: int, seen: frozenset = frozenset()) -> dict | None:
    b = parse(cfg, table[n]["basis"]) if n in table else None
    if b is None or n in seen:
        return None
    if b["kind"] == "fix":
        return plan_of(cfg, table, b["parent"], seen | {n}) if b["parent"] else None
    return None if b["kind"] == "none" else b


def verdict(cfg: dict, table: dict, scopes: list[dict], n: int) -> dict:
    r, why = table[n], []
    b = parse(cfg, r["basis"])
    if not r["status"].startswith(cfg["proposed"]):
        why.append(f"status is not «{cfg['proposed']}»: {r['status'][:40]!r}")
    if b is None:
        return {"n": n, "verdict": "ask", "reasons": why + ["basis does not parse"]}
    plan = plan_of(cfg, table, n)
    if plan is None:
        why.append("not tied to an accepted plan (no plan, or a fix with no plan up its parents)")
    elif not in_scope(plan, scopes):
        why.append(f"{plan['ref']} is not in the accepted list")
    parent = b["parent"]
    if parent is None or parent not in table:
        why.append("no parent: unclear that the step continues the same plan")
    else:
        if not table[parent]["status"].startswith(cfg["done"]):
            why.append(f"parent №{parent} is not finished")
        pplan = plan_of(cfg, table, parent)
        if plan and (pplan is None or pplan["doc"] != plan["doc"]):
            why.append(f"parent №{parent} is from another plan")
        elif plan and plan.get("level") and pplan["groups"].get(plan["level"]) != plan["groups"].get(plan["level"]):
            why.append(f"moves from {plan['level']} {pplan['groups'].get(plan['level'])} to "
                       f"{plan['groups'].get(plan['level'])}: whether a stage is complete is the user's call")
    chain, k = 0, n
    while k in table and (kb := parse(cfg, table[k]["basis"])) and kb["kind"] == "fix":
        chain += 1
        k = kb["parent"]
    if chain > cfg["max_fix_chain"]:
        why.append(f"{chain} fixes in a row (more than {cfg['max_fix_chain']})")
    if re.search(cfg["ask_words"], r["text"], re.I):
        why.append("names an outward or irreversible action")
    return {"n": n, "verdict": "ask" if why else "auto", "reasons": why}


class Mandate:
    """The queue, the accepted list and the user's messages as of `rev` (None: the working tree)."""

    def __init__(self, cfg: dict, rev: str | None = None):
        self.cfg, self.rev = cfg, rev
        self.table = rows(cfg, read(cfg, cfg["queue"], rev))
        try:
            self.scopes = accepted(cfg, read(cfg, cfg["accepted"], rev))
        except FileNotFoundError:
            self.scopes = []
        self.msgs = messages(cfg)
        self.repos = [Path(cfg["repo"])]

    def verdict(self, n: int) -> dict:
        return verdict(self.cfg, self.table, self.scopes, n)

    # each check returns a claim row: {kind, row?, status, why?}

    def done(self, n: int, line: str = "") -> dict:
        out = {"kind": "done", "row": n}
        if n not in self.table:
            return dict(out, status=BROKEN, why=f"no row №{n} in {self.cfg['queue']}")
        status = self.table[n]["status"]
        if not status.startswith(self.cfg["done"]):
            return dict(out, status=BROKEN, why=f"row №{n} is {status[:40]!r}, not «{self.cfg['done']}»")
        found = anc.ANCHOR.findall(status) or anc.ANCHOR.findall(line)
        if not found:
            return dict(out, status=UNSUPPORTED, why=f"row №{n} is done with no anchor")
        checked = [anc.check_one(a, self.repos, {}) for a in found]
        worst = BROKEN if any(c["status"] == BROKEN for c in checked) else \
            UNCHECKABLE if any(c["status"] == UNCHECKABLE for c in checked) else HOLDS
        why = "; ".join(f"⚓ {c['anchor']}: {c['why']}" for c in checked if c.get("why"))
        return dict(out, status=worst, **({"why": why} if why else {}))

    def claimed_verdict(self, n: int, claimed: str) -> dict:
        out = {"kind": "verdict", "row": n, "claimed": claimed}
        if n not in self.table:
            return dict(out, status=BROKEN, why=f"no row №{n} in {self.cfg['queue']}")
        v = self.verdict(n)
        out["computed"] = v["verdict"]
        if claimed == "auto" and v["verdict"] != "auto":
            return dict(out, status=BROKEN, why="claimed auto, computed ask: " + "; ".join(v["reasons"]))
        return dict(out, status=HOLDS)

    def consent(self, line: str) -> dict:
        out = {"kind": "consent"}
        quotes = [a or b for a, b in QUOTE.findall(line)]
        when = WHEN.search(line)
        if not quotes:
            return dict(out, status=UNSUPPORTED, why="consent without the user's words in «…»")
        out["quotes"] = [q[:120] for q in quotes]
        if self.msgs is None:
            return dict(out, status=UNCHECKABLE, why="no export of the user's messages (config `messages`)")
        hits = [self._find(q) for q in quotes]
        missing = [q for q, h in zip(quotes, hits) if not h]
        if len(missing) == len(quotes):
            if self.cfg["messages_complete"]:
                return dict(out, status=BROKEN, why=f"no user message has «{missing[0][:80]}»")
            return dict(out, status=UNCHECKABLE, why=f"«{missing[0][:80]}» is not in the export (export is partial)")
        found = [m for h in hits for m in h]
        out["messages"] = sorted({m["id"] for m in found})
        if not when:
            return dict(out, status=UNSUPPORTED, why="the user's words are found, but the line gives no date")
        if not any(self._at(m, when) for m in found):
            ats = ", ".join(sorted({m["at"][:16] for m in found}))
            return dict(out, status=BROKEN, why=f"the words are from {ats}, the line says {when.group(0)}")
        if missing:
            return dict(out, status=UNCHECKABLE, why=f"«{missing[0][:80]}» is not in the export")
        return dict(out, status=HOLDS)

    def next_step(self, line: str) -> dict:
        out = {"kind": "next"}
        n = ROW.search(line)
        if not n:
            return dict(out, status=UNSUPPORTED, why=f"the next step names no row of {self.cfg['queue']} (№N)")
        n = int(n.group(1))
        if n not in self.table:
            return dict(out, row=n, status=BROKEN, why=f"no row №{n} in {self.cfg['queue']}")
        return dict(out, row=n, status=HOLDS, computed=self.verdict(n)["verdict"])

    @staticmethod
    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", s.replace("ё", "е")).strip(" .,;:!?").casefold()

    def _find(self, quote: str) -> list[dict]:
        q = self._norm(quote)
        return [m for m in self.msgs if q and q in self._norm(m["text"])]

    def _at(self, msg: dict, when: re.Match) -> bool:
        slack = timedelta(minutes=self.cfg["time_slack_minutes"])
        for key in ("at", "edited_at"):
            if not msg.get(key):
                continue
            t = datetime.fromisoformat(msg[key].replace("Z", "+00:00")).replace(tzinfo=None)
            if t.strftime("%Y-%m-%d") != when["date"]:
                continue
            if not when["time"]:
                return True
            said = datetime.strptime(f"{when['date']} {when['time']}", "%Y-%m-%d %H:%M")
            if abs(t.replace(second=0) - said) <= slack:
                return True
        return False


# --- claims in a report ----------------------------------------------------------------------------------------------

def _line_rev(line: str, cfg: dict) -> str | None:
    """A claim that anchors the queue (`⚓ NEXT.md@78c212f`) is judged at that commit, not at `rev`."""
    for a in anc.ANCHOR.findall(line):
        if (m := anc.FILE_AT.match(a)) and m["path"] == cfg["queue"]:
            return m["commit"]
    return None


def _sentence(line: str, pos: int) -> tuple[int, int]:
    starts = [m.end() for m in re.finditer(r"[.!?;](\s|$)", line[:pos])]
    end = re.search(r"[.!?;](\s|$)", line[pos:])
    return (starts[-1] if starts else 0), (pos + end.start() if end else len(line))


def check_text(text: str, cfg: dict, rev: str | None = None) -> list[dict]:
    """Every claim about the course of work in `text`, judged against the queue as of `rev`."""
    states = {}

    def at(r):
        if r not in states:
            states[r] = Mandate(cfg, r)
        return states[r]

    out = []
    for number, line in enumerate(text.splitlines(), 1):
        m, found = at(_line_rev(line, cfg) or rev), []
        if cfg["final_mark"] and cfg["final_mark"] in line:
            found.append(m.next_step(line))
        if v := AUTO.search(line):
            # the rows named in the verdict's sentence, except parents («← №21», «родитель №21»)
            lo, hi = _sentence(line, v.start())
            named = [int(r.group(1)) for r in ROW.finditer(line, lo, hi)
                     if not re.search(r"(←|родител\w*|parent)\s*$", line[lo:r.start()])]
            if not named and found:
                named = [f["row"] for f in found if f.get("row")]
            if not named and v.group(2).lower() == "auto":
                found.append({"kind": "verdict", "claimed": v.group(2).lower(), "status": UNSUPPORTED,
                              "why": f"a verdict with no row of {cfg['queue']} (№N)"})
            seen = {f.get("row") for f in found if f["kind"] == "next"}
            found += [m.claimed_verdict(n, v.group(2).lower()) for n in dict.fromkeys(named)
                      if not (n in seen and v.group(2).lower() == "ask")]
        elif not found:
            # «№30 выполнен», «шаг №19 сделан»: the row nearest before the word
            for d in DONE.finditer(line):
                rows_before = list(ROW.finditer(line[:d.start()]))
                if rows_before and d.start() - rows_before[-1].end() <= 40:
                    found.append(m.done(int(rows_before[-1].group(1)), line))
        if CONSENT.search(line):
            found.append(m.consent(line))
        out += [dict(f, line=number, text=line.strip()[:160], rev=m.rev) for f in found]
    return out


def check_queue(cfg: dict, rev: str | None = None) -> dict:
    """The queue itself: every done row carries an anchor that holds; the verdict of every proposed row."""
    m = Mandate(cfg, rev)
    done = [m.done(n) for n in sorted(m.table) if m.table[n]["status"].startswith(cfg["done"])]
    proposed = [m.verdict(n) for n in sorted(m.table) if m.table[n]["status"].startswith(cfg["proposed"])]
    return {"rows": len(m.table), "done": done, "proposed": proposed}


def check_accepted(cfg: dict, rev: str | None = None) -> list[dict]:
    """Every accepted plan is a consent claim: its row must quote the user with a date."""
    m = Mandate(cfg, rev)
    return [dict(m.consent(s["line"]), scope=_cells(s["line"])[0].strip("`")) for s in m.scopes]


def outcome(claims: list[dict]) -> str | None:
    if not claims:
        return None
    if any(c["status"] == BROKEN for c in claims):
        return "FAIL"
    if any(c["status"] in (UNSUPPORTED, UNCHECKABLE) for c in claims):
        return "GAPS"
    return "PASS"
