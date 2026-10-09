#!/usr/bin/env python3
"""Contribution extension slot: one package-metadata key per overlay.

The slot is the root key equal to contribution_id with '-' replaced by '_'.
It must be an object, is never merged into the effective schema, and is
ignored by core. Every other extra overlay root key is still rejected on
SCHEMA 2.0. `schema upgrade --to 2.0` checks installed overlays too.

Released overlays under fixtures/contributions/ are installed verbatim.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"
FIXTURES = ROOT / "fixtures" / "contributions"
sys.path.insert(0, str(Path(__file__).resolve().parent))

from atlas_cli.core.overlay import extension_key, merge_overlays  # noqa: E402
from atlas_cli.core.recall_config import validate_contribution  # noqa: E402

RELEASED = {
    "atlas-tasks-v0.6.0": ("atlas-tasks", "atlas_tasks"),
    "atlas-todo-v0.2.0": ("atlas-todo", "atlas_todo"),
}


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ATLAS), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


def out(r: subprocess.CompletedProcess[str]) -> str:
    return (r.stdout + r.stderr).strip()


def as_json(r: subprocess.CompletedProcess[str]) -> dict:
    text = r.stdout.strip()
    return json.loads(text) if text.startswith("{") else {}


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}".rstrip())
        if not ok:
            failed.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="atlas-overlay-ext-"))
    try:
        stores = tmp / "stores"
        sources = tmp / "src"

        def store(name: str, version: str = "1.0") -> Path:
            s = stores / name
            args = ["init", "--root", str(s), "--json"]
            if version == "2.0":
                args[1:1] = ["--schema-version", "2.0"]
            r = run(args)
            if r.returncode != 0:
                check(f"{name}-init", False, out(r)[:200])
            return s

        def overlay(name: str, body: dict) -> Path:
            d = sources / name
            d.mkdir(parents=True, exist_ok=True)
            (d / "SCHEMA.overlay.json").write_text(json.dumps(body, indent=2) + "\n")
            return d

        def install(src: Path, s: Path) -> subprocess.CompletedProcess[str]:
            return run(["schema", "install", str(src), "--root", str(s)])

        def compile_(s: Path) -> subprocess.CompletedProcess[str]:
            return run(["compile", "--root", str(s)])

        def effective(s: Path) -> dict:
            core = json.loads((s / "CONTRACT.json").read_text())
            merged, critical, _ = merge_overlays(core, s)
            return {"merged": merged, "critical": critical}

        # Slot naming rule.
        check("slot-name-kebab", extension_key("atlas-tasks") == "atlas_tasks")
        check("slot-name-single", extension_key("discuss") == "discuss")
        for cid in ("memory", "atlas-release", "claimed-folders", "contribution-id", "schema-version", "templates"):
            check(f"slot-reserved-{cid}", extension_key(cid) is None)
        check("slot-invalid-id", extension_key("Atlas_Tasks") is None and extension_key("") is None)

        # P1: released overlays install and compile on SCHEMA 2.0 as shipped.
        for fx, (cid, slot) in RELEASED.items():
            src = FIXTURES / fx
            body = json.loads((src / "SCHEMA.overlay.json").read_text())
            check(f"p1-{fx}-fixture-has-slot", body.get("contribution_id") == cid and isinstance(body.get(slot), dict))
            check(f"p1-{fx}-validate", validate_contribution(body) == [], str(validate_contribution(body)))
            s = store(f"p1-{fx}", "2.0")
            r = install(src, s)
            check(f"p1-{fx}-install-2.0", r.returncode == 0, out(r)[:300])
            r = compile_(s)
            check(f"p1-{fx}-compile-2.0", r.returncode == 0, out(r)[-300:])
            eff = effective(s)
            check(f"p1-{fx}-not-merged", slot not in eff["merged"] and not eff["critical"], str(eff["critical"])[:200])

        v06 = FIXTURES / "atlas-tasks-v0.6.0"

        # P2: install on 1.0, upgrade to 2.0, compile.
        s = store("p2")
        r = install(v06, s)
        check("p2-install-1.0", r.returncode == 0, out(r)[:300])
        pre = as_json(run(["schema", "upgrade", "--to", "2.0", "--root", str(s), "--json"]))
        check("p2-upgrade-preview-ok", pre.get("ok") is True, str(pre.get("target_errors")))
        r = run(["schema", "upgrade", "--to", "2.0", "--apply", "--root", str(s), "--json"])
        check("p2-upgrade-apply", r.returncode == 0, out(r)[:300])
        r = compile_(s)
        check("p2-compile-after-upgrade", r.returncode == 0, out(r)[-300:])

        # P3: 1.0 store keeps installing and compiling the overlay as shipped.
        s = store("p3")
        r = install(v06, s)
        check("p3-install-1.0", r.returncode == 0, out(r)[:300])
        r = compile_(s)
        check("p3-compile-1.0", r.returncode == 0, out(r)[-300:])
        check("p3-not-merged", "atlas_tasks" not in effective(s)["merged"])

        # N: everything except the one object slot is still rejected on 2.0.
        base = {"contribution_id": "atlas-tasks", "claimed_folders": ["tasks"]}
        negatives = {
            "x-prefix": ({**base, "x-atlas-tasks": {"a": 1}}, ["x-atlas-tasks", "extension key 'atlas_tasks'"]),
            "other-package-slot": ({**base, "other_package": {"a": 1}}, ["other_package"]),
            "slot-plus-extra": ({**base, "atlas_tasks": {"a": 1}, "kva": {}}, ["'kva'"]),
            "slot-not-object": ({**base, "atlas_tasks": "note"}, ["extension metadata must be an object"]),
            "reserved-atlas-release": ({"contribution_id": "atlas-release", "atlas_release": {"a": 1}}, ["atlas_release"]),
            "reserved-memory": ({"contribution_id": "memory", "memory": {"rung": "error"}}, ["memory"]),
        }
        for name, (body, needles) in negatives.items():
            s = store(f"n-{name}", "2.0")
            r = install(overlay(f"n-{name}", body), s)
            text = out(r)
            check(
                f"n-{name}-install-2.0-rejected",
                r.returncode == 2 and all(n in text for n in needles),
                text[:300],
            )
            check(f"n-{name}-nothing-written", not (s / "schema.d").exists() or not any((s / "schema.d").glob("*.json")))

        # N2: another overlay squatting the slot name clashes with its owner.
        s = store("n2")
        install(v06, s)
        install(overlay("n2-squat", {"contribution_id": "zz-squat", "atlas_tasks": {"evil": True}}), s)
        r = compile_(s)
        check("n2-squat-clash", r.returncode == 2 and "overlay_key_clash" in out(r), out(r)[-300:])

        # N3: upgrade preview blocks on installed overlays that fail 2.0 rules.
        s = store("n3")
        r = install(overlay("n3-kva", {"contribution_id": "discuss", "kva": {"values": ["forming"]}}), s)
        check("n3-install-1.0", r.returncode == 0, out(r)[:300])
        r = run(["schema", "upgrade", "--to", "2.0", "--dry-run", "--root", str(s), "--json"])
        pre = as_json(r)
        errs = " ".join(pre.get("target_errors") or [])
        check("n3-upgrade-blocked", r.returncode == 2 and pre.get("ok") is False and "kva" in errs, errs[:300])
        r = run(["schema", "upgrade", "--to", "2.0", "--apply", "--root", str(s), "--json"])
        schema = json.loads((s / "CONTRACT.json").read_text())
        check("n3-apply-refused", r.returncode == 2 and schema.get("schema_version") == "1.0", out(r)[:200])

        # N3b: a non-object slot is legacy-tolerated on 1.0 but blocks upgrade.
        s = store("n3b")
        r = install(overlay("n3b-str", {**base, "atlas_tasks": "note"}), s)
        check("n3b-install-1.0", r.returncode == 0, out(r)[:300])
        pre = as_json(run(["schema", "upgrade", "--to", "2.0", "--root", str(s), "--json"]))
        errs = " ".join(pre.get("target_errors") or [])
        check("n3b-upgrade-blocked", pre.get("ok") is False and "overlay_extension" in errs, errs[:300])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"FAILED: {len(failed)} — {', '.join(failed)}")
        return 1
    print("overlay extension: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
