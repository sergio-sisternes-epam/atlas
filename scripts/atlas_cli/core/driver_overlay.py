"""Driver overlay: a small registry of retrieval drivers behind one interface.

Built-in drivers (``sqlite-fts5`` for BM25 search, ``native-graph`` for
traversal) run everywhere and are always the defaults. External drivers are
optional, platform-gated and never selected implicitly; callers fall back to
the built-in for the same capability when an external driver is unavailable
or fails. See references/drivers.md.
"""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

CAPABILITIES = frozenset({"bm25_search", "graph_traversal"})
DEFAULT_DRIVER = {"bm25_search": "sqlite-fts5", "graph_traversal": "native-graph"}

# One row per platform slot. Only darwin/arm64 has an external driver today;
# the other rows are reserved slots (planned: none) so a future driver for
# Windows or Linux has an obvious place to land.
PLATFORM_MATRIX: tuple[dict[str, Any], ...] = (
    {"platform": "darwin", "machine": "arm64", "external": {"nanograph": "supported"}, "planned": None},
    {"platform": "darwin", "machine": "x86_64", "external": {}, "planned": "none"},
    {"platform": "linux", "machine": "x86_64", "external": {}, "planned": "none"},
    {"platform": "linux", "machine": "aarch64", "external": {}, "planned": "none"},
    {"platform": "win32", "machine": "AMD64", "external": {}, "planned": "none"},
)

# Test-only: lets subprocess tests pretend to run on another platform, e.g.
# ATLAS_PLATFORM_OVERRIDE=darwin-arm64. Not a user-facing setting.
_PLATFORM_OVERRIDE_ENV = "ATLAS_PLATFORM_OVERRIDE"


class DriverError(RuntimeError):
    """A driver failed at run time; callers fall back to the built-in."""


class NotSupported(DriverError):
    """The driver does not implement the requested capability."""


@dataclass(frozen=True)
class Detection:
    available: bool
    reason: str
    version: str | None = None
    binary: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalise_machine(machine: str) -> str:
    """arm64 and aarch64 are the same machine; everything else is kept as reported."""
    text = (machine or "").strip()
    if text.lower() in ("arm64", "aarch64"):
        return "arm64"
    return text or "unknown"


def current_platform() -> tuple[str, str]:
    """(sys.platform, normalised machine). The single platform probe."""
    override = os.environ.get(_PLATFORM_OVERRIDE_ENV, "").strip()
    if override and "-" in override:
        plat, machine = override.split("-", 1)
        return plat, normalise_machine(machine)
    return sys.platform, normalise_machine(platform.machine())


def platform_label(plat: tuple[str, str] | None = None) -> str:
    p, m = plat or current_platform()
    return f"{p}-{m}"


def _platform_matches(rows: tuple[tuple[str, str], ...], plat: tuple[str, str]) -> bool:
    if not rows:
        return True
    p, m = plat
    return any(p == rp and normalise_machine(rm) == m for rp, rm in rows)


@runtime_checkable
class Driver(Protocol):
    """Interface every driver implements.

    ``capabilities`` is a subset of :data:`CAPABILITIES`; methods outside it
    raise :class:`NotSupported`. ``platforms`` lists ``(sys.platform,
    machine)`` pairs; empty means every platform. ``external`` drivers depend
    on a binary Atlas does not ship.
    """

    id: str
    capabilities: frozenset[str]
    platforms: tuple[tuple[str, str], ...]
    external: bool

    def detect(self) -> Detection: ...

    def build(self, export_dir: Path, index_dir: Path) -> dict[str, Any]: ...

    def bm25_search(self, store: Path, query: str, limit: int) -> list[dict[str, Any]]: ...

    def neighbours(
        self, store: Path, seed: str, kinds: list[str] | tuple[str, ...], direction: str, hops: int
    ) -> dict[str, Any]: ...

    def health(self) -> dict[str, Any]: ...


class BaseDriver:
    id = ""
    capabilities: frozenset[str] = frozenset()
    platforms: tuple[tuple[str, str], ...] = ()
    external = False
    # Driver type under <project-root>/.atlas/indexes/ (core/index_location.py), if any.
    index_type: str | None = None

    def _unsupported(self, capability: str) -> NotSupported:
        return NotSupported(f"driver {self.id} does not support {capability}")

    def supports_platform(self, plat: tuple[str, str] | None = None) -> bool:
        return _platform_matches(self.platforms, plat or current_platform())

    def detect(self) -> Detection:
        return Detection(True, "ok")

    def build(self, export_dir: Path, index_dir: Path) -> dict[str, Any]:
        return {"built": False, "reason": "built-in driver needs no separate index"}

    def bm25_search(self, store: Path, query: str, limit: int, **options: Any) -> list[dict[str, Any]]:
        raise self._unsupported("bm25_search")

    def neighbours(self, store, seed, kinds=(), direction="both", hops=1, **options) -> dict[str, Any]:
        raise self._unsupported("graph_traversal")

    def index_info(self, store: Path | None) -> dict[str, Any]:
        """``index_dir`` / ``index_location`` for drivers that keep an index."""
        if store is None or not self.index_type:
            return {}
        from . import index_location

        try:
            return index_location.describe(store, self.index_type)
        except (index_location.IndexLocationError, OSError):
            return {}

    def health(self, store: Path | None = None) -> dict[str, Any]:
        det = self.detect()
        return {"id": self.id, "ok": det.available, **det.as_dict(), **self.index_info(store)}

    def describe(self, store: Path | None = None) -> dict[str, Any]:
        return {
            "id": self.id,
            "capabilities": sorted(self.capabilities),
            "platforms": [f"{p}-{m}" for p, m in self.platforms] or ["all"],
            "external": self.external,
            "default_for": sorted(c for c, d in DEFAULT_DRIVER.items() if d == self.id),
            "detect": self.detect().as_dict(),
            **self.index_info(store),
        }


class SqliteFts5Driver(BaseDriver):
    """Built-in BM25 over SQLite FTS5 (the `--engine bm25` path)."""

    id = "sqlite-fts5"
    capabilities = frozenset({"bm25_search"})
    index_type = "fts5"

    def detect(self) -> Detection:
        from .recall_config import fts5_available

        if fts5_available():
            return Detection(True, "ok")
        return Detection(False, "sqlite3 lacks FTS5")

    def bm25_search(self, store: Path, query: str, limit: int, **options: Any) -> list[dict[str, Any]]:
        from ..commands.search import _bm25_search
        from .schema import load_schema

        schema, _ = load_schema(store)
        include_exits = bool(options.get("include_exits"))
        hits, warnings, _ = _bm25_search(store, schema, query, limit, include_exits)
        if hits is None:
            raise DriverError(warnings[-1] if warnings else "sqlite-fts5 search failed")
        for h in hits:
            h["driver"] = self.id
            h["score_orientation"] = "lower_better"
        return hits


class NativeGraphDriver(BaseDriver):
    """Built-in traversal over the shared page projection (`atlas graph`)."""

    id = "native-graph"
    capabilities = frozenset({"graph_traversal"})

    def neighbours(
        self, store, seed, kinds=(), direction="both", hops=1, *, source=None, **options
    ) -> dict[str, Any]:
        from . import graph

        source = source if source is not None else graph.load_source(store)
        result = graph.query_neighbours(
            source["pages"], seed, kinds=kinds, direction=direction, hops=hops, **options
        )
        return {**result, "driver": self.id}


def registry() -> dict[str, BaseDriver]:
    from .drivers.nanograph import NanographDriver

    drivers: list[BaseDriver] = [SqliteFts5Driver(), NativeGraphDriver(), NanographDriver()]
    return {d.id: d for d in drivers}


def get_driver(driver_id: str) -> BaseDriver:
    drivers = registry()
    if driver_id not in drivers:
        raise KeyError(f"unknown driver {driver_id!r}")
    return drivers[driver_id]


def describe_all(store: Path | None = None) -> dict[str, Any]:
    plat = current_platform()
    return {
        "platform": {"sys_platform": plat[0], "machine": plat[1], "label": platform_label(plat)},
        "defaults": dict(DEFAULT_DRIVER),
        "drivers": [d.describe(store) for d in registry().values()],
        "matrix": [dict(row) for row in PLATFORM_MATRIX],
    }
