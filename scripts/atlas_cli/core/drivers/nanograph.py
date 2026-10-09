"""nanograph driver: optional, external, macOS arm64 only.

Argv-only subprocess (never a shell), bounded timeouts, an allow-listed
environment with credentials denied (core/drivers/subprocess_env.py), an
absolute binary path fixed at detection time, and an Atlas-owned index under
``<project-root>/.atlas/indexes/nanograph/<atlas-id>/<generation>/`` (see
core/index_location.py). Builds run in a ``.tmp-<generation>`` sibling under
the shared builder lock, are published with an atomic rename and then an
atomic replace of ``current.json`` (see core/index_publish.py), so readers
never see a half-built generation. The final ownership check, the pointer
replace and pruning run under the lock's takeover guard, so a builder whose
lock was taken over publishes nothing (``lock_lost``). A ready generation in
the deprecated in-store ``.atlas-index/nanograph/`` is reused read-only for
0.14.x. Any failure raises DriverError so callers fall back to the built-in
driver.

Every nanograph process runs with its working directory set to a private,
empty ``atlas-nanograph-*`` temporary directory (mode 0700, removed
afterwards), because nanograph loads ``.env.nano`` and ``.env`` from its
working directory and ``init`` scaffolds ``nanograph.toml`` and ``.env.nano``
into an inferred project directory. ``init`` reads a schema copy from that
private directory; scaffolding ``init`` writes elsewhere is removed unless it
was already there, and a generation is scrubbed of those files before
``load`` and again before it is published.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Iterator

from .. import driver_overlay, graph, index_location, index_publish
from ..driver_overlay import BaseDriver, Detection, DriverError
from ..ignore_guard import ensure_indexes_ignored
from ..index_location import IndexLocationError
from .fts5 import query_tokens
from .subprocess_env import external_driver_env

MIN_VERSION = (1, 3, 0)
BIN_ENV = "ATLAS_NANOGRAPH_BIN"
VERSION_TIMEOUT = 10
BUILD_TIMEOUT = 120
RUN_TIMEOUT = 30
# graph neighbours: overall wall-clock deadline, in multiples of RUN_TIMEOUT.
NEIGHBOURS_DEADLINE_RUNS = 4
KEEP_GENERATIONS = 2
# Bumped when generated queries or edge type naming change, so older ready
# generations (for example with a capped bm25_text) are rebuilt, not reused.
# 3: the corpus digest now covers relative paths plus content (content-digest
# freshness), so generations recorded with the old digest rebuild once.
# 4: the corpus digest also covers the projection inputs (SCHEMA/CONTRACT,
# schema.d overlays, projection version).
INDEX_FORMAT = 4
QUERIES_NAME = "atlas.gq"
DB_NAME = "atlas.nano"
READY_NAME = "ready.json"
CURRENT_NAME = "current.json"
# nanograph loads these from its working directory at startup.
ENV_FILES = (".env.nano", ".env")
# ``nanograph init`` writes these into the directory it infers (if missing).
SCAFFOLD_FILES = ("nanograph.toml", ".env.nano")
# Never present in a published generation.
FORBIDDEN_FILES = frozenset({".env.nano", ".env", "nanograph.toml"})
PRIVATE_PREFIX = "atlas-nanograph-"
_PATH_OPTIONS = frozenset({"--db", "--schema", "--data", "--query"})
_GEN_NAME = re.compile(r"[0-9a-f]{16}(?:-[0-9a-f]{8})?")
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def query_ident(edge_type: str) -> str:
    return edge_type[:1].lower() + edge_type[1:]


def infer_init_project_dir(cwd: Path, db: str, schema: str) -> Path:
    """Where ``nanograph init`` writes ``nanograph.toml`` / ``.env.nano`` (nanograph 1.3.0).

    The lexical common ancestor of ``--db`` and ``--schema`` (each resolved
    against ``cwd`` when relative), or ``cwd`` when that ancestor is the
    filesystem root or there is none.
    """
    left = Path(db) if Path(db).is_absolute() else cwd / db
    right = Path(schema) if Path(schema).is_absolute() else cwd / schema
    shared: list[str] = []
    for a, b in zip(left.parts, right.parts):
        if a != b:
            break
        shared.append(a)
    if not shared:
        return cwd
    common = Path(*shared)
    return common if common.parent != common else cwd


def scrub_generation(root: Path) -> list[str]:
    """Remove every ``.env.nano``, ``.env`` and ``nanograph.toml`` under ``root`` (no symlinks followed)."""
    removed: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        for name in [*filenames, *dirnames]:
            if name not in FORBIDDEN_FILES:
                continue
            target = here / name
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
                dirnames.remove(name)
            else:
                target.unlink()
            removed.append(target.relative_to(root).as_posix())
    return removed


@contextlib.contextmanager
def private_cwd() -> Iterator[Path]:
    """A fresh, empty, 0700 working directory under the system temp dir, removed afterwards."""
    path = Path(tempfile.mkdtemp(prefix=PRIVATE_PREFIX))
    try:
        path.chmod(0o700)
        yield path.resolve()
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _check_private_cwd(cwd: Path) -> None:
    present = [name for name in ENV_FILES if os.path.lexists(cwd / name)]
    if present:
        raise DriverError(f"private working directory is not clean ({', '.join(present)})")


def generate_queries(page_edge_types: list[str]) -> str:
    # bm25_text has no row limit: Atlas applies type:/path:/exit-state
    # eligibility afterwards, so a cap here would drop eligible pages that rank
    # below it. Omitting ``limit`` uses only syntax the neighbour queries use.
    blocks = [
        "query bm25_text($q: String) {\n"
        "    match { $p: Page }\n"
        "    return { $p.slug, bm25($p.text, $q) as score }\n"
        "    order { bm25($p.text, $q) desc, $p.slug asc }\n"
        "}\n"
    ]
    for name in sorted(page_edge_types):
        ident = query_ident(name)
        for direction, pattern in (("out", f"$s {ident} $n"), ("in", f"$n {ident} $s")):
            blocks.append(
                f"query neighbours_{direction}_{ident}($seed: String) {{\n"
                "    match {\n"
                "        $s: Page { slug: $seed }\n"
                "        $n: Page\n"
                f"        {pattern}\n"
                "    }\n"
                "    return { $n.slug }\n"
                "    order { $n.slug asc }\n"
                "}\n"
            )
    return "\n".join(blocks)


def _row_value(row: Any, names: tuple[str, ...], index: int) -> Any:
    if isinstance(row, dict):
        for name in names:
            if name in row:
                return row[name]
        return None
    if isinstance(row, (list, tuple)) and len(row) > index:
        return row[index]
    return None


class NanographDriver(BaseDriver):
    id = "nanograph"
    capabilities = frozenset({"bm25_search", "graph_traversal"})
    platforms = (("darwin", "arm64"),)
    external = True
    index_type = "nanograph"

    def __init__(self) -> None:
        self.last_index: dict[str, Any] | None = None
        self.build_notes: list[str] = []
        self._detection: Detection | None = None

    # --- detection ------------------------------------------------------

    def find_binary(self) -> str | None:
        """Absolute, resolved path to the binary; later calls run with another cwd.

        A relative ``ATLAS_NANOGRAPH_BIN`` is resolved against the process cwd
        at detection time.
        """
        configured = os.environ.get(BIN_ENV, "").strip()
        if configured:
            path = Path(configured).expanduser()
            if not path.is_absolute():
                path = Path.cwd() / path
        else:
            found = shutil.which("nanograph")
            if not found:
                return None
            path = Path(found)
            if not path.is_absolute():
                path = Path.cwd() / path
        try:
            path = path.resolve()
        except (OSError, RuntimeError):
            return None
        return str(path) if path.is_file() and os.access(path, os.X_OK) else None

    def detect(self) -> Detection:
        self._detection = self._probe()
        return self._detection

    def _probe(self) -> Detection:
        plat = driver_overlay.current_platform()
        if not self.supports_platform(plat):
            return Detection(False, f"unavailable on {driver_overlay.platform_label(plat)}")
        binary = self.find_binary()
        if not binary:
            return Detection(False, "nanograph binary not found")
        try:
            with private_cwd() as cwd:
                _check_private_cwd(cwd)
                proc = subprocess.run(
                    [binary, "--version"],
                    cwd=str(cwd),
                    capture_output=True,
                    text=True,
                    timeout=VERSION_TIMEOUT,
                    env=external_driver_env(),
                    shell=False,
                )
            match = _VERSION.search(f"{proc.stdout}\n{proc.stderr}") if proc.returncode == 0 else None
        except (OSError, subprocess.SubprocessError, DriverError):
            match = None
        if match is None:
            return Detection(False, "nanograph version unreadable", None, binary)
        version = match.group(0)
        if tuple(int(x) for x in match.groups()) < MIN_VERSION:
            minimum = ".".join(str(x) for x in MIN_VERSION)
            return Detection(False, f"nanograph version {version} below minimum {minimum}", version, binary)
        return Detection(True, "ok", version, binary)

    def _ready(self) -> Detection:
        if self._detection is None:
            self._detection = self.detect()
        if not self._detection.available:
            raise DriverError(self._detection.reason)
        return self._detection

    # --- subprocess -----------------------------------------------------

    def _exec(self, args: list[str], timeout: int, cwd: Path | None = None) -> str:
        """Run nanograph in ``cwd`` (a private directory from :func:`private_cwd`; a fresh one when ``None``)."""
        if cwd is None:
            with private_cwd() as fresh:
                return self._exec(args, timeout, fresh)
        det = self._ready()
        for i, arg in enumerate(args[:-1]):
            if arg in _PATH_OPTIONS and not Path(args[i + 1]).is_absolute():
                raise DriverError(f"{args[0]} {arg} path must be absolute")
        _check_private_cwd(cwd)
        argv = [str(det.binary), *args]
        try:
            proc = subprocess.run(
                argv,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=external_driver_env(),
                shell=False,
            )
        except subprocess.TimeoutExpired as e:
            raise DriverError(f"{args[0]} timed out after {timeout}s") from e
        except OSError as e:
            raise DriverError(f"{args[0]} could not start ({e.strerror or e})") from e
        if proc.returncode != 0:
            raise DriverError(f"{args[0]} failed (exit {proc.returncode})")
        return proc.stdout

    def _run_query(
        self, gen_dir: Path, name: str, params: dict[str, str], timeout: int = RUN_TIMEOUT
    ) -> list[Any]:
        args = [
            "run",
            "--db", os.path.abspath(gen_dir / DB_NAME),
            "--query", os.path.abspath(gen_dir / QUERIES_NAME),
            "--name", name,
            "--format", "json",
        ]
        for key, value in params.items():
            args += ["--param", f"{key}={value}"]
        out = self._exec(args, timeout)
        try:
            data = json.loads(out)
        except json.JSONDecodeError as e:
            raise DriverError(f"run {name} returned non-JSON output") from e
        rows = data.get("rows") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise DriverError(f"run {name} returned no rows array")
        return rows

    # --- index ----------------------------------------------------------

    def build(self, export_dir: Path, index_dir: Path) -> dict[str, Any]:
        det = self._ready()
        try:
            receipt = json.loads((export_dir / "export-receipt.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise DriverError("export receipt unreadable") from e
        schema_text = (export_dir / "schema.pg").read_text(encoding="utf-8")
        page_types = sorted(
            m.group(1) for m in re.finditer(r"^edge (\w+): Page -> Page$", schema_text, re.M)
        )
        (index_dir / QUERIES_NAME).write_text(generate_queries(page_types), encoding="utf-8")
        db = os.path.abspath(index_dir / DB_NAME)
        with private_cwd() as cwd:
            # init reads a private schema copy, so the db/schema common ancestor is never the generation.
            schema = cwd / "schema.pg"
            shutil.copyfile(export_dir / "schema.pg", schema)
            _check_private_cwd(cwd)
            project = infer_init_project_dir(cwd, db, str(schema))
            existed = {name: os.path.lexists(project / name) for name in SCAFFOLD_FILES}
            try:
                self._exec(["init", "--db", db, "--schema", str(schema)], BUILD_TIMEOUT, cwd)
            finally:
                for name, was_there in existed.items():
                    if not was_there and project != cwd:
                        with contextlib.suppress(FileNotFoundError):
                            (project / name).unlink()
            kept = [name for name, was_there in existed.items() if was_there and project != cwd]
            if kept:
                self.build_notes.append(
                    f"nanograph init inferred {project} as its project directory and left the existing "
                    f"{', '.join(kept)} there untouched"
                )
        scrub_generation(index_dir)
        self._exec(
            ["load", "--db", db, "--data", os.path.abspath(export_dir / "seed.jsonl"), "--mode", "overwrite"],
            BUILD_TIMEOUT,
        )
        ready = {
            "format": INDEX_FORMAT,
            "version": det.version,
            "corpus_digest": receipt.get("corpus_digest"),
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        tmp = index_dir / (READY_NAME + ".tmp")
        tmp.write_text(json.dumps(ready, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, index_dir / READY_NAME)
        return {"built": True, **ready}

    @staticmethod
    def index_base(store: Path) -> Path:
        try:
            return index_location.index_dir(store, "nanograph")
        except IndexLocationError as e:
            raise DriverError(f"index path rejected: {e}") from e

    @staticmethod
    def legacy_base(store: Path) -> Path:
        return index_location.legacy_dir(store, "nanograph")

    def _guard(self, store: Path, path: Path) -> None:
        try:
            index_location.reject_symlink_escape(index_location.indexes_base(store), path)
        except IndexLocationError as e:
            raise DriverError(f"index path rejected: {e}") from e

    @staticmethod
    def _read_ready(gen_dir: Path) -> dict[str, Any] | None:
        try:
            data = json.loads((gen_dir / READY_NAME).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _reusable(self, gen_dir: Path, digest: str, version: str | None) -> bool:
        ready = self._read_ready(gen_dir)
        return bool(
            ready
            and ready.get("corpus_digest") == digest
            and ready.get("version") == version
            and ready.get("format") == INDEX_FORMAT
            and (gen_dir / DB_NAME).exists()
            and (gen_dir / QUERIES_NAME).is_file()
        )

    def _current(self, base: Path, digest: str, version: str | None) -> Path | None:
        """Resolve ``current.json`` once; fall back to a pre-pointer ``<digest16>`` generation."""
        try:
            pointer = json.loads((base / CURRENT_NAME).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pointer = None
        names: list[str] = []
        if isinstance(pointer, dict) and isinstance(pointer.get("generation"), str):
            names.append(pointer["generation"])
        names.append(digest[:16])
        for name in names:
            if not _GEN_NAME.fullmatch(name):
                continue
            gen_dir = base / name
            if gen_dir.is_symlink():
                continue
            if self._reusable(gen_dir, digest, version):
                return gen_dir
        return None

    def _legacy_generation(self, store: Path, digest: str, version: str | None) -> Path | None:
        """A ready generation in the deprecated in-store location, used read-only."""
        base = self.legacy_base(store)
        gen_dir = base / digest[:16]
        for path in (store / index_location.LEGACY_DIR, base, gen_dir):
            if path.is_symlink():
                return None
        try:
            gen_dir.resolve().relative_to(store.resolve())
        except ValueError:
            return None
        return gen_dir if self._reusable(gen_dir, digest, version) else None

    def index_state(self, store: Path, digest: str) -> dict[str, Any]:
        """Read-only freshness of the new-location index for ``digest`` (no build)."""
        det = self.detect()
        if not det.available:
            return {"fresh": False, "reason": det.reason}
        base = self.index_base(store)
        gen = self._current(base, digest, det.version)
        if gen is not None:
            return {"fresh": True, "generation": gen.name}
        legacy = self._legacy_generation(store, digest, det.version)
        if legacy is not None:
            return {"fresh": True, "generation": legacy.name, "legacy": True}
        return {"fresh": False, "reason": "missing or stale"}

    def ensure_index(
        self,
        store: Path,
        source: dict[str, Any],
        wait: float | None = None,
        allow_legacy: bool = True,
        force: bool = False,
    ) -> Path:
        det = self._ready()
        digest = str(source.get("corpus_digest") or "")
        if not re.fullmatch(r"[0-9a-f]{16,}", digest):
            raise DriverError("corpus digest unavailable")
        base = self.index_base(store)
        self._guard(store, base / digest[:16])
        where = index_location.describe(store, "nanograph")
        gen_dir = None if force else self._current(base, digest, det.version)
        if gen_dir is None and allow_legacy and not force:
            legacy = self._legacy_generation(store, digest, det.version)
            if legacy is not None:
                self.last_index = {
                    "generation": legacy.name,
                    "path": legacy.relative_to(store).as_posix(),
                    "reused": True,
                    "legacy": True,
                    "warning": index_location.legacy_warning(store, "nanograph"),
                    **where,
                }
                return legacy

        lock_warnings: list[dict[str, Any]] = []
        self.build_notes = []

        def build(lock: index_publish.BuildLock) -> Path:
            guarded = ensure_indexes_ignored(store)
            if guarded and guarded.get("level") == "warning":
                lock_warnings.append(guarded)
            name = digest[:16]
            if (base / name).exists():
                name = f"{name}-{index_publish.new_name()}"
            tmp_dir = base / f"{index_publish.TMP_PREFIX}{name}"
            dest = base / name
            self._guard(store, tmp_dir)
            self._guard(store, dest)
            tmp_dir.mkdir(parents=True)
            try:
                graph.export_nanograph(source, tmp_dir / "export")
                self.build(tmp_dir / "export", tmp_dir)
                scrub_generation(tmp_dir)
                index_publish.ensure_owned(lock)
                index_publish.publish_dir(tmp_dir, dest)
            except BaseException:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                raise
            ready = self._read_ready(dest) or {}
            pointer = {
                "generation": name,
                "corpus_digest": digest,
                "version": det.version,
                "built_at": ready.get("built_at"),
            }
            # Final ownership check, pointer replace and prune under the takeover guard.
            try:
                with index_publish.critical_section(lock):
                    try:
                        before = json.loads((base / CURRENT_NAME).read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        before = {}
                    previous = before.get("generation") if isinstance(before, dict) else None
                    index_publish.write_json_atomic(base / CURRENT_NAME, pointer)
                    retired = self._prune(base, dest, previous if isinstance(previous, str) else None)
            except index_publish.LockLost:
                shutil.rmtree(dest, ignore_errors=True)
                raise
            index_publish.discard(retired)
            return dest

        reused = gen_dir is not None
        if gen_dir is None:
            try:
                gen_dir, built = index_publish.locked_build(
                    base,
                    lambda: None if force else self._current(base, digest, det.version),
                    build,
                    wait=wait,
                    warnings=lock_warnings,
                )
            except index_publish.IndexBusy as e:
                raise DriverError(str(e)) from e
            except OSError as e:
                raise DriverError(f"index build failed ({e.strerror or e})") from e
            reused = not built
        self.last_index = {
            "generation": gen_dir.name,
            "path": index_location.project_relative(store, gen_dir),
            "reused": reused,
            **where,
        }
        if lock_warnings:
            self.last_index["warnings"] = lock_warnings
        if self.build_notes:
            self.last_index["driver_note"] = "; ".join(self.build_notes)
        return gen_dir

    def _prune(self, base: Path, keep: Path, previous: str | None = None) -> list[Path]:
        """Retire all but ``keep`` and one other: the previous pointer's generation if present, else the newest.

        Old generations are only renamed to ``.tmp-*``; the caller removes the returned paths.
        """
        others: list[tuple[int, str, float, Path]] = []
        for child in base.iterdir():
            if child == keep or child.is_symlink() or not child.is_dir():
                continue
            if child.name.startswith(index_publish.TMP_PREFIX):
                continue
            ready = self._read_ready(child) or {}
            others.append((1 if child.name == previous else 0, str(ready.get("built_at") or ""), child.stat().st_mtime, child))
        others.sort(reverse=True)
        return index_publish.retire([old for *_, old in others[KEEP_GENERATIONS - 1 :]], base)

    # --- capabilities -----------------------------------------------------

    def _source(self, store: Path, source: dict[str, Any] | None) -> dict[str, Any]:
        if source is not None:
            return source
        try:
            return graph.load_source(store)
        except graph.GraphError as e:
            raise DriverError(str(e)) from e

    def bm25_search(
        self, store: Path, query: str, limit: int, *, source: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Higher-better hits for every page with a positive score (limit 0 = all)."""
        text = " ".join(query_tokens(query))
        if not text:
            return []
        source = self._source(store, source)
        gen_dir = self.ensure_index(store, source)
        by_id = {p.page_id: p for p in source["pages"]}
        hits: list[dict[str, Any]] = []
        for row in self._run_query(gen_dir, "bm25_text", {"q": text}):
            slug = _row_value(row, ("slug", "$p.slug", "p.slug"), 0)
            score = _row_value(row, ("score",), 1)
            if not isinstance(score, (int, float)) or isinstance(score, bool) or score <= 0:
                continue
            page = by_id.get(str(slug))
            if page is None:
                continue
            hits.append(
                {
                    "path": page.page_id,
                    "score": float(score),
                    "title": page.title or Path(page.path).stem,
                    "type": str(page.meta.get("type") or ""),
                    "driver": self.id,
                    "score_orientation": "higher_better",
                }
            )
        hits.sort(key=lambda h: (-h["score"], h["path"]))
        return hits[:limit] if limit else hits

    def neighbours(
        self,
        store: Path,
        seed: str,
        kinds: list[str] | tuple[str, ...] = (),
        direction: str = "both",
        hops: int = 1,
        *,
        source: dict[str, Any] | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        source = self._source(store, source)
        pages = source["pages"]
        edges = graph.all_edges(pages)
        try:
            type_map = graph.source_edge_type_map(source, edges)
        except graph.GraphError as e:
            raise DriverError(str(e)) from e
        # edge type -> Atlas kind, for kinds with at least one resolved page edge.
        kind_of = {
            type_map[(e["kind"], False)]: e["kind"]
            for e in edges
            if e["resolved"] and not e.get("external")
        }
        wanted = frozenset(kinds or ())
        pairs = sorted((t, k) for t, k in kind_of.items() if not wanted or k in wanted)
        ways = [w for w in ("out", "in") if direction in (w, "both")]
        max_nodes = options.get("max_nodes", graph.DEFAULT_MAX_NODES)
        max_edges = options.get("max_edges", graph.DEFAULT_MAX_EDGES)
        # Work budget: every expanded page is the seed or the far end of an
        # accepted edge, so at most 1 + max_edges pages are ever expanded.
        expandable = len(pages) if max_edges is None else min(len(pages), 1 + max(0, max_edges))
        budget: dict[str, Any] = {
            "calls": len(pairs) * len(ways) * expandable,
            "deadline": time.monotonic() + RUN_TIMEOUT * NEIGHBOURS_DEADLINE_RUNS,
            "stopped": None,
            "calls_made": 0,
        }
        progress: dict[str, Any] = {}
        state: dict[str, Any] = {"gen_dir": None}
        cache: dict[tuple[str, str, str], list[str]] = {}

        def step(page_id: str, way: str, edge_type: str, timeout: int) -> list[str]:
            key = (page_id, way, edge_type)
            if key not in cache:
                if state["gen_dir"] is None:
                    state["gen_dir"] = self.ensure_index(store, source)
                budget["calls"] -= 1
                budget["calls_made"] += 1
                rows = self._run_query(
                    state["gen_dir"],
                    f"neighbours_{way}_{query_ident(edge_type)}",
                    {"seed": page_id},
                    timeout=timeout,
                )
                found = (_row_value(r, ("slug", "$n.slug", "n.slug"), 0) for r in rows)
                cache[key] = sorted({str(s) for s in found if isinstance(s, str) and s})
            return cache[key]

        def over_cap(page_id: str, found: list[tuple[str, str, str]]) -> bool:
            """True once ``found`` is certain to push the traversal past a cap (it truncates anyway)."""
            seen, accepts = progress["seen"], progress["accepts"]
            new_nodes: set[str] = set()
            new_edges: set[tuple[str, str, str]] = set()
            for other, kind, step_dir in found:
                visible, counts = accepts(other)
                if not visible:
                    continue
                key = (page_id, other, kind) if step_dir == "outgoing" else (other, page_id, kind)
                if key not in progress["edge_keys"]:
                    new_edges.add(key)
                if counts and other not in seen:
                    new_nodes.add(other)
            return (max_nodes is not None and len(new_nodes) > max_nodes - len(progress["nodes"])) or (
                max_edges is not None and len(new_edges) > max_edges - len(progress["edges"])
            )

        def adjacency(page_id: str, way: str, wanted: frozenset[str]) -> list[tuple[str, str, str]]:
            if budget["stopped"]:
                return []
            if (max_nodes is not None and len(progress["nodes"]) >= max_nodes) or (
                max_edges is not None and len(progress["edges"]) >= max_edges
            ):
                budget["stopped"] = "cap"
                return []
            out: list[tuple[str, str, str]] = []
            for w in ways:
                for edge_type, kind in pairs:
                    timeout = RUN_TIMEOUT
                    if (page_id, w, edge_type) not in cache:
                        if over_cap(page_id, out):
                            budget["stopped"] = "cap"
                            return out
                        left = budget["deadline"] - time.monotonic()
                        if budget["calls"] <= 0 or left < 1:
                            budget["stopped"] = "budget"
                            return out
                        timeout = min(RUN_TIMEOUT, int(left))
                    found = step(page_id, w, edge_type, timeout)
                    out += [(o, kind, "outgoing" if w == "out" else "incoming") for o in found]
            return out

        result = graph.query_neighbours(
            pages,
            seed,
            kinds=kinds,
            direction=direction,
            hops=hops,
            adjacency=adjacency,
            progress=progress,
            **options,
        )
        if state["gen_dir"] is None:
            self.ensure_index(store, source)
        result = {**result, "driver": self.id}
        if budget["stopped"] == "cap":
            result["truncated"] = True
            result["driver_note"] = "nanograph traversal stopped at the --max-nodes/--max-edges cap"
        elif budget["stopped"] == "budget":
            result["truncated"] = True
            result["driver_note"] = (
                "nanograph traversal stopped at its work budget "
                f"({budget['calls_made']} calls, {RUN_TIMEOUT * NEIGHBOURS_DEADLINE_RUNS}s deadline)"
            )
        return result
