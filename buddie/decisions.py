"""A person's pick on a project's decision card (`mcp__hearthbot__ask_decision`, NEXT №109).

The summary card of buddie is an AskUserQuestion, whose answer comes back as the tool's result and goes to the journal
on PostToolUse (summary.on_choice). A project's coordinator asks with `ask_decision` instead: the call only posts the
card and returns its message id, and the pick arrives later as a new turn, a `<wake reason="decision-chosen">`
written by the platform with the card's id and the option's index. Neither is a tool result the model wrote, so both
are read from the session's transcript:

  card    an assistant `tool_use` of ask_decision (question, options with label and consequence) whose `tool_result`
          is not an error and carries the card's `message_id`
  pick    a user turn (or a queued command) that *starts* with `<wake reason="decision-chosen"`, whose message is from
          a human with trust principal, and whose system notes after `</project>` name `decision_id` and
          `option_index`; text inside a tool result never counts, so a pick printed by Bash or a fetched page is not one

An option's steps are the `№N` of its label and consequence; an option that says «то же» (the same as the one before
it, «То же самое, плюс №101») also has the steps of the option before it. The pick becomes a `choice` line in the
journal's own format (summary.check_choice reads it): chosen = the option's label and its steps.

The coordinator is recycled: a card asked in one session can be answered in the next. So the hook writes each card
(`card` line) and each resolved pick (`choice` line) to the journal, which is the shared folder of the project when
there is one; a pick whose card is in no transcript and no journal still holds for the option's label, and a step is
UNCHECKABLE then, never HOLDS.

Without `[journal] text = true` (NEXT №104) both lines are receipts: a card keeps each option's label as a hash and
its queue steps, a pick keeps the hashes of the chosen label and steps; check_choice holds on them the same way.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

TOOL = re.compile(r"(^|__)ask_decision$")
WAKE = re.compile(r'^\s*<wake reason="decision-chosen"')
ATTR = re.compile(r'([\w-]+)="([^"]*)"')
NOTE = re.compile(r"<system-note>\s*([\w-]+)=([^<\s]+)\s*</system-note>")
CHOSE = re.compile(r'^Chose "(?P<label>.*)" on the decision card asking "(?P<question>.*)"\s*$', re.S)
STEP = re.compile(r"№\s?(\d+)")
SAME = re.compile(r"(?<!\w)(то же|same as)(?!\w)", re.I)


def card_of(tool_input: dict, result) -> dict | None:
    """The card from ask_decision's input and its result (a JSON text, a content list or a dict with message_id)."""
    cid = message_id(result)
    opts = tool_input.get("options") if isinstance(tool_input, dict) else None
    if not cid or not isinstance(opts, list):
        return None
    return {"id": cid, "question": str(tool_input.get("question", "")),
            "options": [{"label": str(o.get("label", "")), "consequence": str(o.get("consequence", ""))}
                        for o in opts if isinstance(o, dict)]}


def message_id(result) -> str | None:
    if isinstance(result, dict):
        if isinstance(result.get("message_id"), str):
            return result["message_id"]
        return message_id(result.get("content") if "content" in result else result.get("text"))
    if isinstance(result, list):
        return next((m for r in result if (m := message_id(r))), None)
    if isinstance(result, str):
        try:
            return message_id(json.loads(result))
        except json.JSONDecodeError:
            return None
    return None


def steps(card: dict, index: int) -> list[str]:
    """The queue steps of option `index`: its own №N, and those of the option before it when it says «то же»."""
    opts = card.get("options") or []
    if not 0 <= index < len(opts):
        return []
    o = opts[index]
    if "steps" in o:  # a receipt card: the steps were taken when it was written
        return list(o["steps"])
    text = f"{o.get('label', '')} {o.get('consequence', '')}"
    own = [f"№{n}" for n in STEP.findall(text)]
    before = steps(card, index - 1) if SAME.search(text) and index > 0 else []
    return list(dict.fromkeys(before + own))


def pick_of(text: str) -> dict | None:
    """A decision-chosen wake: {id, index, option, label, question, actor}; None for anything else."""
    if not isinstance(text, str) or not WAKE.match(text):
        return None
    head, sep, tail = text.partition("</project>")
    if not sep:
        return None
    m = re.search(r"<message ([^>]*)>(.*?)</message>", head, re.S)
    if not m:
        return None
    attrs = dict(ATTR.findall(m.group(1)))
    if attrs.get("from") != "human" or attrs.get("trust") != "principal":
        return None
    notes = dict(NOTE.findall(tail))
    if not re.fullmatch(r"[\w.-]+", notes.get("decision_id", "")) or not notes.get("option_index", "").isdigit():
        return None
    said = CHOSE.match(html.unescape(m.group(2)).strip())
    return {"id": notes["decision_id"], "index": int(notes["option_index"]), "option": notes.get("option"),
            "label": said["label"] if said else None, "question": said["question"] if said else None,
            "actor": notes.get("actor_account_id") or attrs.get("author-id"), "at": attrs.get("sent-at")}


def _turn_text(entry: dict) -> str | None:
    """The text of a turn the harness wrote: a user message (string or text blocks, no tool result) or a command
    queued in the middle of a turn."""
    if entry.get("type") == "user":
        content = (entry.get("message") or {}).get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list) and content and all(isinstance(c, dict) and c.get("type") == "text"
                                                         for c in content):
            return "".join(c.get("text", "") for c in content)
    if entry.get("type") == "attachment":
        a = entry.get("attachment") or {}
        if a.get("type") == "queued_command" and isinstance(a.get("prompt"), str):
            return a["prompt"]
    return None


def scan(transcript: str | None) -> tuple[dict, list[dict]]:
    """The cards ({id: card}) and the picks of a session's transcript."""
    cards, picks, asked = {}, [], {}
    if not transcript or not Path(transcript).is_file():
        return cards, picks
    for raw in Path(transcript).read_text(encoding="utf-8", errors="replace").splitlines():
        if "ask_decision" not in raw and "decision-chosen" not in raw and not any(t in raw for t in asked):
            continue
        try:
            e = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(e, dict):
            continue
        if (text := _turn_text(e)) is not None:
            if p := pick_of(text):
                picks.append(p)
            continue
        content = (e.get("message") or {}).get("content")
        for c in content if isinstance(content, list) else []:
            if not isinstance(c, dict):
                continue
            if e.get("type") == "assistant" and c.get("type") == "tool_use" and TOOL.search(str(c.get("name", ""))):
                asked[c.get("id")] = c.get("input") or {}
            elif e.get("type") == "user" and c.get("type") == "tool_result" and c.get("tool_use_id") in asked \
                    and not c.get("is_error"):
                if card := card_of(asked.pop(c["tool_use_id"]), c.get("content")):
                    cards[card["id"]] = card
    return cards, picks


def journal_cards(paths=None) -> dict:
    """The `card` lines of the journal, {id: card}."""
    from buddie.hook import journal_paths
    out = {}
    files = []
    for p in map(Path, paths if paths is not None else journal_paths()):
        files += sorted(p.glob("*.jsonl")) if p.is_dir() else [p] if p.is_file() else []
    for f in files:
        for raw in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if '"card"' not in raw:
                continue
            try:
                e = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(e, dict) and isinstance(e.get("card"), dict) and e["card"].get("id"):
                out[e["card"]["id"]] = e["card"]
    return out


def choice(pick: dict, card: dict | None) -> dict:
    """The pick as a journal `choice` (summary.check_choice's format)."""
    label, ok = pick.get("label"), False
    if card:
        opts = card.get("options") or []
        if 0 <= pick["index"] < len(opts):
            o = opts[pick["index"]]
            if "label" in o:
                ok = pick.get("label") in (None, o["label"])  # the wake may name another option than the card has
                label = o["label"] if ok else None
            else:  # a receipt card: the wake's label must hash to the option's
                ok = label is None or _hash(label) == o.get("sha256")
                label = label if ok else None
        else:
            label = None
    chosen = ([label] if label else []) + (steps(card, pick["index"]) if ok else [])
    return {"id": pick["id"], "source": "ask_decision", "question": (card or {}).get("question") or pick.get("question"),
            "options": [{"key": o["label"], "label": o["label"]} for o in (card or {}).get("options", []) if "label" in o],
            "chosen": chosen, "other": [], "option_index": pick["index"], "actor": pick.get("actor"),
            "card": bool(card)}


def _hash(text: str) -> str:
    from buddie.summary import _step_hash
    return _step_hash(text)


def receipt_card(card: dict) -> dict:
    """A card line without words ([journal] text = false): per option the label's hash and its queue steps."""
    return {"id": card["id"], "options": [{"sha256": _hash(o.get("label", "")), "steps": steps(card, i)}
                                          for i, o in enumerate(card.get("options") or [])]}


def receipt_choice(c: dict) -> dict:
    """A choice line without words: the hashes of the chosen label and steps (summary.check_choice reads them)."""
    return {"id": c["id"], "source": c["source"], "picked": sorted({_hash(x) for x in c["chosen"] if x}),
            "other_rows": [], "option_index": c["option_index"], "card": c["card"]}


def _words(event: dict) -> bool:
    from buddie import config
    return config.journal_text(config.of_event(event)[1])


def choices(transcript: str | None, paths=None) -> list[dict]:
    """The picks of this session's transcript as journal lines, their cards from the transcript or the journal."""
    cards, picks = scan(transcript)
    if not picks:
        return []
    if any(p["id"] not in cards for p in picks):
        cards = {**journal_cards(paths), **cards}
    return [{"at": p.get("at"), "choice": choice(p, cards.get(p["id"]))} for p in picks]


def sync(event: dict) -> None:
    """Write the cards and picks of the session's transcript that the journal does not have yet."""
    from buddie.hook import log
    from buddie.summary import choices as journal_choices, now_iso
    transcript = event.get("transcript_path")
    cards, picks = scan(transcript)
    if not cards and not picks:
        return
    have = journal_cards()
    session = event.get("session_id")
    words = _words(event)
    for cid, card in cards.items():
        if cid not in have:
            log({"at": now_iso(), "session": session, "event": "card", "card": card if words else receipt_card(card)})
    if picks:
        done = {(e["choice"].get("id"), e["choice"].get("card")) for e in journal_choices()
                if e["choice"].get("source") == "ask_decision"}
        known = {**have, **cards}
        for p in picks:
            c = choice(p, known.get(p["id"]))
            if (c["id"], c["card"]) not in done and (c["id"], True) not in done:
                log({"at": p.get("at") or now_iso(), "session": session, "event": "decision-chosen",
                     "choice": c if words else receipt_choice(c)})


def on_post(event: dict) -> dict | None:
    """PostToolUse on ask_decision: the card goes to the journal at once (the session may end before another hook)."""
    from buddie.hook import log
    from buddie.summary import now_iso
    card = card_of(event.get("tool_input") or {}, event.get("tool_response"))
    if card and card["id"] not in journal_cards():
        log({"at": now_iso(), "session": event.get("session_id"), "event": "card",
             "card": card if _words(event) else receipt_card(card)})
    return card
