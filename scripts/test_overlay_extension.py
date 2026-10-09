#!/usr/bin/env python3
"""Contribution extension slot: one package-metadata key per overlay.

The slot is the root key equal to contribution_id with '-' replaced by '_'.
It must be an object, is never merged into the effective contract, and is
ignored by core. Every other extra overlay root key is still rejected on
SCHEMA 2.0. `schema upgrade --to 2.0` checks installed overlays too, each
against contribution-v1, and rechecks them under the lock that `schema
install`, `schema uninstall`, `schema new`, `schema memory-rung`, `init
--force`, `memory-migrate --operation apply`, `recall activate` and `recall
disable` share. Locks are never
reclaimed and only their owner removes them.

Released overlays under fixtures/contributions/ are installed verbatim.
"""

from __future__ import annotations

import contextlib
import io
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

from atlas_cli.commands import schema_cmd  # noqa: E402
from atlas_cli.core import schema_upgrade  # noqa: E402
from atlas_cli.core.overlay import (  # noqa: E402
    extension_key,
    receipt_path,
    merge_overlays,
    overlay_path,
    write_json,
    write_receipt,
)
from atlas_cli.core.recall_config import validate_contribution  # noqa: E402

NOTE = "needs Atlas >= 0.13.1 to compile"

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
            check(f"p1-{fx}-install-2.0-reader-note", NOTE in r.stdout and f"'{slot}'" in r.stdout, r.stdout[:300])
            r = compile_(s)
            check(f"p1-{fx}-compile-2.0", r.returncode == 0, out(r)[-300:])
            eff = effective(s)
            check(f"p1-{fx}-not-merged", slot not in eff["merged"] and not eff["critical"], str(eff["critical"])[:200])

        for fx, (_cid, slot) in RELEASED.items():
            src = FIXTURES / fx

            # P2: install on 1.0, upgrade to 2.0, compile.
            s = store(f"p2-{fx}")
            r = install(src, s)
            check(f"p2-{fx}-install-1.0", r.returncode == 0, out(r)[:300])
            pre = as_json(run(["schema", "upgrade", "--to", "2.0", "--root", str(s), "--json"]))
            check(f"p2-{fx}-upgrade-preview-ok", pre.get("ok") is True, str(pre.get("target_errors")))
            r = run(["schema", "upgrade", "--to", "2.0", "--apply", "--root", str(s), "--json"])
            check(f"p2-{fx}-upgrade-apply", r.returncode == 0, out(r)[:300])
            r = compile_(s)
            check(f"p2-{fx}-compile-after-upgrade", r.returncode == 0, out(r)[-300:])

            # P3: 1.0 store keeps installing and compiling the overlay as shipped.
            s = store(f"p3-{fx}")
            r = install(src, s)
            check(f"p3-{fx}-install-1.0", r.returncode == 0, out(r)[:300])
            check(f"p3-{fx}-install-1.0-no-note", NOTE not in r.stdout, r.stdout[:300])
            r = compile_(s)
            check(f"p3-{fx}-compile-1.0", r.returncode == 0, out(r)[-300:])
            check(f"p3-{fx}-not-merged", slot not in effective(s)["merged"])

        v06 = FIXTURES / "atlas-tasks-v0.6.0"

        # Reader note: only a 2.0 install that carries the slot gets it; JSON carries it in notes.
        s = store("note-json", "2.0")
        r = run(["schema", "install", str(v06), "--root", str(s), "--json"])
        notes = as_json(r).get("notes") or []
        check("note-json", r.returncode == 0 and any(NOTE in n for n in notes), out(r)[:300])
        slot_free = {k: v for k, v in json.loads((v06 / "SCHEMA.overlay.json").read_text()).items() if k != "atlas_tasks"}
        r = run(["schema", "install", str(overlay("note-slot-free", slot_free)), "--root", str(s), "--json"])
        check("note-slot-free-reinstall", r.returncode == 0 and "notes" not in as_json(r), out(r)[:300])

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

        # N4: upgrade validates every installed overlay against contribution-v1,
        # exactly as a 2.0 install would.
        def snapshot(s: Path) -> dict:
            files = {p.name: p.read_bytes() for p in sorted((s / "schema.d").glob("*"))}
            return {"contract": (s / "CONTRACT.json").read_bytes(), "schema.d": files}

        bad_claim = {"contribution_id": "discuss", "claimed_folders": [1]}
        s = store("n4-2.0", "2.0")
        r = install(overlay("n4-claim-2.0", bad_claim), s)
        check("n4-install-2.0-rejected", r.returncode == 2 and "$.claimed_folders[0]" in out(r), out(r)[:300])
        s = store("n4")
        r = install(overlay("n4-claim", bad_claim), s)
        check("n4-install-1.0", r.returncode == 0, out(r)[:300])
        before = snapshot(s)
        r = run(["schema", "upgrade", "--to", "2.0", "--root", str(s), "--json"])
        pre = as_json(r)
        errs = " ".join(pre.get("target_errors") or [])
        check(
            "n4-upgrade-preview-blocked",
            r.returncode == 2
            and pre.get("ok") is False
            and "schema.d/discuss.json" in errs
            and "$.claimed_folders[0]" in errs,
            errs[:300],
        )
        r = run(["schema", "upgrade", "--to", "2.0", "--apply", "--root", str(s), "--json"])
        check(
            "n4-upgrade-apply-refused",
            r.returncode == 2
            and "schema.d/discuss.json" in out(r)
            and snapshot(s) == before
            and not (s / schema_upgrade.LOCK_NAME).exists(),
            out(r)[:300],
        )
        s = store("n4-valid")
        r = install(overlay("n4-valid", {"contribution_id": "discuss", "claimed_folders": ["discuss"]}), s)
        check("n4-valid-install-1.0", r.returncode == 0, out(r)[:300])
        pre = as_json(run(["schema", "upgrade", "--to", "2.0", "--root", str(s), "--json"]))
        check("n4-valid-preview-ok", pre.get("ok") is True and not pre.get("target_errors"), str(pre.get("target_errors")))
        r = run(["schema", "upgrade", "--to", "2.0", "--apply", "--root", str(s), "--json"])
        check("n4-valid-apply", r.returncode == 0, out(r)[:300])
        r = compile_(s)
        check("n4-valid-compile-after-upgrade", r.returncode == 0, out(r)[-300:])

        # L: install, uninstall and upgrade share .atlas-upgrade.lock.
        lock_name = schema_upgrade.LOCK_NAME
        s = store("l-install-blocked")
        (s / lock_name).write_text(schema_upgrade.UPGRADE_LOCK_TAG + "\n")
        r = install(v06, s)
        check(
            "l-install-refused-while-locked",
            r.returncode == 2 and lock_name in out(r) and not overlay_path(s, "atlas-tasks").exists(),
            out(r)[:300],
        )
        check("l-install-keeps-foreign-lock", (s / lock_name).is_file())

        s = store("l-install-releases")
        r = install(v06, s)
        check("l-install-releases-on-success", r.returncode == 0 and not (s / lock_name).exists(), out(r)[:200])
        s = store("l-install-releases-2.0", "2.0")
        r = install(overlay("l-bad", {**base, "kva": {}}), s)
        check("l-install-releases-on-refusal", r.returncode == 2 and not (s / lock_name).exists(), out(r)[:200])

        # L2: an install interrupted after the overlay write keeps its lock;
        # a refusal that returns normally still releases it.
        s = store("l-install-interrupted")
        original_receipt = schema_cmd.write_receipt

        def receipt_fails(*_a, **_k):
            raise OSError("simulated interruption")

        schema_cmd.write_receipt = receipt_fails
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                schema_cmd.run_install(str(v06), str(s))
            check("l-install-interrupted-raises", False, "install returned normally")
        except OSError as e:
            check("l-install-interrupted-raises", "simulated interruption" in str(e), str(e)[:200])
        finally:
            schema_cmd.write_receipt = original_receipt
        lock_text = (s / lock_name).read_text() if (s / lock_name).is_file() else ""
        check(
            "l-install-interrupted-keeps-lock",
            lock_text.split()[:1] == [schema_upgrade.INSTALL_LOCK_TAG]
            and overlay_path(s, "atlas-tasks").is_file(),
            lock_text[:100],
        )
        r = install(v06, s)
        check("l-install-interrupted-blocks-next", r.returncode == 2 and lock_name in out(r), out(r)[:200])
        s = store("l-install-refusal-inproc", "2.0")
        with contextlib.redirect_stdout(io.StringIO()):
            code = schema_cmd.run_install(str(overlay("l-bad-inproc", {**base, "kva": {}})), str(s))
        check("l-install-refusal-releases-inproc", code == 2 and not (s / lock_name).exists())

        s = store("l-upgrade-blocked")
        (s / lock_name).write_text(schema_upgrade.INSTALL_LOCK_TAG + "\n")
        r = run(["schema", "upgrade", "--to", "2.0", "--apply", "--root", str(s), "--json"])
        schema = json.loads((s / "CONTRACT.json").read_text())
        check(
            "l-upgrade-refused-while-install-holds-lock",
            r.returncode == 2
            and "schema install is running or was interrupted" in out(r)
            and (s / lock_name).read_text() == schema_upgrade.INSTALL_LOCK_TAG + "\n"
            and schema.get("schema_version") == "1.0"
            and not overlay_path(s, schema_upgrade.COMPAT_ID).exists(),
            out(r)[:300],
        )

        # R: an install that lands after the preview but before the lock is
        # caught by the recheck under the lock, before any write.
        def race(body: dict | None, name: str = "") -> Path:
            s = store(name or f"r-{body['contribution_id'] if body else 'none'}")
            original = schema_upgrade.acquire_store_lock

            def acquire_then_install(root: Path, tag: str) -> Path:
                if body is not None:
                    cid = body["contribution_id"]
                    write_json(overlay_path(root, cid), body)
                    write_receipt(root, cid, [f"schema.d/{cid}.json", f"schema.d/{cid}.receipt.json"])
                return original(root, tag)

            schema_upgrade.acquire_store_lock = acquire_then_install
            try:
                schema_upgrade.apply(s)
                return s
            finally:
                schema_upgrade.acquire_store_lock = original

        try:
            s = race({"contribution_id": "discuss", "kva": {"values": ["forming"]}})
            check("r-upgrade-refused-after-late-install", False, "apply succeeded")
        except schema_upgrade.UpgradeError as e:
            s = stores / "r-discuss"
            schema = json.loads((s / "CONTRACT.json").read_text())
            check(
                "r-upgrade-refused-after-late-install",
                "kva" in str(e)
                and schema.get("schema_version") == "1.0"
                and not overlay_path(s, schema_upgrade.COMPAT_ID).exists()
                and not (s / lock_name).exists(),
                str(e)[:300],
            )
        body = json.loads((v06 / "SCHEMA.overlay.json").read_text())
        try:
            s = race(body)
            r = compile_(s)
            check("r-upgrade-ok-after-late-valid-install", r.returncode == 0, out(r)[-300:])
        except schema_upgrade.UpgradeError as e:
            check("r-upgrade-ok-after-late-valid-install", False, str(e)[:300])

        try:
            race({"contribution_id": "discuss", "claimed_folders": [1]}, "r-envelope")
            check("r-upgrade-refused-after-late-invalid-envelope", False, "apply succeeded")
        except schema_upgrade.UpgradeError as e:
            s = stores / "r-envelope"
            schema = json.loads((s / "CONTRACT.json").read_text())
            check(
                "r-upgrade-refused-after-late-invalid-envelope",
                "schema.d/discuss.json" in str(e)
                and schema.get("schema_version") == "1.0"
                and not overlay_path(s, schema_upgrade.COMPAT_ID).exists()
                and not (s / lock_name).exists(),
                str(e)[:300],
            )

        # U: uninstall takes the same lock for its whole read/delete operation.
        def uninstall(cid: str, s: Path) -> subprocess.CompletedProcess[str]:
            return run(["schema", "uninstall", cid, "--root", str(s), "--json"])

        s = store("u-blocked")
        install(v06, s)
        for holder in (schema_upgrade.UPGRADE_LOCK_TAG, schema_upgrade.INSTALL_LOCK_TAG):
            (s / lock_name).write_text(holder + "\n")
            r = uninstall("atlas-tasks", s)
            check(
                f"u-refused-while-{holder}-holds-lock",
                r.returncode == 2
                and "Remove the lock only if" in out(r)
                and overlay_path(s, "atlas-tasks").is_file()
                and receipt_path(s, "atlas-tasks").is_file()
                and (s / lock_name).read_text() == holder + "\n",
                out(r)[:300],
            )
        (s / lock_name).unlink()

        s = store("u-releases")
        install(v06, s)
        r = uninstall("atlas-tasks", s)
        check(
            "u-releases-on-success",
            r.returncode == 0
            and not overlay_path(s, "atlas-tasks").exists()
            and not receipt_path(s, "atlas-tasks").exists()
            and not (s / lock_name).exists(),
            out(r)[:300],
        )
        r = uninstall("atlas-tasks", s)
        check("u-releases-on-refusal", r.returncode == 2 and not (s / lock_name).exists(), out(r)[:200])

        # U2: an uninstall interrupted mid-delete keeps its lock and blocks the next writer.
        s = store("u-interrupted")
        install(v06, s)
        original_resolve = schema_cmd.resolve_under_root

        def resolve_fails(*_a, **_k):
            raise OSError("simulated interruption")

        schema_cmd.resolve_under_root = resolve_fails
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                schema_cmd.run_uninstall("atlas-tasks", str(s))
            check("u-interrupted-raises", False, "uninstall returned normally")
        except OSError as e:
            check("u-interrupted-raises", "simulated interruption" in str(e), str(e)[:200])
        finally:
            schema_cmd.resolve_under_root = original_resolve
        lock_text = (s / lock_name).read_text() if (s / lock_name).is_file() else ""
        check("u-interrupted-keeps-lock", lock_text.split()[:1] == [schema_upgrade.UNINSTALL_LOCK_TAG], lock_text[:100])
        r = run(["schema", "upgrade", "--to", "2.0", "--apply", "--root", str(s), "--json"])
        check(
            "u-interrupted-blocks-upgrade",
            r.returncode == 2 and "schema uninstall is running or was interrupted" in out(r),
            out(r)[:300],
        )

        # U3: an uninstall attempted while an upgrade holds the lock (after the
        # compat overlay is written, before the contract is replaced) cannot
        # delete atlas-compat-v1 or any other overlay.
        s = store("u-race")
        install(v06, s)
        original_write_receipt = schema_upgrade.write_receipt
        attempts: dict[str, int] = {}

        def write_receipt_then_uninstall(root: Path, cid: str, *a, **k):
            res = original_write_receipt(root, cid, *a, **k)
            for victim in (schema_upgrade.COMPAT_ID, "atlas-tasks"):
                with contextlib.redirect_stdout(io.StringIO()):
                    attempts[victim] = schema_cmd.run_uninstall(victim, str(root))
            return res

        schema_upgrade.write_receipt = write_receipt_then_uninstall
        try:
            schema_upgrade.apply(s)
            upgrade_err = ""
        except schema_upgrade.UpgradeError as e:
            upgrade_err = str(e)
        finally:
            schema_upgrade.write_receipt = original_write_receipt
        schema = json.loads((s / "CONTRACT.json").read_text())
        check(
            "u-race-uninstall-refused",
            attempts == {schema_upgrade.COMPAT_ID: 2, "atlas-tasks": 2},
            str(attempts),
        )
        check(
            "u-race-overlays-kept",
            not upgrade_err
            and schema.get("schema_version") == "2.0"
            and overlay_path(s, schema_upgrade.COMPAT_ID).is_file()
            and receipt_path(s, schema_upgrade.COMPAT_ID).is_file()
            and overlay_path(s, "atlas-tasks").is_file()
            and receipt_path(s, "atlas-tasks").is_file()
            and not (s / lock_name).exists(),
            upgrade_err[:300],
        )
        r = compile_(s)
        check("u-race-compile-after-upgrade", r.returncode == 0, out(r)[-300:])

        # W: schema new, schema memory-rung, init --force and memory-migrate apply
        # take the same lock; while it is held each exits 2 and writes nothing.
        def snapshot(s: Path) -> dict[str, bytes]:
            return {
                str(p.relative_to(s)): p.read_bytes()
                for p in sorted(s.rglob("*"))
                if p.is_file() and p.name != lock_name
            }

        def restampable(s: Path) -> None:
            contract = s / "CONTRACT.json"
            body = json.loads(contract.read_text())
            body["atlas_release"] = "0.13.0-beta.7"
            contract.write_text(json.dumps(body, indent=2) + "\n")

        writers = {
            "new": lambda s: ["schema", "new", "atlas-notes", "--root", str(s), "--json"],
            "new-compat": lambda s: ["schema", "new", schema_upgrade.COMPAT_ID, "--root", str(s), "--json"],
            "memory-rung": lambda s: ["schema", "memory-rung", "--set", "warn", "--root", str(s), "--json"],
            "init-force": lambda s: ["init", "--force", "--root", str(s), "--json"],
            "memory-migrate-restamp": lambda s: [
                "memory-migrate", "--operation", "apply", "--batch", "restamp", "--root", str(s), "--json"
            ],
            "memory-migrate-contract-file": lambda s: [
                "memory-migrate", "--operation", "apply", "--batch", "contract-file", "--root", str(s), "--json"
            ],
        }
        s = store("w-blocked")
        install(v06, s)
        restampable(s)
        for holder in (schema_upgrade.UPGRADE_LOCK_TAG, schema_upgrade.INSTALL_LOCK_TAG):
            (s / lock_name).write_text(holder + "\n")
            before = snapshot(s)
            for name, argv in writers.items():
                r = run(argv(s))
                check(
                    f"w-{name}-refused-while-{holder}-holds-lock",
                    r.returncode == 2
                    and "Remove the lock only if" in out(r)
                    and snapshot(s) == before
                    and (s / lock_name).read_text() == holder + "\n",
                    out(r)[:300],
                )
        r = run(["memory-migrate", "--operation", "assess", "--root", str(s), "--json"])
        check("w-memory-migrate-assess-ignores-lock", r.returncode == 0, out(r)[:200])
        (s / lock_name).unlink()

        for tag, phrase in (
            (schema_upgrade.NEW_LOCK_TAG, "schema new is running"),
            (schema_upgrade.MEMORY_RUNG_LOCK_TAG, "schema memory-rung is running"),
            (schema_upgrade.INIT_FORCE_LOCK_TAG, "init --force is running"),
            (schema_upgrade.MEMORY_MIGRATE_LOCK_TAG, "memory-migrate apply is running"),
            (schema_upgrade.RECALL_LOCK_TAG, "recall activate/disable is running"),
        ):
            (s / lock_name).write_text(tag + "\n")
            r = run(["schema", "upgrade", "--to", "2.0", "--apply", "--root", str(s), "--json"])
            check(f"w-upgrade-names-{tag}-holder", r.returncode == 2 and phrase in out(r), out(r)[:300])
            (s / lock_name).unlink()

        # W4: recall activate and recall disable rewrite the 2.0 contract file,
        # so they take the same lock; while it is held each exits 2 and the
        # contract file is byte-identical.
        recall_writers = {
            "recall-activate": lambda s: ["recall", "activate", "--profile", "atlas:scan", "--root", str(s), "--json"],
            "recall-disable": lambda s: ["recall", "disable", "--root", str(s), "--json"],
        }
        s = store("w-recall", "2.0")
        contract = s / "CONTRACT.json"
        for holder in (
            schema_upgrade.UPGRADE_LOCK_TAG,
            schema_upgrade.MEMORY_RUNG_LOCK_TAG,
            schema_upgrade.RECALL_LOCK_TAG,
        ):
            (s / lock_name).write_text(holder + "\n")
            before = contract.read_bytes()
            before_all = snapshot(s)
            for name, argv in recall_writers.items():
                r = run(argv(s))
                check(
                    f"w-{name}-refused-while-{holder}-holds-lock",
                    r.returncode == 2
                    and as_json(r).get("ok") is False
                    and "Remove the lock only if" in out(r)
                    and contract.read_bytes() == before
                    and snapshot(s) == before_all
                    and (s / lock_name).read_text() == holder + "\n",
                    out(r)[:300],
                )
            (s / lock_name).unlink()
        r = run(recall_writers["recall-activate"](s))
        recall = json.loads(contract.read_text()).get("recall") or {}
        check(
            "w-recall-activate-releases-on-success",
            r.returncode == 0
            and recall.get("enabled") is True
            and recall.get("preset") == "atlas:scan"
            and not (s / lock_name).exists(),
            out(r)[:300],
        )
        r = run(recall_writers["recall-disable"](s))
        recall = json.loads(contract.read_text()).get("recall") or {}
        check(
            "w-recall-disable-releases-on-success",
            r.returncode == 0 and recall.get("enabled") is False and not (s / lock_name).exists(),
            out(r)[:300],
        )
        before = contract.read_bytes()
        r = run(["recall", "activate", "--profile", "atlas:no-such-profile", "--root", str(s), "--json"])
        check(
            "w-recall-activate-releases-on-refusal",
            r.returncode == 2 and contract.read_bytes() == before and not (s / lock_name).exists(),
            out(r)[:300],
        )
        s = store("w-recall-v1")
        for name, argv in recall_writers.items():
            before = (s / "CONTRACT.json").read_bytes()
            r = run(argv(s))
            check(
                f"w-{name}-releases-on-1.0-refusal",
                r.returncode == 2
                and "SCHEMA 2.0 required" in out(r)
                and (s / "CONTRACT.json").read_bytes() == before
                and not (s / lock_name).exists(),
                out(r)[:300],
            )

        s = store("w-releases")
        r = run(writers["new"](s))
        check(
            "w-new-releases-on-success",
            r.returncode == 0
            and overlay_path(s, "atlas-notes").is_file()
            and receipt_path(s, "atlas-notes").is_file()
            and not (s / lock_name).exists(),
            out(r)[:300],
        )
        r = run(writers["new"](s))
        check("w-new-releases-on-refusal", r.returncode == 2 and not (s / lock_name).exists(), out(r)[:200])
        r = run(writers["memory-rung"](s))
        rung = json.loads((s / "CONTRACT.json").read_text()).get("memory", {}).get("rung")
        check(
            "w-memory-rung-releases-on-success",
            r.returncode == 0 and rung == "warn" and not (s / lock_name).exists(),
            out(r)[:300],
        )
        restampable(s)
        r = run(writers["memory-migrate-restamp"](s))
        stamp = json.loads((s / "CONTRACT.json").read_text()).get("atlas_release")
        check(
            "w-memory-migrate-releases-on-success",
            r.returncode == 0 and stamp == "0.13.0" and not (s / lock_name).exists(),
            out(r)[:300],
        )
        r = run(writers["init-force"](s))
        check("w-init-force-releases-on-success", r.returncode == 0 and not (s / lock_name).exists(), out(r)[:300])
        r = run(writers["new"](stores / "w-fresh"))
        check(
            "w-new-on-fresh-root-no-lock",
            r.returncode == 0 and overlay_path(stores / "w-fresh", "atlas-notes").is_file()
            and not (stores / "w-fresh" / lock_name).exists(),
            out(r)[:300],
        )

        # W2: a schema new interrupted mid-write keeps its lock and blocks the upgrade.
        s = store("w-new-interrupted")
        schema_cmd.write_receipt = receipt_fails
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                schema_cmd.run_new("atlas-notes", str(s))
            check("w-new-interrupted-raises", False, "schema new returned normally")
        except OSError as e:
            check("w-new-interrupted-raises", "simulated interruption" in str(e), str(e)[:200])
        finally:
            schema_cmd.write_receipt = original_receipt
        lock_text = (s / lock_name).read_text() if (s / lock_name).is_file() else ""
        check("w-new-interrupted-keeps-lock", lock_text.split()[:1] == [schema_upgrade.NEW_LOCK_TAG], lock_text[:100])
        r = run(["schema", "upgrade", "--to", "2.0", "--apply", "--root", str(s), "--json"])
        check("w-new-interrupted-blocks-upgrade", r.returncode == 2 and "schema new is running" in out(r), out(r)[:300])

        # W3: writers attempted while an upgrade holds the lock, after its
        # recheck and before any write, cannot write. In particular
        # `schema new atlas-compat-v1` cannot create the overlay the upgrade
        # then overwrites.
        s = store("w-race")
        restampable(s)
        original_preview = schema_upgrade.preview
        race_attempts: dict[str, int] = {}

        def recheck_then_writers(root: Path) -> dict:
            res = original_preview(root)
            if (root / lock_name).is_file() and not race_attempts:
                with contextlib.redirect_stdout(io.StringIO()):
                    race_attempts["new-compat"] = schema_cmd.run_new(schema_upgrade.COMPAT_ID, str(root))
                    race_attempts["memory-rung"] = schema_cmd.run_memory_rung("warn", str(root))
                for name in ("init-force", "memory-migrate-restamp"):
                    race_attempts[name] = run(writers[name](root)).returncode
            return res

        schema_upgrade.preview = recheck_then_writers
        try:
            schema_upgrade.apply(s)
            upgrade_err = ""
        except schema_upgrade.UpgradeError as e:
            upgrade_err = str(e)
        finally:
            schema_upgrade.preview = original_preview
        schema = json.loads((s / "CONTRACT.json").read_text())
        compat = json.loads(overlay_path(s, schema_upgrade.COMPAT_ID).read_text())
        compat_receipt = json.loads(receipt_path(s, schema_upgrade.COMPAT_ID).read_text())
        check(
            "w-race-writers-refused",
            race_attempts == {"new-compat": 2, "memory-rung": 2, "init-force": 2, "memory-migrate-restamp": 2},
            str(race_attempts),
        )
        check(
            "w-race-upgrade-owns-compat-overlay",
            not upgrade_err
            and schema.get("schema_version") == "2.0"
            and schema.get("atlas_release") == "0.13.0-beta.7"
            and "rung" not in (schema.get("memory") or {})
            and "bindings" in compat
            and "templates" not in compat
            and compat_receipt.get("written")
            == sorted([f"schema.d/{schema_upgrade.COMPAT_ID}.json", f"schema.d/{schema_upgrade.COMPAT_ID}.receipt.json"])
            and not (s / lock_name).exists(),
            upgrade_err[:300],
        )
        r = run(writers["new-compat"](s))
        check("w-race-new-compat-after-upgrade-exists", r.returncode == 2 and "already exists" in out(r), out(r)[:200])

        # D: locks are never reclaimed from contract state, and only their owner removes them.
        s = store("d-token")
        lk = schema_upgrade.acquire_store_lock(s, schema_upgrade.INSTALL_LOCK_TAG)
        parts = (s / lock_name).read_text().split()
        check("d-lock-has-token", parts[0] == schema_upgrade.INSTALL_LOCK_TAG and len(parts) == 2 and len(parts[1]) == 32)
        (s / lock_name).unlink()
        other = schema_upgrade.acquire_store_lock(s, schema_upgrade.UPGRADE_LOCK_TAG)
        check(
            "d-release-keeps-other-holder",
            schema_upgrade.release_store_lock(lk) is False and (s / lock_name).read_text() == other.content,
        )
        check("d-release-own-lock", schema_upgrade.release_store_lock(other) and not (s / lock_name).exists())

        # D2: a second upgrade that previewed 1.0 meets the first upgrade's live
        # lock after the contract is already 2.0. It must refuse, not reclaim.
        s = store("d-double-upgrade")
        original_preview = schema_upgrade.preview
        first: dict = {}

        def preview_then_first_upgrade_lands(root: Path) -> dict:
            res = original_preview(root)
            if not first:
                first["lock"] = schema_upgrade.acquire_store_lock(root, schema_upgrade.UPGRADE_LOCK_TAG)
                contract = root / "CONTRACT.json"
                body = json.loads(contract.read_text())
                contract.write_text(json.dumps(schema_upgrade._target_schema(body), indent=2) + "\n")
            return res

        schema_upgrade.preview = preview_then_first_upgrade_lands
        try:
            schema_upgrade.apply(s)
            check("d-second-upgrade-refused", False, "second apply succeeded")
        except schema_upgrade.UpgradeError as e:
            check(
                "d-second-upgrade-refused",
                "schema upgrade is running or was interrupted" in str(e)
                and (s / lock_name).read_text() == first["lock"].content,
                str(e)[:300],
            )
        finally:
            schema_upgrade.preview = original_preview
        r = install(v06, s)
        check("d-install-refused-while-first-upgrade-holds", r.returncode == 2 and lock_name in out(r), out(r)[:200])
        check("d-first-upgrade-releases", schema_upgrade.release_store_lock(first["lock"]) and not (s / lock_name).exists())

        # D3: a stale lock is never reclaimed, on 1.0 or 2.0 stores.
        for version in ("1.0", "2.0"):
            s = store(f"d-stale-{version}", version)
            (s / lock_name).write_text(schema_upgrade.UPGRADE_LOCK_TAG + "\n")
            r = install(v06, s)
            check(
                f"d-stale-{version}-install-refused",
                r.returncode == 2 and "Remove the lock only if" in out(r) and (s / lock_name).is_file(),
                out(r)[:200],
            )
        s = stores / "d-stale-1.0"
        r = run(["schema", "upgrade", "--to", "2.0", "--apply", "--root", str(s), "--json"])
        schema = json.loads((s / "CONTRACT.json").read_text())
        check(
            "d-stale-1.0-upgrade-refused",
            r.returncode == 2 and schema.get("schema_version") == "1.0" and (s / lock_name).is_file(),
            out(r)[:200],
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"FAILED: {len(failed)} — {', '.join(failed)}")
        return 1
    print("overlay extension: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
