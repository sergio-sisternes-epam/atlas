"""nanograph driver: optional, external, macOS arm64 only.

Argv-only subprocess (never a shell), bounded timeouts, embedding credentials
stripped from the environment, and an Atlas-owned index under
``<project-root>/.atlas/indexes/nanograph/<atlas-id>/<generation>/`` (see
core/index_location.py). Builds run in a ``.tmp-<generation>`` sibling under
the shared builder lock, are published with an atomic rename and then an
atomic replace of ``current.json`` (see core/index_publish.py), so readers
never see a half-built generation. A ready generation in the deprecated in-store
``.atlas-index/nanograph/`` is reused read-only for 0.14.x. Any failure raises
DriverError so callers fall back to the built-in driver.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .. import driver_overlay, graph, index_location, index_publish
from ..driver_overlay import BaseDriver, Detection, DriverError
from ..ignore_guard import ensure_indexes_ignored
from ..index_location import IndexLocationError
from .fts5 import query_tokens

MIN_VERSION = (1, 3, 0)
BIN_ENV = "ATLAS_NANOGRAPH_BIN"
VERSION_TIMEOUT = 10
BUILD_TIMEOUT = 120
RUN_TIMEOUT = 30
KEEP_GENERATIONS = 2
BM25_ROW_CAP = 500
QUERIES_NAME = "atlas.gq"
DB_NAME = "atlas.nano"
READY_NAME = "ready.json"
CURRENT_NAME = "current.json"
_GEN_NAME = re.compile(r"[0-9a-f]{16}(?:-[0-9a-f]{8})?")
STRIPPED_ENV = frozenset({"OPENAI_API_KEY", "GEMINI_API_KEY"})
STRIPPED_ENV_PREFIX = "NANOGRAPH_EMBED"
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def child_env() -> dict[str, str]:
    return {
        k: v
        for k, v in os.environ.items()
        if k not in STRIPPED_ENV and not k.startswith(STRIPPED_ENV_PREFIX)
    }


def query_ident(edge_type: str) -> str:
    return edge_type[:1].lower() + edge_type[1:]


def generate_queries(page_edge_types: list[str]) -> str:
    blocks = [
        "query bm25_text($q: String) {\n"
        "    match { $p: Page }\n"
        "    return { $p.slug, bm25($p.text, $q) as score }\n"
        "    order { bm25($p.text, $q) desc, $p.slug asc }\n"
        f"    limit {BM25_ROW_CAP}\n"
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
        self._detection: Detection | None = None

    # --- detection ------------------------------------------------------

    def find_binary(self) -> str | None:
        configured = os.environ.get(BIN_ENV, "").strip()
        if configured:
            path = Path(configured).expanduser()
            return str(path) if path.is_file() and os.access(path, os.X_OK) else None
        return shutil.which("nanograph")

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
            proc = subprocess.run(
                [binary, "--version"],
                capture_output=True,
                text=True,
                timeout=VERSION_TIMEOUT,
                env=child_env(),
                shell=False,
            )
            match = _VERSION.search(f"{proc.stdout}\n{proc.stderr}") if proc.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
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

    def _exec(self, args: list[str], cwd: Path, timeout: int) -> str:
        det = self._ready()
        argv = [str(det.binary), *args]
        try:
            proc = subprocess.run(
                argv,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=child_env(),
                shell=False,
            )
        except subprocess.TimeoutExpired as e:
            raise DriverError(f"{args[0]} timed out after {timeout}s") from e
        except OSError as e:
            raise DriverError(f"{args[0]} could not start ({e.strerror or e})") from e
        if proc.returncode != 0:
            raise DriverError(f"{args[0]} failed (exit {proc.returncode})")
        return proc.stdout

    def _run_query(self, gen_dir: Path, name: str, params: dict[str, str]) -> list[Any]:
        args = [
            "run",
            "--db", str(gen_dir / DB_NAME),
            "--query", str(gen_dir / QUERIES_NAME),
            "--name", name,
            "--format", "json",
        ]
        for key, value in params.items():
            args += ["--param", f"{key}={value}"]
        out = self._exec(args, gen_dir, RUN_TIMEOUT)
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
        db = index_dir / DB_NAME
        self._exec(
            ["init", "--db", str(db), "--schema", str(export_dir / "schema.pg")], index_dir, BUILD_TIMEOUT
        )
        self._exec(
            ["load", "--db", str(db), "--data", str(export_dir / "seed.jsonl"), "--mode", "overwrite"],
            index_dir,
            BUILD_TIMEOUT,
        )
        ready = {
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
        self, store: Path, source: dict[str, Any], wait: float | None = None, allow_legacy: bool = True
    ) -> Path:
        det = self._ready()
        digest = str(source.get("corpus_digest") or "")
        if not re.fullmatch(r"[0-9a-f]{16,}", digest):
            raise DriverError("corpus digest unavailable")
        base = self.index_base(store)
        self._guard(store, base / digest[:16])
        where = index_location.describe(store, "nanograph")
        gen_dir = self._current(base, digest, det.version)
        if gen_dir is None and allow_legacy:
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

        def build() -> Path:
            ensure_indexes_ignored(store)
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
                index_publish.publish_dir(tmp_dir, dest)
            except BaseException:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                raise
            ready = self._read_ready(dest) or {}
            index_publish.write_json_atomic(
                base / CURRENT_NAME,
                {
                    "generation": name,
                    "corpus_digest": digest,
                    "version": det.version,
                    "built_at": ready.get("built_at"),
                },
            )
            return dest

        reused = gen_dir is not None
        if gen_dir is None:
            try:
                gen_dir, built = index_publish.locked_build(
                    base, lambda: self._current(base, digest, det.version), build, wait=wait
                )
            except index_publish.IndexBusy as e:
                raise DriverError(str(e)) from e
            except OSError as e:
                raise DriverError(f"index build failed ({e.strerror or e})") from e
            reused = not built
            if built:
                self._prune(base, gen_dir)
        self.last_index = {
            "generation": gen_dir.name,
            "path": index_location.project_relative(store, gen_dir),
            "reused": reused,
            **where,
        }
        return gen_dir

    def _prune(self, base: Path, keep: Path) -> None:
        others: list[tuple[str, float, Path]] = []
        for child in base.iterdir():
            if child == keep or child.is_symlink() or not child.is_dir():
                continue
            if child.name.startswith(index_publish.TMP_PREFIX):
                continue
            ready = self._read_ready(child) or {}
            others.append((str(ready.get("built_at") or ""), child.stat().st_mtime, child))
        others.sort(reverse=True)
        for _, _, old in others[KEEP_GENERATIONS - 1 :]:
            shutil.rmtree(old, ignore_errors=True)

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
        type_kinds: dict[str, set[str]] = {}
        for edge in graph.all_edges(pages):
            if edge["resolved"] and not edge.get("external"):
                type_kinds.setdefault(graph.edge_type_name(edge["kind"]), set()).add(edge["kind"])
        clashes = sorted(t for t, ks in type_kinds.items() if len(ks) > 1)
        if clashes:
            raise DriverError(f"relation kinds collide on edge type {clashes[0]}")
        kind_of = {t: next(iter(ks)) for t, ks in type_kinds.items()}
        state: dict[str, Any] = {"gen_dir": None}
        cache: dict[tuple[str, str, str], list[str]] = {}

        def step(page_id: str, way: str, edge_type: str) -> list[str]:
            key = (page_id, way, edge_type)
            if key not in cache:
                if state["gen_dir"] is None:
                    state["gen_dir"] = self.ensure_index(store, source)
                rows = self._run_query(
                    state["gen_dir"], f"neighbours_{way}_{query_ident(edge_type)}", {"seed": page_id}
                )
                found = (_row_value(r, ("slug", "$n.slug", "n.slug"), 0) for r in rows)
                cache[key] = sorted({str(s) for s in found if isinstance(s, str) and s})
            return cache[key]

        def adjacency(page_id: str, way: str, wanted: frozenset[str]) -> list[tuple[str, str, str]]:
            out: list[tuple[str, str, str]] = []
            for edge_type, kind in sorted(kind_of.items()):
                if wanted and kind not in wanted:
                    continue
                if way in ("out", "both"):
                    out += [(o, kind, "outgoing") for o in step(page_id, "out", edge_type)]
                if way in ("in", "both"):
                    out += [(o, kind, "incoming") for o in step(page_id, "in", edge_type)]
            return out

        result = graph.query_neighbours(
            pages, seed, kinds=kinds, direction=direction, hops=hops, adjacency=adjacency, **options
        )
        if state["gen_dir"] is None:
            self.ensure_index(store, source)
        return {**result, "driver": self.id}
