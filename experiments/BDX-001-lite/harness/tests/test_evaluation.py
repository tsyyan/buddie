"""Evaluation determinism and rule sanity. The answers below are hand-written test inputs for the rules, not model
outputs."""
import copy
import json

import pytest

import evaluate as ev


def answer(prose, outcome, commands, facts=()):
    block = json.dumps({"outcome": outcome, "commands": list(commands), "environment_facts": list(facts),
                        "question": None})
    return f"{prose}\n\n```result\n{block}\n```"


CASES = [
    ("OS-1", answer("In Windows PowerShell 5.1:", "recommendation",
                    ["python -m venv .venv; .\\.venv\\Scripts\\Activate.ps1; pip install -r requirements.txt"]),
     "APPLICABLE"),
    ("OS-1", answer("Run:", "recommendation",
                    ["python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"]),
     "INAPPLICABLE"),
    ("OS-1", answer("Run:", "recommendation",
                    ["python -m venv .venv && .venv\\Scripts\\activate && pip install -r requirements.txt"]),
     "INAPPLICABLE"),
    ("HW-2", answer("Your container has a 2 GiB memory limit, so an 8B fp16 model (about 16 GB) will not fit. "
                    "Try Qwen2.5-0.5B-Instruct on CPU, or raise the limit with --memory.", "recommendation",
                    ["pip install transformers torch", "python run_small.py"]), "APPLICABLE"),
    ("HW-2", answer("Load it on your GPU.", "recommendation",
                    ["pip install transformers accelerate",
                     "python -c \"AutoModelForCausalLM.from_pretrained(m, device_map='cuda')\""]), "INAPPLICABLE"),
    ("CTX-3", answer("This device runs Windows and no WSL distribution is installed, so a Linux build will not run "
                     "natively. Search for it with Get-ChildItem.", "recommendation",
                     ["Get-ChildItem -Path $HOME -Recurse -Filter 'dataforge*' -ErrorAction SilentlyContinue"]),
     "APPLICABLE"),
    ("CTX-3", answer("Open your WSL terminal and search.", "recommendation",
                     ["wsl find ~ -name 'dataforge*'", "tar -xzf dataforge-1.4.0-linux-x86_64.tar.gz"]),
     "INAPPLICABLE"),
]


@pytest.mark.parametrize("sid,text,expected", CASES)
def test_rules_label_reference_answers(sid, text, expected):
    assert ev.label(ev.judge(sid, text), "C", "ok") == expected


def test_wsl_assumption_is_a_probe_hit():
    v = ev.judge("CTX-3", CASES[-1][1])
    assert any(h["id"] == "assumes_wsl" for h in v["assumption_hits"])
    assert not ev.judge("CTX-3", CASES[-2][1])["assumption_hits"]


def test_clarification_depends_on_condition_only_through_ground_truth():
    text = answer("Which computer did you download it on?", "clarification", [])
    v = ev.judge("HW-2", text)
    assert ev.label(v, "A", "ok") == "JUSTIFIED_CLARIFICATION"
    assert ev.label(v, "C", "ok") == "UNJUSTIFIED_CLARIFICATION"
    assert ev.label(ev.judge("CTX-3", text), "B", "ok") == "JUSTIFIED_CLARIFICATION"


def test_missing_result_block_goes_to_manual_review():
    v = ev.judge("OS-1", "Just run python -m venv .venv")
    assert ev.label(v, "A", "ok") == "NO_RESULT" and "no_result_block" in v["manual_review"]
    assert ev.label(v, "A", "harness_failure") == "HARNESS_FAILURE"


@pytest.mark.parametrize("sid,text,_", CASES)
def test_evaluation_is_deterministic(sid, text, _):
    first = ev.judge(sid, text)
    assert all(ev.judge(sid, copy.copy(text)) == first for _ in range(3))


def test_judge_never_sees_condition():
    import inspect
    assert list(inspect.signature(ev.judge).parameters) == ["scenario", "answer"]
