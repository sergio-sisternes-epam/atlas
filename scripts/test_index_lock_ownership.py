#!/usr/bin/env python3
"""Index builder locks carry an owner token: only the owner releases, a
builder that lost its lock to a stale takeover publishes nothing, and racing
stale takeovers end with exactly one owner.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core import index_location, index_publish, recall_index  # noqa: E402
from atlas_cli.core.schema import load_schema  # noqa: E402
from test_recall_bm25 import PAGES, make_store  # noqa: E402


def force_stale(lock_path: Path) -> None:
    info = json.loads(lock_path.read_text(encoding="utf-8"))
    info["created_at"] = time.time() - index_publish.LOCK_STALE_SECONDS - 60
    lock_path.write_text(json.dumps(info) + "\n", encoding="utf-8")


def lock_owner(lock_path: Path) -> str | None:
    try:
        return json.loads(lock_path.read_text(encoding="utf-8")).get("owner")
    except (OSError, ValueError):
        return None


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="atlas-lock-owner-"))
    saved_env = dict(os.environ)
    try:
        # --- lock file content ----------------------------------------------------
        parent = tmp / "parent"
        a = index_publish.BuildLock(parent)
        check("owner-acquires", a.try_acquire())
        info = a.info() or {}
        check(
            "lock-content",
            info.get("owner") == a.owner
            and info.get("pid") == os.getpid()
            and info.get("host") == socket.gethostname()
            and isinstance(info.get("created_at"), float),
            str(info),
        )
        check("fresh-lock-blocks", not index_publish.BuildLock(parent).try_acquire())
        check("owner-release-removes", a.release() and not a.path.exists() and not a.lost)
        check("no-debris", sorted(p.name for p in parent.iterdir()) == [], str(list(parent.iterdir())))

        # --- stale takeover: A must not release B's lock ----------------------------
        a = index_publish.BuildLock(parent)
        a.try_acquire()
        force_stale(a.path)
        b = index_publish.BuildLock(parent)
        check("stale-takeover", b.try_acquire() and lock_owner(b.path) == b.owner)
        released = a.release()
        check("loser-release-refused", not released and a.lost, f"released={released} lost={a.lost}")
        check("winner-lock-kept", b.path.exists() and lock_owner(b.path) == b.owner)
        check("winner-releases", b.release() and not b.path.exists())

        # A dead pid on this host is stale even when young.
        parent.mkdir(exist_ok=True)
        (parent / index_publish.LOCK_NAME).write_text(
            json.dumps({"owner": "dead", "pid": 2**22 + 12345, "host": socket.gethostname(), "created_at": time.time()}),
            encoding="utf-8",
        )
        c = index_publish.BuildLock(parent)
        check("dead-pid-stale", c.try_acquire() and lock_owner(c.path) == c.owner)
        c.release()

        # locked_build reports lock_lost when the lock was taken over during the build.
        warnings: list[dict] = []
        holder: dict = {}

        def build_and_lose(lock: index_publish.BuildLock) -> str:
            force_stale(lock.path)
            other = index_publish.BuildLock(parent)
            other.try_acquire()
            holder["other"] = other
            return "built"

        result, built = index_publish.locked_build(parent, lambda: None, build_and_lose, warnings=warnings)
        other = holder["other"]
        check(
            "locked-build-lock-lost-warning",
            built and [w.get("code") for w in warnings] == ["lock_lost"] and lock_owner(other.path) == other.owner,
            str(warnings),
        )
        other.release()

        # --- concurrent stale takeovers: exactly one owner --------------------------
        for round_ in range(20):
            stale = index_publish.BuildLock(parent)
            stale.try_acquire()
            force_stale(stale.path)
            contenders = [index_publish.BuildLock(parent) for _ in range(8)]
            barrier = threading.Barrier(len(contenders))
            results: list[bool] = [False] * len(contenders)

            def race(i: int) -> None:
                barrier.wait()
                results[i] = contenders[i].try_acquire()

            threads = [threading.Thread(target=race, args=(i,)) for i in range(len(contenders))]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            winners = [c for c, ok in zip(contenders, results) if ok]
            owner = lock_owner(parent / index_publish.LOCK_NAME)
            ok = len(winners) == 1 and owner == winners[0].owner
            if not ok:
                check(f"concurrent-takeover-one-owner-{round_}", False, f"winners={len(winners)} owner={owner}")
                break
            winners[0].release()
            if stale.release():
                check(f"concurrent-stale-owner-cannot-release-{round_}", False)
                break
        else:
            check("concurrent-takeover-one-owner", True)
        check("concurrent-no-lock-left", not (parent / index_publish.LOCK_NAME).exists())

        # --- publish after losing the lock leaves the pointer alone -----------------
        os.environ["ATLAS_INDEX_ROOT"] = str(tmp / "project")
        index_location.clear_cache()
        store = make_store(tmp / "store", "1.0")
        schema, _ = load_schema(store)
        first = recall_index.ensure_fresh(store, schema)
        root = recall_index.index_root(store)
        pointer_before = (root / recall_index.CURRENT_NAME).read_text(encoding="utf-8")
        gens_before = sorted(p.name for p in (root / "generations").iterdir())
        check("baseline-built", first.rebuilt and len(gens_before) == 1, str(gens_before))
        page = store / sorted(PAGES)[0]
        page.write_text(page.read_text(encoding="utf-8") + "\nLock takeover marker.\n", encoding="utf-8")

        real_write = recall_index._write_sqlite
        taken: dict = {}

        def write_then_lose(path: Path, pages, digest):  # type: ignore[no-untyped-def]
            out = real_write(path, pages, digest)
            lock_path = root / index_publish.LOCK_NAME
            force_stale(lock_path)
            thief = index_publish.BuildLock(root)
            thief.try_acquire()
            taken["thief"] = thief
            return out

        recall_index._write_sqlite = write_then_lose
        try:
            try:
                recall_index.ensure_fresh(store, schema)
                raised = None
            except index_publish.IndexBusy as e:
                raised = e
        finally:
            recall_index._write_sqlite = real_write
        thief = taken.get("thief")
        check("lost-publish-raises-lock-lost", isinstance(raised, index_publish.LockLost) and "lock_lost" in str(raised), repr(raised))
        check(
            "lost-publish-pointer-unchanged",
            (root / recall_index.CURRENT_NAME).read_text(encoding="utf-8") == pointer_before,
        )
        gens_after = sorted(p.name for p in (root / "generations").iterdir())
        check("lost-publish-no-new-generation", gens_after == gens_before, f"{gens_before} -> {gens_after}")
        check("lost-publish-no-temp-left", not [p.name for p in root.iterdir() if p.name.startswith(index_publish.TMP_PREFIX)])
        check("lost-publish-thief-lock-kept", thief is not None and lock_owner(root / index_publish.LOCK_NAME) == thief.owner)
        if thief is not None:
            thief.release()
        again = recall_index.ensure_fresh(store, schema)
        check("next-build-publishes", again.rebuilt and (root / recall_index.CURRENT_NAME).read_text(encoding="utf-8") != pointer_before)
    finally:
        os.environ.clear()
        os.environ.update(saved_env)
        index_location.clear_cache()
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"\n{len(failed)} lock ownership check(s) failed: {', '.join(failed)}")
        return 1
    print("\nAll lock ownership checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
