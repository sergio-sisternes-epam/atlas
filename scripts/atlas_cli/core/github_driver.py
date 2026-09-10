"""Post-git GitHub driver for shared atlas branch protection."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from .gitops import SHARED_BRANCH


RULESET_NAME = "atlas-no-direct-push"


def github_hostname(host: str) -> str:
    """Host without a trailing :port so GHE atlas_ids still match."""
    h = (host or "").strip().lower()
    if h.startswith("[") and "]" in h:
        return h[1 : h.find("]")]
    if ":" in h:
        name, port = h.rsplit(":", 1)
        if port.isdigit():
            return name
    return h


def host_is_github(host: str) -> bool:
    h = github_hostname(host)
    return h == "github.com" or h.endswith(".ghe.com")


def ruleset_targets_branch(ruleset: dict[str, Any], branch: str) -> bool:
    include = ((ruleset.get("conditions") or {}).get("ref_name") or {}).get(
        "include"
    ) or []
    wanted = f"refs/heads/{branch}"
    return wanted in include or "~ALL" in include


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
    hostname = github_hostname(host)
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
    env_host = [] if hostname == "github.com" else ["--hostname", hostname]
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
        match = next(
            (
                r
                for r in rows
                if isinstance(r, dict) and r.get("name") == RULESET_NAME
            ),
            None,
        ) if isinstance(rows, list) else None
        if match:
            detail = match
            rid = match.get("id")
            if rid is not None:
                got = subprocess.run(
                    ["gh", "api", *env_host, f"repos/{owner_repo}/rulesets/{rid}"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if got.returncode == 0:
                    try:
                        loaded = json.loads(got.stdout or "{}")
                    except json.JSONDecodeError:
                        loaded = None
                    if isinstance(loaded, dict):
                        detail = loaded
            if ruleset_targets_branch(detail, branch):
                return 0, ""
            return (
                0,
                f"github driver skipped: ruleset {RULESET_NAME} "
                f"does not target branch {branch}",
            )
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
