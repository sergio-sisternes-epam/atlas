"""Strict JSON loading for closed Atlas configuration."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


class StrictJsonError(ValueError):
    pass


def _reject_nonfinite(obj: Any, path: str = "$") -> None:
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        raise StrictJsonError(f"non-finite number at {path}")
    if isinstance(obj, dict):
        for k, v in obj.items():
            _reject_nonfinite(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _reject_nonfinite(v, f"{path}[{i}]")


def object_pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise StrictJsonError(f"duplicate key {key!r}")
        out[key] = value
    return out


def loads_strict(text: str) -> Any:
    try:
        data = json.loads(text, object_pairs_hook=object_pairs_hook, parse_constant=lambda v: (_ for _ in ()).throw(StrictJsonError(f"non-standard constant {v!r}")))
    except json.JSONDecodeError as e:
        raise StrictJsonError(str(e)) from e
    _reject_nonfinite(data)
    return data


def load_strict(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise StrictJsonError(f"cannot read {path}: {e}") from e
    return loads_strict(text)
