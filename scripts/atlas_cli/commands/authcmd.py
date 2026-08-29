from __future__ import annotations

import json
import sys

from ..core.auth import resolve_auth
from ..core.authstore import load, remove_host, upsert_host
from ..core.gitops import has_git


def run(action: str, host: str, ssh: bool, as_json: bool, org: str | None = None) -> int:
    action = (action or "login").lower()
    if action in ("login", "status"):
        if not has_git():
            return _out({"ok": False, "error": "git not on PATH (headless: auth login is unavailable)"}, as_json, 2)
        result = resolve_auth(host, want_ssh=ssh)
        if result.error:
            return _out({"ok": False, "error": result.error}, as_json, 2)
        upsert_host(host, result.backend, result.ssh, org)
        return _out(
            {
                "ok": True,
                "action": action,
                "host": host,
                "backend": result.backend,
                "ssh": result.ssh,
                "recorded": True,
                "token_stored": False,
            },
            as_json,
            0,
        )
    if action == "list":
        try:
            doc = load()
        except ValueError as e:
            return _out({"ok": False, "error": str(e)}, as_json, 2)
        rows = doc.get("hosts") or []
        if as_json:
            print(json.dumps({"ok": True, "hosts": rows}))
        elif not rows:
            print("(no recorded hosts)")
        else:
            for row in rows:
                extra = f" org={row['org']}" if row.get("org") else ""
                print(f"{row.get('host')} backend={row.get('backend')} ssh={row.get('ssh')}{extra}")
        return 0
    if action == "logout":
        removed = remove_host(host, org)
        return _out({"ok": True, "removed": removed, "host": host}, as_json, 0)
    return _out({"ok": False, "error": f"unknown action {action}"}, as_json, 2)


def _out(payload: dict, as_json: bool, code: int) -> int:
    if as_json:
        print(json.dumps(payload))
    elif not payload.get("ok"):
        print(f"atlas auth: {payload.get('error')}", file=sys.stderr)
    elif payload.get("action"):
        print(f"{payload.get('host')} backend={payload.get('backend')} recorded=yes token_stored=no")
    elif "removed" in payload:
        print("removed" if payload["removed"] else "nothing to remove")
    return code
