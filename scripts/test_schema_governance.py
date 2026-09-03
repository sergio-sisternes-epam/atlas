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
        schema_file = store / "SCHEMA.json"
        if r.returncode != 0 or not schema_file.is_file():
            check(
                "init-core-only",
                False,
                f"exit={r.returncode} missing SCHEMA.json stderr={r.stderr[:200]}",
            )
            return 1
        schema = json.loads(schema_file.read_text())
        check(
            "init-core-only",
            "kva" not in schema and not (store / "schema.d").exists(),
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

        foo["templates"] = {
            "by_type": {"comet": {"frontmatter": {"required": ["type", "title"]}}}
        }
        bar["templates"] = {
            "by_type": {"comet": {"frontmatter": {"required": ["type", "title", "created"]}}}
        }
        (store / "schema.d" / "foo.json").write_text(json.dumps(foo, indent=2) + "\n")
        (store / "schema.d" / "bar.json").write_text(json.dumps(bar, indent=2) + "\n")
        r = run(["compile", "--root", str(store), "--json"])
        payload = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}
        crit_ids = [i.get("id") for i in payload.get("critical") or []]
        check(
            "overlay-type-clash-not-core-type",
            r.returncode == 2
            and "overlay_key_clash" in crit_ids
            and "overlay_core_type" not in crit_ids,
            f"exit={r.returncode} crit={crit_ids}",
        )
        foo["templates"] = {"by_type": {}}
        bar["templates"] = {"by_type": {}}
        (store / "schema.d" / "foo.json").write_text(json.dumps(foo, indent=2) + "\n")
        (store / "schema.d" / "bar.json").write_text(json.dumps(bar, indent=2) + "\n")

        # claimed_folders are prefixes (foo/bar allows foo/bar/x.md)
        r = run(["schema", "new", "nested", "--root", str(store), "--claim", "foo/bar", "--json"])
        nest = json.loads((store / "schema.d" / "nested.json").read_text())
        recn = json.loads((store / "schema.d" / "nested.receipt.json").read_text())
        recn["written"] = list(recn.get("written") or []) + ["foo/bar/page.md"]
        (store / "schema.d" / "nested.receipt.json").write_text(json.dumps(recn, indent=2) + "\n")
        write(
            store / "foo" / "bar" / "page.md",
            "---\ntype: document\ntitle: nested\ncreated: 2026-09-03\n---\n\n## Content\n\nClaimed prefix write is allowed and this body is long enough for compile.\n",
        )
        write(store / "foo" / "bar" / "index.md", "# Nested\n\nIndex for the claimed prefix folder used by the overlay smoke.\n")
        write(store / "foo" / "index.md", "# Foo\n\nParent folder index so compile does not fail on thin listing pages.\n")
        r = run(["compile", "--root", str(store), "--json"])
        payload = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}
        crit_ids = [i.get("id") for i in payload.get("critical") or []]
        check(
            "claimed-prefix-nested-ok",
            r.returncode != 2 and "overlay_undeclared_root" not in crit_ids,
            f"exit={r.returncode} crit={crit_ids}",
        )
        recn["written"] = list(recn.get("written") or []) + ["templates/../../evil-out.md"]
        (store / "schema.d" / "nested.receipt.json").write_text(json.dumps(recn, indent=2) + "\n")
        r = run(["compile", "--root", str(store), "--json"])
        payload = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}
        crit_ids = [i.get("id") for i in payload.get("critical") or []]
        check(
            "receipt-dotdot-fails",
            r.returncode == 2 and "overlay_undeclared_root" in crit_ids,
            f"exit={r.returncode} crit={crit_ids}",
        )
        recn["written"] = [w for w in recn["written"] if ".." not in str(w)]
        (store / "schema.d" / "nested.receipt.json").write_text(json.dumps(recn, indent=2) + "\n")
        run(["schema", "uninstall", "nested", "--root", str(store), "--json"])

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
        r = run(["schema", "install", str(contrib), "--root", str(store), "--json"])
        check(
            "install-same-fingerprint-no-force",
            r.returncode == 0,
            f"exit={r.returncode} {r.stdout[:180]}",
        )

        write(
            contrib / "templates" / "star.md",
            "---\ntype: star\ntitle: \"\"\ncreated: \"\"\n---\n\n## Pending\n\nTemplate copied on install.\n",
        )
        r = run(["schema", "install", str(contrib), "--root", str(store), "--force", "--json"])
        r2 = run(["compile", "--root", str(store), "--json"])
        payload = json.loads(r2.stdout) if r2.stdout.strip().startswith("{") else {}
        crit_ids = [i.get("id") for i in payload.get("critical") or []]
        check(
            "install-templates-receipt-ok",
            r.returncode == 0 and r2.returncode != 2 and "overlay_undeclared_root" not in crit_ids,
            f"install={r.returncode} compile={r2.returncode} crit={crit_ids}",
        )

        bad = tmp / "bad-type"
        write(
            bad / "SCHEMA.overlay.json",
            json.dumps(
                {
                    "contribution_id": "evil",
                    "claimed_folders": [],
                    "templates": {"by_type": {"../etc": {"frontmatter": {"required": ["type"]}}}},
                }
            )
            + "\n",
        )
        r = run(["schema", "install", str(bad), "--root", str(store), "--json"])
        check("install-rejects-path-type", r.returncode == 2, f"exit={r.returncode} {r.stdout[:180]}")

        bad2 = tmp / "bad-by-type"
        write(
            bad2 / "SCHEMA.overlay.json",
            json.dumps(
                {
                    "contribution_id": "shapeless",
                    "claimed_folders": [],
                    "templates": {"by_type": ["not", "an", "object"]},
                }
            )
            + "\n",
        )
        r = run(["schema", "install", str(bad2), "--root", str(store), "--json"])
        check("install-rejects-by-type-list", r.returncode == 2, f"exit={r.returncode} {r.stdout[:180]}")

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
