"""Read-only governance policy; absence or ambiguity blocks remote promotion."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import release_governance as rg


def protected():
    return [
        {"enforcement": "active", "target": "branch", "conditions": {"ref_name": {
            "include": ["refs/heads/plugin-stable"], "exclude": []}},
         "bypass_actors": [], "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}]},
        {"enforcement": "active", "target": "branch", "conditions": {"ref_name": {
            "include": ["refs/heads/plugin-stable"], "exclude": []}},
         "bypass_actors": [{"actor_type": "Integration", "actor_id": 15368, "bypass_mode": "always"}],
         "rules": [{"type": "update"}, {"type": "creation"}]},
    ]


def environment():
    return {"name": "pypi", "can_admins_bypass": False, "protection_rules": [
        {"type": "required_reviewers", "reviewers": [{"type": "User", "reviewer": {"id": 1}}]}]}


def test_verified_rules_allow_generated_distribution():
    assert rg.problems(protected(), environment()) == []


@pytest.mark.parametrize("change", ["absent", "disabled", "force_bypass", "delete_missing", "human_push",
                                   "other_branch", "excluded", "no_creation", "no_reviewers", "admin_bypass"])
def test_unverified_governance_blocks(change):
    rules, env = copy.deepcopy(protected()), environment()
    if change == "absent":
        rules = []
    elif change == "disabled":
        rules[0]["enforcement"] = "evaluate"
    elif change == "force_bypass":
        rules[0]["bypass_actors"] = rules[1]["bypass_actors"]
    elif change == "delete_missing":
        rules[0]["rules"] = [{"type": "non_fast_forward"}]
    elif change == "human_push":
        rules[1]["bypass_actors"].append({"actor_type": "RepositoryRole", "actor_id": 5})
    elif change == "other_branch":
        rules[0]["conditions"]["ref_name"]["include"] = ["refs/heads/main"]
    elif change == "excluded":
        rules[0]["conditions"]["ref_name"]["exclude"] = ["refs/heads/plugin-stable"]
    elif change == "no_creation":
        rules[1]["rules"] = [{"type": "update"}]
    elif change == "no_reviewers":
        env["protection_rules"] = []
    elif change == "admin_bypass":
        env["can_admins_bypass"] = True
    assert rg.problems(rules, env)


def test_unreadable_governance_is_not_an_empty_success():
    def denied(_):
        raise RuntimeError("403")
    with pytest.raises(rg.GovernanceError, match="cannot verify"):
        rg.check("tsyyan/buddie", api=denied)
