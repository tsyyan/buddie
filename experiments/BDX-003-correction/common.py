"""BDX-003 shared pieces: paths, the independent quote matcher and page text.

The matcher here is deliberately NOT buddie's. buddie's verdicts are what arm C feeds back to the model, so judging
the outcome with buddie would let buddie grade itself. This one is plain: Unicode NFKC, case folded, quotation marks,
apostrophes and dashes unified, whitespace collapsed, an ellipsis splitting a quote into parts that must each appear
in order. It is stricter than a careful human in some places (a text layer that dropped a word) and that is
recorded as a limitation, not tuned away.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.append(str(ROOT))  # after the experiment directory: the repository has its own run.py

SETS = {  # report text is redistributable only for DeepResearch Bench (Apache-2.0); E010 (ydc) has no text
    "E008": ROOT / "results" / "E008-drb2-fresh",
    "E011": ROOT / "results" / "E011-drb1-claude",
}
ERROR_LABELS = {"AGENT_ALTERED", "AGENT_ABSENT"}
OK_LABELS = {"IN_SOURCE"}

_QUOTES = str.maketrans({c: '"' for c in "“”„‟«»″〝〞＂"} | {c: "'" for c in "‘’‚‛′`´"}
                        | {c: "-" for c in "‐‑‒–—―−"})
_SPACE = re.compile(r"\s+")
_DASH = re.compile(r"\s*-\s*")
_ELLIPSIS = re.compile(r"\s*(?:\.\s?\.\s?\.|…)\s*")


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").translate(_QUOTES).casefold()
    text = text.replace("­", "").replace("​", "")
    text = _DASH.sub("-", text)  # "important – this" and "important—this" are the same dash
    return _SPACE.sub(" ", text).strip()


def parts(quote: str) -> list[str]:
    """The pieces of a quote an ellipsis or a bracketed insertion separates; empty pieces dropped."""
    q = re.sub(r"\[[^\]]{0,40}\]", "…", quote)
    return [p.strip(" \"'.,;:") for p in _ELLIPSIS.split(norm(q)) if len(p.strip(" \"'.,;:")) >= 3]


def in_text(quote: str, page: str) -> bool:
    """Every part of the quote is in the page text, in order (independent of buddie)."""
    hay = norm(page)
    at = 0
    pieces = parts(quote)
    if not pieces:
        return False
    for p in pieces:
        i = hay.find(p, at)
        if i < 0:
            return False
        at = i + len(p)
    return True


QUOTED = re.compile(r'“([^”]{3,600})”|"([^"\n]{3,600})"|«([^»]{3,600})»|„([^“”]{3,600})[“”]')


def quoted_spans(text: str) -> list[str]:
    return [next(g for g in m.groups() if g) for m in QUOTED.finditer(text or "")]


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, norm(a), norm(b), autojunk=False).ratio()


def best_span(target: str, text: str) -> tuple[str | None, float]:
    """The quoted span of `text` most like `target`, by character similarity."""
    best, score = None, 0.0
    for s in quoted_spans(text):
        r = similarity(target, s)
        if r > score:
            best, score = s, r
    return best, score


def page_text(store, url: str) -> tuple[dict | None, str | None]:
    """Newest snapshot of `url` in a buddie Store, and its visible text (None when unreadable)."""
    from buddie.verbatim.textlayer import Unreadable, layers
    try:
        entry, data = store.resolve(url.split("#", 1)[0])
    except KeyError:
        return None, None
    try:
        return entry, layers(data, entry.get("content_type"), entry.get("content_encoding"))["visible"]
    except Unreadable:
        return entry, None


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")


def read_jsonl(path: Path) -> list[dict]:
    p = Path(path)
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()] if p.exists() else []


def append_jsonl(path: Path, row: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
