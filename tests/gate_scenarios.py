"""The hook's gate on a fixed matrix of answers, configs and events, normalized (tmp paths, times) so that its output
can be compared run to run: tests/test_gate.py holds it equal to tests/data/gate_golden.json, which was written by
the gate as it was before #27 (`python tests/gate_scenarios.py > tests/data/gate_golden.json`)."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path

URL = "https://news.example.org/outage"
PAGE = ("<p>" + "Background paragraph about the service. " * 40 + "</p><p>The company said the outage began at 14:59 "
        "UTC and was resolved within two hours. The market was valued at USD 3.4 billion in 2022.</p>").encode()
HELLO = hashlib.sha256(b"hello\n").hexdigest()[:12]
GOOD_Q = f"The vendor wrote that “the outage began at 14:59 UTC and was resolved within two hours” ([r]({URL}))."
BAD_Q = GOOD_Q.replace("14:59", "14:58")
HOLDS, BROKEN, MISSING = f"`⚓ data.txt#{HELLO}`", f"`⚓ data.txt#{'0' * 12}`", f"`⚓ gone.txt#{HELLO}`"

TEXTS = {
    "pass": f"Done. {HOLDS}",
    "fail_anchor": f"Done. {BROKEN}",
    "gaps_anchor": f"Done. {MISSING}",
    "bad_quote": f"{BAD_Q} {HOLDS}",
    "good_quote": f"{GOOD_Q} {HOLDS}",
    "number_miss": f"The market was worth $3.4 billion in 2022 and grows 9.5% ([z]({URL})). {HOLDS}",
    "prose": "All merged and CI is green.\nTests passed.",
    "bare_count": "We checked 73 of 84 files.",
    "mixed": f"{BAD_Q}\nDone. {BROKEN}\nMerged, CI green.\nWe checked 73 of 84 files.",
    "disclosed": f"{BAD_Q} {HOLDS}\nbuddie: the quote could not be fixed, its page changed.",
    "disclosed_anchor": f"Done. {BROKEN}\nbuddie: the anchor is stale, the file changed after.",
    "fact": "Counted. `⚓ x.count=3`",
    "empty": "   ",
}
CONFIGS = {
    "none": None,
    "defaults": '[gates]\nanchors = "block"\n',
    "quotes_warn": '[gates]\nquotes = "warn"\n',
    "anchors_off": '[gates]\nanchors = "off"\nfinal = "off"\n',
    "strict": '[gates]\nprose = "block"\nnumbers = "block"\n',
    "intro": '[intro]\nfinals = 3\n',
    "final_mark": '[mandate]\nfinal_mark = "Done"\n',
}
ENVS = {"plain": {}, "env_gates": {"BUDDIE_GATES": "quotes=off,prose=block"}, "env_final": {"BUDDIE_FINAL": ""}}
EVENTS = ("Stop", "Stop_active", "PreToolUse")
QUEUE = "| № | Шаг | Тема | Основание | Статус |\n|---|---|---|---|---|\n"


def _norm(s: str, base: Path) -> str:
    for b in {str(base), str(base.resolve()), base.as_posix(), base.resolve().as_posix()}:
        s = s.replace(b, "<TMP>").replace(b.replace("\\", "\\\\"), "<TMP>")
    return re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", "<AT>", s.replace("\\\\", "/").replace("\\", "/"))


def run_all(anchors_patch=None) -> dict:
    from buddie import hook
    from buddie.verbatim.store import Store
    out = {}
    saved = dict(os.environ)
    keep = ("BUDDIE_GATES", "BUDDIE_FINAL", "BUDDIE_REPOS", "BUDDIE_NUMBERS", "BUDDIE_TRANSCRIPT",
            "CLAUDE_PLUGIN_OPTION_READ_TRANSCRIPT")
    try:
        for cname, toml in CONFIGS.items():
            for ename, env in ENVS.items():
                base = Path(tempfile.mkdtemp())
                repo = base / "repo"
                repo.mkdir()
                (repo / "data.txt").write_bytes(b"hello\n")
                if toml is not None:
                    (repo / "buddie.toml").write_text(toml, encoding="utf-8")
                    (repo / "NEXT.md").write_text(QUEUE, encoding="utf-8")
                Store(base / "store").add(URL, PAGE, content_type="text/html", fetched_at="2026-10-21T00:00:00Z")
                for k in keep:
                    os.environ.pop(k, None)
                os.environ.update({"BUDDIE_FETCH": "0", "BUDDIE_GITHUB": "0", "BUDDIE_LOG": str(base / "hook.jsonl"),
                                   "BUDDIE_STATE": str(base / "pending"), "BUDDIE_REPOS": str(repo),
                                   "VERBATIM_STORE": str(base / "store"), "BUDDIE_SHARED_LOG": "0",
                                   "BUDDIE_INTRO": str(base / "intro.json"), "BUDDIE_PROMISES": "0",
                                   "BUDDIE_LESSONS": "0", **env})
                for tname, text in TEXTS.items():
                    for event in EVENTS:
                        ev = {"session_id": f"{tname}-{event}", "cwd": str(repo)}
                        if event == "PreToolUse":
                            ev |= {"hook_event_name": "PreToolUse", "tool_name": "mcp__x__send_message",
                                   "tool_input": {"text": text}}
                        else:
                            ev |= {"hook_event_name": "Stop", "last_assistant_message": text,
                                   "stop_hook_active": event == "Stop_active"}
                        before = (base / "hook.jsonl").read_text(encoding="utf-8") if (base / "hook.jsonl").exists() else ""
                        attempts = []
                        for _ in range(2):  # the same event twice: the second meets the first's pending return
                            err, so = io.StringIO(), io.StringIO()
                            code = hook.run(dict(ev), err, so)
                            attempts.append([code, _norm(err.getvalue(), base), _norm(so.getvalue(), base)])
                        after = (base / "hook.jsonl").read_text(encoding="utf-8")[len(before):]
                        lines = [json.loads(x) for x in after.splitlines()]
                        for line in lines:
                            line.pop("at", None)
                        out[f"{cname}/{ename}/{tname}/{event}"] = {"attempts": attempts,
                                                                    "journal": json.loads(_norm(json.dumps(lines, ensure_ascii=False), base))}
    finally:  # the environment as it was, whole: nothing set here leaks into the next test
        os.environ.clear()
        os.environ.update(saved)
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(run_all(), ensure_ascii=False, indent=0, sort_keys=True))
