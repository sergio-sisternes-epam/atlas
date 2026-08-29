#!/usr/bin/env python3
"""Shim — all logic lives in atlas_cli/ (Click wiring)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atlas_cli.cli import main

if __name__ == "__main__":
    main()
