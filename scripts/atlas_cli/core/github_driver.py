"""Post-git GitHub driver for shared atlas branch protection."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from .gitops import SHARED_BRANCH


RULESET_NAME = "atlas-no-direct-push"


def host_is_github(host: str) -> bool:
    h = (host or "").lower()
    return h == "github.com" or h.endswith(".ghe.com")


def ruleset_payload(branch: str = SHARED_BRANCH) -> dict[str, Any]:
    return {
        "name": RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "conditions": {
            "ref_name": {
                "include": [f"refs/heads/{branch}"],
                "exclude": [],
            }
        },
        "rules": [
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 0,
                    "dismiss_stale_reviews_on_push": False,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": False,
                },
            },
            {"type": "deletion"},
            {"type": "non_fast_forward"},
        ],
        "bypass_actors": [],
    }


def protect_atlas_branch(atlas_id: str, branch: str = SHARED_BRANCH) -> tuple[int, str]:
    """Create the no-direct-push ruleset. Warn-and-continue: always return 0.

    Second value is a warning (empty if applied or already present).
    """
    parts = atlas_id.split("/", 2)
    if len(parts) != 3:
        return 0, f"github driver skipped: unparseable id {atlas_id}"
    host, org, repo = parts
    if not host_is_github(host):
        return (
            0,
            "github driver skipped: self-hosted git has no Atlas ruleset; "
            f"protect branch '{branch}' on the server if you can",
        )
    if shutil.which("gh") is None:
        return 0, (
            "github driver skipped: gh not on PATH; "
            f"protect branch {branch} manually"
        )
    owner_repo = f"{org}/{repo}"
    env_host = [] if host == "github.com" else ["--hostname", host]
    listed = subprocess.run(
        ["gh", "api", *env_host, f"repos/{owner_repo}/rulesets"],
        capture_output=True,
        text=True,
        check=False,
    )
    if listed.returncode == 0:
        try:
            rows = json.loads(listed.stdout or "[]")
        except json.JSONDecodeError:
            rows = []
        if isinstance(rows, list) and any(
            isinstance(r, dict) and r.get("name") == RULESET_NAME for r in rows
        ):
            return 0, ""
    created = subprocess.run(
        [
            "gh",
            "api",
            *env_host,
            "--method",
            "POST",
            f"repos/{owner_repo}/rulesets",
            "--input",
            "-",
        ],
        input=json.dumps(ruleset_payload(branch)),
        capture_output=True,
        text=True,
        check=False,
    )
    if created.returncode != 0:
        err = (created.stderr or created.stdout or "ruleset create failed").strip()
        return 0, f"github driver skipped: {err}"
    return 0, ""
