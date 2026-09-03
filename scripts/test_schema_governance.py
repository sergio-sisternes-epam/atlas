#!/usr/bin/env python3
"""Smokes for work 2026-09-03-atlas-schema-governance. Run: python3 scripts/test_schema_governance.py"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"


def run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ATLAS), *args],
        cwd=cwd or ROOT,
        text=True,
        capture_output=True,
    )


def write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name} {detail}".rstrip())
        if not ok:
            failed.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="atlas-schema-"))
    try:
        store = tmp / "store"
        print(f"store={store}")

        # init-core-only
        r = run(["init", "--root", str(store), "--json"])
        schema = json.loads((store / "SCHEMA.json").read_text())
        check(
            "init-core-only",
            r.returncode == 0 and "kva" not in schema and not (store / "schema.d").exists(),
            f"exit={r.returncode}",
        )

        # new-writes-schema-d
        r = run(["schema", "new", "foo", "--root", str(store), "--claim", "experiments", "--json"])
        check(
            "new-writes-schema-d",
            r.returncode == 0 and (store / "schema.d" / "foo.json").is_file(),
            f"exit={r.returncode} {r.stdout[:200]}",
        )

        # knowledge-folder-ok — free-layout folder not on receipt
        write(
            store / "notes" / "idea.md",
            "---\ntype: document\ntitle: idea\ncreated: 2026-09-03\n---\n\n## Content\n\nA free-layout note that is long enough for compile.\n",
        )
        write(store / "notes" / "index.md", "# Notes\n\n- idea\n")
        r = run(["compile", "--root", str(store), "--json"])
        payload = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}
        crit_ids = [i.get("id") for i in payload.get("critical") or []]
        check(
            "knowledge-folder-ok",
            r.returncode != 2 and "overlay_undeclared_root" not in crit_ids,
            f"exit={r.returncode} crit={crit_ids} err={r.stderr[:200]}",
        )

        # undeclared-root-fails — tamper receipt + root file
        rec_path = store / "schema.d" / "foo.receipt.json"
        rec = json.loads(rec_path.read_text())
        rec["written"] = list(rec.get("written") or []) + ["evil.md"]
        rec_path.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
        write(store / "evil.md", "---\ntype: document\ntitle: evil\ncreated: 2026-09-03\n---\n\n## Content\n\nUndeclared root dump from a fake CLI write.\n")
        r = run(["compile", "--root", str(store), "--json"])
        payload = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}
        crit_ids = [i.get("id") for i in payload.get("critical") or []]
        check(
            "undeclared-root-fails",
            r.returncode == 2 and "overlay_undeclared_root" in crit_ids,
            f"exit={r.returncode} crit={crit_ids}",
        )
        rec["written"] = [w for w in rec["written"] if w != "evil.md"]
        rec_path.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
        (store / "evil.md").unlink()

        # core-key-clash-fails
        ov = json.loads((store / "schema.d" / "foo.json").read_text())
        ov["atlas_id"] = "hijack"
        (store / "schema.d" / "foo.json").write_text(json.dumps(ov, indent=2) + "\n")
        r = run(["compile", "--root", str(store), "--json"])
        payload = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}
        crit_ids = [i.get("id") for i in payload.get("critical") or []]
        check(
            "core-key-clash-fails",
            r.returncode == 2 and "overlay_core_clash" in crit_ids,
            f"exit={r.returncode} crit={crit_ids}",
        )
        del ov["atlas_id"]
        (store / "schema.d" / "foo.json").write_text(json.dumps(ov, indent=2) + "\n")

        # overlay must not mutate core type
        ov["templates"] = {
            "by_type": {
                "work": {
                    "file": "templates/work.md",
                    "frontmatter": {"required": ["type", "title", "created", "work_id"]},
                }
            }
        }
        (store / "schema.d" / "foo.json").write_text(json.dumps(ov, indent=2) + "\n")
        r = run(["compile", "--root", str(store), "--json"])
        payload = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}
        crit_ids = [i.get("id") for i in payload.get("critical") or []]
        check(
            "core-type-mutate-fails",
            r.returncode == 2 and "overlay_core_type" in crit_ids,
            f"exit={r.returncode} crit={crit_ids}",
        )
        ov["templates"] = {"by_type": {}}
        (store / "schema.d" / "foo.json").write_text(json.dumps(ov, indent=2) + "\n")

        # overlay-key-clash-fails
        r = run(["schema", "new", "bar", "--root", str(store), "--json"])
        foo = json.loads((store / "schema.d" / "foo.json").read_text())
        foo["kva"] = {"values": ["forming"]}
        (store / "schema.d" / "foo.json").write_text(json.dumps(foo, indent=2) + "\n")
        bar = json.loads((store / "schema.d" / "bar.json").read_text())
        bar["kva"] = {"values": ["alive"]}
        (store / "schema.d" / "bar.json").write_text(json.dumps(bar, indent=2) + "\n")
        r = run(["compile", "--root", str(store), "--json"])
        payload = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}
        crit_ids = [i.get("id") for i in payload.get("critical") or []]
        check(
            "overlay-key-clash-fails",
            r.returncode == 2 and "overlay_key_clash" in crit_ids,
            f"exit={r.returncode} crit={crit_ids}",
        )
        del bar["kva"]
        (store / "schema.d" / "bar.json").write_text(json.dumps(bar, indent=2) + "\n")
        del foo["kva"]
        (store / "schema.d" / "foo.json").write_text(json.dumps(foo, indent=2) + "\n")

        # install required-key change without --force
        contrib = tmp / "contrib"
        write(
            contrib / "SCHEMA.overlay.json",
            json.dumps(
                {
                    "contribution_id": "foo",
                    "claimed_folders": [],
                    "templates": {
                        "by_type": {
                            "star": {
                                "frontmatter": {"required": ["type", "title", "created", "kva"]}
                            }
                        }
                    },
                },
                indent=2,
            )
            + "\n",
        )
        r = run(["schema", "install", str(contrib), "--root", str(store), "--json"])
        check(
            "install-required-keys-need-force",
            r.returncode == 2,
            f"exit={r.returncode} {r.stdout[:180]}",
        )
        r = run(["schema", "install", str(contrib), "--root", str(store), "--force", "--json"])
        check("install-force-ok", r.returncode == 0, f"exit={r.returncode} {r.stdout[:180]}")

        # uninstall-removes-overlay
        r = run(["schema", "uninstall", "foo", "--root", str(store), "--json"])
        gone = not (store / "schema.d" / "foo.json").is_file()
        r2 = run(["compile", "--root", str(store), "--json"])
        payload = json.loads(r2.stdout) if r2.stdout.strip().startswith("{") else {}
        still = any("foo.json" in str(i.get("path")) for i in payload.get("critical") or [])
        check(
            "uninstall-removes-overlay",
            r.returncode == 0 and gone and r2.returncode != 2,
            f"uninstall={r.returncode} gone={gone} compile={r2.returncode} still={still}",
        )

        # path-registry-lists-schema
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        pathf = ROOT / "references" / "paths" / "schema.md"
        check("path-registry-lists-schema", "| **schema** |" in skill and pathf.is_file())

        # schema new invalid id
        r = run(["schema", "new", "Not_Kebab", "--root", str(store), "--json"])
        check("kebab-id-required", r.returncode == 2, f"exit={r.returncode}")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failed:
        print(f"FAILED {len(failed)}: {', '.join(failed)}")
        return 1
    print("All schema-governance smokes passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
