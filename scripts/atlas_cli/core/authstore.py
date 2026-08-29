"""User-level auth catalogue. Host/backend only — never persist tokens."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

AUTH_NAME = "auth.json"


def auth_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "atlas" / AUTH_NAME


def load() -> dict[str, Any]:
    fp = auth_path()
    if not fp.is_file():
        return {"version": 1, "hosts": []}
    data = json.loads(fp.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("auth.json version must be 1")
    if not isinstance(data.get("hosts"), list):
        raise ValueError("auth.json hosts must be a list")
    for row in data["hosts"]:
        if isinstance(row, dict) and any(k in row for k in ("token", "pat", "password", "secret")):
            raise ValueError("auth.json must not contain token fields")
    return data


def save(doc: dict[str, Any]) -> Path:
    fp = auth_path()
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return fp


def upsert_host(host: str, backend: str, ssh: bool, org: str | None = None) -> Path:
    doc = load()
    hosts = [h for h in doc["hosts"] if not (h.get("host") == host and h.get("org") == org)]
    row = {"host": host, "backend": backend, "ssh": bool(ssh)}
    if org:
        row["org"] = org
    hosts.append(row)
    doc["hosts"] = hosts
    return save(doc)


def lookup(host: str, org: str | None = None) -> dict | None:
    """Org-specific row wins over host-only row."""
    try:
        doc = load()
    except ValueError:
        return None
    host_hit = None
    org_hit = None
    for row in doc.get("hosts") or []:
        if row.get("host") != host:
            continue
        if org and row.get("org") == org:
            org_hit = row
        elif not row.get("org"):
            host_hit = row
    return org_hit or host_hit


def remove_host(host: str, org: str | None = None) -> bool:
    doc = load()
    before = len(doc["hosts"])
    doc["hosts"] = [
        h
        for h in doc["hosts"]
        if not (h.get("host") == host and (org is None or h.get("org") == org))
    ]
    save(doc)
    return len(doc["hosts"]) < before
