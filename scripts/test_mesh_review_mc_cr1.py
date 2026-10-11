#!/usr/bin/env python3
"""Copilot review CR1 for federated recall (MC): engine preferences and ``--limit`` in mesh scope.

- A ``subpath`` row and a pathless row honour their row ``recall.engine`` and
  the project ``recall.engine`` (the member's mesh row is pinned for engine
  resolution, not only for its index location).
- ``--limit 0 --scope mesh`` means all hits for every engine, grep included,
  as :func:`mesh_recall.fuse` defines it; a negative ``--limit`` exits 2.

Linux-safe: no network, no git.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core import engine_preference, index_location, mesh_recall, mesh_scope  # noqa: E402
from test_mesh_recall import page, recall, schema, write  # noqa: E402

PLAIN = "github.com/acme/plain"
SUB = "github.com/acme/sub"
BARE = "github.com/acme/bare"
QUERY = "graph export"


def build(tmp: Path, *, row_engines: bool, project_engine: str | None = None) -> Path:
    """plain (a ``path`` row), sub (a ``subpath`` row) and bare (no ``path``), three hits each."""
    project = tmp / "proj"
    roots = {
        PLAIN: project / "atlas" / "plain",
        SUB: project / "atlas" / "mono" / "kb",
        BARE: project / ".atlas" / "github.com" / "acme" / "bare",
    }
    for sid, store in roots.items():
        schema(store)
        name = sid.rsplit("/", 1)[1]
        for n in range(3):
            write(store / "notes" / f"{name}-{n}.md", page(f"Graph export {name} {n}", "Graph export note", "Graph export body."))
    stores: list[dict] = [
        {"id": PLAIN, "path": "atlas/plain"},
        {"id": SUB, "path": "atlas/mono", "subpath": "kb"},
        {"id": BARE},
    ]
    if row_engines:
        for row in stores:
            row["recall"] = {"engine": "bm25"}
    doc: dict = {"version": 1, "stores": stores}
    if project_engine is not None:
        doc["recall"] = {"engine": project_engine}
    write(project / "atlas-mesh.json", json.dumps(doc, indent=2) + "\n")
    return project


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-cr1-"))
    try:
        # --- Blocker: row and project recall.engine for subpath and pathless rows ---------
        for label, kwargs, source in (
            ("row", {"row_engines": True}, "store"),
            ("project", {"row_engines": False, "project_engine": "bm25"}, "project"),
        ):
            case = tmp / label
            project = build(case, **kwargs)
            code, p, err = recall(project, "--scope", "mesh", query=QUERY)
            members = {m["atlas_id"]: m for m in p.get("members", [])}
            check(f"{label}-exit-0", code == 0, f"{code} {err} {p}")
            for sid in (PLAIN, SUB, BARE):
                m = members.get(sid, {})
                check(
                    f"{label}-engine-{sid.rsplit('/', 1)[1]}",
                    m.get("status") == "ok" and m.get("engine_requested") == "bm25",
                    str(m),
                )

            # The pinned row is what engine resolution sees, with its source.
            mesh = mesh_scope.discover(project)
            for member in mesh_scope.members(mesh):
                if member.atlas_id == PLAIN:
                    continue
                with mesh_recall._pinned(member, mesh):
                    pref = engine_preference.resolve_engine(member.root)
                check(
                    f"{label}-pinned-pref-{member.atlas_id.rsplit('/', 1)[1]}",
                    (pref.requested, pref.source, pref.store_id) == ("bm25", source, member.atlas_id),
                    str(pref),
                )
                check(
                    f"{label}-pin-released-{member.atlas_id.rsplit('/', 1)[1]}",
                    index_location.mesh_match(member.root) is None,
                )

        # --- Recommended: --limit 0 means all hits for every engine; negative exits 2 ------
        project = build(tmp / "limit", row_engines=False)
        code, p, err = recall(project, "--scope", "mesh", "--limit", "0", query=QUERY)
        members = {m["atlas_id"]: m for m in p.get("members", [])}
        check("limit-0-exit-0", code == 0, f"{code} {err} {p}")
        check(
            "limit-0-grep-members-answer",
            all(members.get(sid, {}).get("engine_used") == "grep" and members[sid]["hits"] == 3 for sid in (PLAIN, SUB, BARE)),
            str(members),
        )
        check("limit-0-all-hits", p.get("count") == 9 and len(p.get("hits", [])) == 9, str(p.get("count")))

        code_b, p_b, _ = recall(build(tmp / "limit-bm25", row_engines=True), "--scope", "mesh", "--limit", "0", query=QUERY)
        check("limit-0-bm25-all-hits", code_b == 0 and p_b.get("count") == 9, str(p_b.get("count")))

        code_n, p_n, _ = recall(project, "--scope", "mesh", "--limit", "-1", query=QUERY)
        check(
            "limit-negative-exit-2",
            code_n == 2 and p_n.get("ok") is False and p_n.get("error") == mesh_recall.LIMIT_ERROR,
            f"{code_n} {p_n}",
        )
        code_t, out_t, _ = recall(project, "--scope", "mesh", "--limit", "-5", query=QUERY, as_json=False)
        check("limit-negative-text-exit-2", code_t == 2 and mesh_recall.LIMIT_ERROR in out_t, f"{code_t} {out_t}")

        settings = mesh_recall.resolve_settings(project, "mesh")
        for bad in (-1, True):
            try:
                mesh_recall.federate(settings, QUERY, limit=bad)  # type: ignore[arg-type]
                check(f"federate-rejects-limit-{bad!r}", False)
            except mesh_recall.MeshRecallError:
                check(f"federate-rejects-limit-{bad!r}", True)

        seen: list[int] = []

        def spy(root, query, limit, engine_override, include_exits):  # noqa: ANN001
            seen.append(limit)
            return mesh_recall.MemberAnswer([{"path": f"{root.name}-{i}.md"} for i in range(4)], "all", "grep", "grep", None)

        payload, code_s = mesh_recall.federate(settings, QUERY, limit=0, search=spy)
        check("limit-0-spy-keeps-all", code_s == 0 and payload["count"] == 12, str(payload["count"]))
        check("limit-0-spy-asks-0-meaning-all", seen == [0, 0, 0], str(seen))
        seen.clear()
        mesh_recall.federate(settings, QUERY, limit=2, search=spy)
        check("limit-2-spy-overfetch", seen == [4, 4, 4], str(seen))

        # Store scope keeps its own --limit handling byte for byte (no new error).
        code_st, p_st, _ = recall(project / "atlas" / "plain", "--limit", "-1", query=QUERY)
        check("store-scope-negative-limit-unchanged", p_st.get("error") != mesh_recall.LIMIT_ERROR, f"{code_st} {p_st}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"\n{len(failed)} check(s) failed: {', '.join(failed)}")
        return 1
    print("\nAll mesh CR1 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
