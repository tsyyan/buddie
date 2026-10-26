"""Read live GitHub rules and environment before a plugin-stable promotion. Never changes settings.

Two separate active rulesets are intentional: immutable history has NO bypass actors; branch creation and
updates permit only GitHub Actions. The protected pypi environment still requires human authorization.
An unavailable API or an unfamiliar ruleset shape blocks promotion. Owners configure settings separately.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess

BRANCH = "refs/heads/plugin-stable"
ACTIONS_APP_ID = 15368


class GovernanceError(RuntimeError):
    pass


def problems(rulesets: list[dict], environment: dict) -> list[str]:
    immutable, controlled = set(), set()
    for ruleset in rulesets:
        names = ruleset.get("conditions", {}).get("ref_name", {})
        # Exact targeting avoids guessing GitHub glob precedence, inherited exclusions or default-branch tokens.
        if (ruleset.get("target") != "branch" or ruleset.get("enforcement") != "active"
                or BRANCH not in names.get("include", []) or names.get("exclude")):
            continue
        actors = ruleset.get("bypass_actors", [])
        types = {r.get("type") for r in ruleset.get("rules", [])}
        if not actors:
            immutable |= types & {"non_fast_forward", "deletion"}
        if actors == [{"actor_id": ACTIONS_APP_ID, "actor_type": "Integration", "bypass_mode": "always"}]:
            controlled |= types & {"creation", "update"}
    errors = [f"plugin-stable lacks a no-bypass {r} rule" for r in
              sorted({"non_fast_forward", "deletion"} - immutable)]
    errors += [f"plugin-stable lacks Actions-only {r} protection" for r in
               sorted({"creation", "update"} - controlled)]
    reviewers = [r for r in environment.get("protection_rules", [])
                 if r.get("type") == "required_reviewers" and r.get("reviewers")]
    if environment.get("name") != "pypi" or not reviewers or environment.get("can_admins_bypass") is not False:
        errors.append("pypi environment needs required reviewers with admin bypass disabled")
    return errors


def _api(path: str):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, check=True, timeout=30)
    return json.loads(out.stdout)


def check(repository: str, *, api=_api) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise GovernanceError("invalid repository")
    try:
        listing = api(f"repos/{repository}/rulesets?includes_parents=true&per_page=100")
        if not isinstance(listing, list) or len(listing) >= 100:
            raise ValueError("ruleset inventory is invalid or may be truncated")
        rulesets = [api(f"repos/{repository}/rulesets/{r['id']}") for r in listing]
        environment = api(f"repos/{repository}/environments/pypi")
        errors = problems(rulesets, environment)
    except Exception as error:
        raise GovernanceError(f"cannot verify live release governance: {type(error).__name__}") from error
    if errors:
        raise GovernanceError("; ".join(errors))
    return {"repository": repository, "branch": BRANCH, "environment": "pypi", "verified": True,
            "ruleset_ids": [r["id"] for r in listing]}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repository", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.repository), indent=2))
    except GovernanceError as error:
        parser.exit(1, f"release_governance: {error}\n")


if __name__ == "__main__":
    main()
