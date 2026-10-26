"""Ground-truth isolation and scenario loading: nothing from the evaluation side reaches an agent."""
import json
import re
from pathlib import Path

import pytest

from bdx import CONDITIONS, ROOT, fixtures, prompts, scenarios, tools

GT = json.loads((ROOT / "evaluation" / "ground_truth.json").read_text(encoding="utf-8"))["scenarios"]
PROMPT_PATH_MODULES = ["__init__.py", "scenarios.py", "prompts.py", "tools.py", "fixtures.py", "backends.py",
                       "mcp_server.py"]


def test_twelve_scenarios_four_categories():
    sc = scenarios.load()
    assert len(sc) == 12
    cats = {}
    for s in sc.values():
        cats[s.category] = cats.get(s.category, 0) + 1
    assert cats == {"os_shell": 3, "runtime": 3, "hardware": 3, "context": 3}
    assert set(sc) == set(GT)
    assert scenarios.smoke() == ["OS-1", "HW-2", "CTX-3"]


@pytest.mark.parametrize("sid", list(GT))
def test_ground_truth_is_complete(sid):
    g = GT[sid]
    for key in ("environment", "relevant_facts", "expected", "acceptable_clarifications", "failure_modes",
                "clarification_justified", "rules", "coverage", "relevant_sources"):
        assert key in g, key
    assert set(g["clarification_justified"]) == set(CONDITIONS)
    assert set(g["environment"]) == set(scenarios.load()[sid].devices)
    for r in g["rules"]:
        re.compile(r["pattern"])
        if r.get("unless"):
            re.compile(r["unless"])
    for b in g["relevant_sources"]["B"]:
        assert b in fixtures.menu(), b


def test_prompt_path_never_reads_ground_truth():
    """No import of the evaluator and no string naming the evaluation side, docstrings aside."""
    import ast
    for name in PROMPT_PATH_MODULES:
        tree = ast.parse((ROOT / "harness" / "bdx" / name).read_text(encoding="utf-8"))
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mods = [a.name for a in node.names] + [getattr(node, "module", None) or ""]
                assert not any("evaluat" in m for m in mods), name
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
                assert "ground_truth" not in node.value and "evaluation" not in node.value, (name, node.value)


def _agent_visible(sid: str, cond: str) -> str:
    s = scenarios.load()[sid]
    return prompts.system(cond, s) + "\n" + prompts.user(s) + "\n" + json.dumps(tools.specs(cond, s))


@pytest.mark.parametrize("sid", list(GT))
@pytest.mark.parametrize("cond", CONDITIONS)
def test_prompts_and_tool_specs_leak_nothing(sid, cond):
    text = _agent_visible(sid, cond)
    s = scenarios.load()[sid]
    for b in s.bindings.values():
        assert b["env"] not in text
        assert fixtures.env(b["env"])["meta"]["redaction"]["host_alias"] not in text
    for phrase in [GT[sid]["expected"][:40]] + [v[:40] for v in GT[sid]["environment"].values()]:
        assert phrase not in text
    for leak in ("ground truth", "expected", "cached", "recorded", "simulat", "fixture", "win-laptop"):
        assert leak not in text.lower(), leak


def test_conditions_share_the_base_prompt_and_task():
    for s in scenarios.load().values():
        a, b, c = (prompts.system(x, s) for x in CONDITIONS)
        strip = lambda t: t.replace(prompts.TOOLS["A"], "").split("\n\n")[0]  # noqa: E731
        assert strip(a) == strip(b) == strip(c)
        assert a.split("End your answer")[1] == b.split("End your answer")[1] == c.split("End your answer")[1]


def test_condition_a_has_no_tools():
    for s in scenarios.load().values():
        assert tools.specs("A", s) == []


def test_buddie_tool_keeps_buddies_own_schema():
    s = scenarios.load()["OS-1"]
    spec = tools.specs("C", s)[0]
    real = next(t for t in fixtures.mcp.TOOLS if t["name"] == "environment_snapshot")
    assert real["description"] in spec["description"]
    for k, v in real["inputSchema"]["properties"].items():
        assert spec["input_schema"]["properties"][k] == v
    assert Path(fixtures.__file__).read_text(encoding="utf-8").count("from buddie import") == 1
