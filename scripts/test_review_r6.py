#!/usr/bin/env python3
"""Review R6 regressions.

1. ``graph neighbours --driver nanograph`` budgets its work, not only its
   output: it queries only relation kinds present in the projection, stops
   issuing nanograph ``run`` calls once ``--max-nodes`` / ``--max-edges`` is
   certain to be hit (``truncated: true`` plus a ``driver_note``), and matches
   native-graph exactly when no cap is hit (test-only harness platform
   darwin-arm64, fake nanograph).
2. ``OwnedLock.release`` re-checks ownership and moves the lock under the same
   token-owned ``<name>.takeover`` guard as stale takeover, so a takeover can no
   longer slip between the release's check and its rename (which used to move
   the new owner's lock aside and make its ``still_owned()`` report lost).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
TEST_CLI = ROOT / "scripts" / "testing" / "atlas_test_cli.py"
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core import index_publish  # noqa: E402
from atlas_cli.core.owned_lock import OwnedLock  # noqa: E402
from test_drivers import make_store, read_log, write_fake  # noqa: E402
from test_graph import SCHEMA_V1  # noqa: E402

VOCAB = [f"kind{i:02d}" for i in range(30)]
SCHEMA_WIDE = {**SCHEMA_V1, "relations": {"recommended_kinds": VOCAB}}


def page(title: str, edges: list[tuple[str, str]] = ()) -> str:
    rel = "".join(f"  - path: {to}\n    kind: {kind}\n" for to, kind in edges)
    head = f"---\ntype: document\ntitle: {title}\ncreated: 2026-10-09\n"
    return head + (f"relates_to:\n{rel}" if rel else "") + f"---\n\n{title} body.\n"


# Only kind00 and kind01 occur, out of a 30-kind vocabulary.
PAGES = {
    "x.md": page("X", [("a.md", "kind00"), ("b.md", "kind01")]),
    "a.md": page("A", [("c.md", "kind00")]),
    "b.md": page("B"),
    "c.md": page("C", [("x.md", "kind01")]),
    "hub.md": page("Hub", [(f"spoke{i}.md", "kind00") for i in range(10)] + [("a.md", "kind01")]),
    **{f"spoke{i}.md": page(f"Spoke {i}") for i in range(10)},
}


def force_stale(path: Path) -> None:
    info = json.loads(path.read_text(encoding="utf-8"))
    info["created_at"] = time.time() - 3600
    path.write_text(json.dumps(info) + "\n", encoding="utf-8")


def owner_of(path: Path) -> str | None:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("owner")
    except (OSError, ValueError):
        return None


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    def attempt(name: str, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - a crash is a failure of this section
            check(name, False, f"{type(e).__name__}: {e}")

    tmp = Path(tempfile.mkdtemp(prefix="atlas-r6-")).resolve()
    try:
        # === 1. nanograph neighbours work budget ===============================
        def neighbours_budget() -> None:
            fake = write_fake(tmp / "nanograph")
            store = make_store(tmp / "project" / "kb", PAGES)
            (store / "SCHEMA.json").write_text(json.dumps(SCHEMA_WIDE, indent=2) + "\n", encoding="utf-8")
            log = tmp / "nanograph.log"
            env = {
                **{k: v for k, v in os.environ.items() if not k.startswith(("ATLAS_", "FAKE_NANOGRAPH_"))},
                "ATLAS_TEST_PLATFORM": "darwin-arm64",
                "ATLAS_NANOGRAPH_BIN": str(fake),
                "FAKE_NANOGRAPH_LOG": str(log),
            }

            def cli(*args: str) -> tuple[int, dict[str, Any], str, int]:
                log.unlink(missing_ok=True)
                proc = subprocess.run(
                    [sys.executable, str(TEST_CLI), "graph", "neighbours", *args, "--root", str(store), "--json"],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    env=env,
                )
                try:
                    data = json.loads(proc.stdout)
                except json.JSONDecodeError:
                    data = {}
                runs = sum(1 for e in read_log(log) if e["argv"][:1] == ["run"])
                return proc.returncode, data, proc.stdout + proc.stderr, runs

            # Warm the index so later counts are queries only.
            code, p, out, _ = cli("b.md", "--driver", "nanograph")
            check("budget-warm", code == 0 and p.get("driver_used") == "nanograph", out[-400:])

            code, p, out, runs = cli("x.md", "--driver", "nanograph", "--max-nodes", "1", "--max-edges", "1")
            check("budget-capped-exit-0", code == 0 and p.get("driver_used") == "nanograph", out[-400:])
            check("budget-capped-at-most-2-runs", runs <= 2, f"runs={runs}")
            check("budget-capped-truncated", p.get("truncated") is True, out[-400:])
            check("budget-capped-note", "stopped at the --max-nodes/--max-edges cap" in str(p.get("driver_note")), out[-400:])
            check("budget-capped-within-caps", len(p.get("nodes") or []) <= 1 and len(p.get("edges") or []) <= 1, out[-400:])

            strip = lambda d: {k: v for k, v in d.items() if k != "driver_used"}  # noqa: E731
            for q in (("x.md",), ("hub.md",), ("x.md", "--hops", "3"), ("a.md", "--direction", "in", "--hops", "2"), ("hub.md", "--kind", "kind01")):
                code_n, native, _, _ = cli(*q)
                code_g, nano, out_g, _ = cli(*q, "--driver", "nanograph")
                label = " ".join(q)
                check(
                    f"budget-uncapped-parity-{label}",
                    code_n == code_g == 0
                    and nano.get("driver_used") == "nanograph"
                    and "driver_note" not in nano
                    and strip(native) == strip(nano),
                    f"{native} != {nano}",
                )

            _, full, _, runs_full = cli("hub.md", "--driver", "nanograph")
            code, capped, out, runs_capped = cli("hub.md", "--driver", "nanograph", "--max-nodes", "2")
            check("budget-hub-fewer-runs", runs_capped < runs_full, f"capped={runs_capped} full={runs_full}")
            check("budget-hub-only-present-kinds", runs_full == 4, f"runs={runs_full} (2 present kinds x 2 directions)")
            check(
                "budget-hub-capped-result",
                code == 0 and capped.get("truncated") is True and len(capped.get("nodes") or []) == 2,
                out[-400:],
            )
            code_n, native_capped, _, _ = cli("hub.md", "--max-nodes", "2")
            full_paths = {n["path"] for n in full.get("nodes") or []}
            check(
                "budget-hub-capped-subset",
                {n["path"] for n in capped.get("nodes") or []} <= full_paths and native_capped.get("truncated") is True,
                f"{capped.get('nodes')} not within {sorted(full_paths)}",
            )

        attempt("neighbours-budget", neighbours_budget)

        # === 2. guard-serialised release ======================================
        def release_interleaving() -> None:
            parent = tmp / "race"
            a = index_publish.BuildLock(parent)
            check("race-a-acquires", a.try_acquire())
            force_stale(a.path)
            b = index_publish.BuildLock(parent)
            seen: dict[str, Any] = {}

            def b_takes_over() -> None:
                seen["b_got"] = b.try_acquire()

            def a_info() -> dict[str, Any] | None:
                data = OwnedLock.info(a)
                if not a.held and "thread" not in seen:
                    # A is inside release(), between its ownership check and its rename: B takes over now.
                    seen["thread"] = threading.Thread(target=b_takes_over)
                    seen["thread"].start()
                    seen["thread"].join(0.5)
                return data

            def a_read(path: Path) -> dict[str, Any] | None:
                if ".release-" in path.name:
                    # A's lock (or, before the fix, B's) is renamed aside right now.
                    seen["b_owned_mid"] = b.still_owned()
                    seen["b_lost_mid"] = b.lost
                return OwnedLock._read(path)

            a.info = a_info  # type: ignore[method-assign]
            a._read = a_read  # type: ignore[method-assign]
            released = a.release()
            if "thread" in seen:
                seen["thread"].join(15)
            check("race-hook-fired", "thread" in seen and "b_lost_mid" in seen, str(seen))
            check("race-b-never-lost", not seen.get("b_lost_mid") and not b.lost, str(seen))
            check("race-b-owns", seen.get("b_got") is True and b.still_owned() and owner_of(b.path) == b.owner, str(seen))
            try:
                index_publish.ensure_owned(b)
                published = True
            except index_publish.LockLost:
                published = False
            check("race-b-publishes", published)
            check("race-a-released-own-or-lost", released or a.lost, f"released={released} lost={a.lost}")
            check("race-b-releases", b.release() and not b.lost)
            check("race-no-debris", sorted(p.name for p in parent.iterdir()) == [], str(sorted(p.name for p in parent.iterdir())))

        attempt("release-interleaving", release_interleaving)

        def guard_staleness() -> None:
            parent = tmp / "guard"
            a = index_publish.BuildLock(parent)
            a.try_acquire()
            force_stale(a.path)
            guard = parent / f"{a.name}.takeover"
            guard.write_text(json.dumps({"owner": "abandoned", "pid": 1, "created_at": time.time() - 3600}) + "\n", encoding="utf-8")
            old = time.time() - 3600
            os.utime(guard, (old, old))
            b = index_publish.BuildLock(parent)
            check("guard-abandoned-taken-over", b.try_acquire() and owner_of(b.path) == b.owner)
            check("guard-abandoned-removed", not [p.name for p in parent.iterdir() if ".takeover" in p.name], str(list(parent.iterdir())))
            check("guard-old-holder-lost", not a.release() and a.lost)

            # A live (young) guard blocks a takeover for a bounded time and is left alone.
            force_stale(b.path)
            guard.write_text(json.dumps({"owner": "busy", "pid": os.getpid(), "created_at": time.time()}) + "\n", encoding="utf-8")
            c = index_publish.BuildLock(parent)
            started = time.monotonic()
            got = c.try_acquire()
            check("guard-busy-blocks-takeover", not got and owner_of(b.path) == b.owner and time.monotonic() - started < 10)
            check("guard-busy-kept", owner_of(guard) == "busy")

            # Only the guard's creator removes it.
            guard.unlink()
            token = b._acquire_guard(1.0)
            guard.write_text(json.dumps({"owner": "someone-else", "created_at": time.time()}) + "\n", encoding="utf-8")
            b._release_guard(token)
            check("guard-only-creator-removes", owner_of(guard) == "someone-else")
            guard.unlink()

            # Release waits for a guard only until the guard's own short timeout.
            short = OwnedLock(tmp / "short", "x.lock", 600, takeover_stale_seconds=0.3)
            short.try_acquire()
            sguard = short.parent / "x.lock.takeover"
            sguard.write_text(json.dumps({"owner": "stuck", "created_at": time.time()}) + "\n", encoding="utf-8")
            check("guard-release-breaks-stale-guard", short.release() and not short.path.exists() and not sguard.exists())
            b.release()

        attempt("guard-staleness", guard_staleness)

        def stress() -> None:
            problems: list[str] = []
            for i in range(50):
                parent = tmp / "stress" / str(i)
                a = OwnedLock(parent, "x.lock", 60)
                a.try_acquire()
                force_stale(a.path)
                contenders = [OwnedLock(parent, "x.lock", 60) for _ in range(3)]
                barrier = threading.Barrier(len(contenders) + 1)
                lost_while_held: list[str] = []
                outcome: dict[str, Any] = {}

                def releaser() -> None:
                    barrier.wait()
                    outcome["a"] = a.release()

                def contender(lock: OwnedLock) -> None:
                    barrier.wait()
                    if lock.try_acquire():
                        for _ in range(20):
                            if not lock.still_owned():
                                lost_while_held.append(lock.owner)
                                break

                threads = [threading.Thread(target=releaser)] + [threading.Thread(target=contender, args=(c,)) for c in contenders]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
                winners = [c for c in contenders if c.held]
                owner = owner_of(parent / "x.lock")
                if len(winners) != 1 or owner != winners[0].owner:
                    problems.append(f"{i}: winners={len(winners)} owner={owner}")
                if lost_while_held or any(c.lost for c in contenders):
                    problems.append(f"{i}: legitimate owner lost")
                if not (outcome.get("a") or a.lost):
                    problems.append(f"{i}: stale holder neither released nor lost")
                for w in winners:
                    w.release()
                left = sorted(p.name for p in parent.iterdir())
                if left:
                    problems.append(f"{i}: debris {left}")
                if problems:
                    break
            check("stress-one-owner-never-lost", not problems, "; ".join(problems[:3]))

        attempt("stress", stress)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"\n{len(failed)} review R6 check(s) failed: {', '.join(failed)}")
        return 1
    print("\nAll review R6 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
