from __future__ import annotations

import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ..core.paths import SCHEMA_NAME, store_root

BUST_NAME = ".okf-wiki-listing-bust"
SKILL_DIR = Path(__file__).resolve().parents[3]
ENV_FILE = Path("/home/workdir/artifacts/atlas-viewer.env")


def is_atlas(path: Path) -> bool:
    if not path.is_dir():
        return False
    return (path / SCHEMA_NAME).is_file() or (path / "index.md").is_file() or (path / "SCHEMA.md").is_file()


def run(
    root: str | None,
    host: str | None,
    check: bool,
    open_browser: bool,
    refresh: bool = False,
) -> int:
    path = store_root(root)
    if not path.is_dir():
        print(f"error: root does not exist: {path}")
        return 2
    if not is_atlas(path):
        print(f"error: not an Atlas (need SCHEMA.json or index.md): {path}")
        return 2
    host = (host or os.environ.get("ATLAS_VIEWER_HOST") or "http://127.0.0.1:8080").rstrip("/")
    url = f"{host}/?root={urllib.parse.quote(str(path), safe='/')}"
    (SKILL_DIR / ".last-view-root").write_text(str(path) + "\n", encoding="utf-8")

    try:
        ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        ENV_FILE.write_text(
            f"ATLAS_ROOT={path}\n"
            f"ATLAS_VIEWER_ROOT={path}\n"
            f"ATLAS_PRESETS=Atlas:{path}\n",
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"warn: could not write env file ({exc})")

    if refresh:
        bust = path / BUST_NAME
        bust.write_text(f"{time.time()}\n", encoding="utf-8")
        print(f"refresh\tbust\t{bust}")

    print(f"atlas\t{path}")
    print(f"viewer\t{url}")
    if check or refresh:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                print(f"status\t{resp.status}")
                if refresh:
                    print("refresh\tprobed (open this URL / hard-reload preview to rescan)")
        except urllib.error.URLError as exc:
            print("error: Grok Build preview is not running")
            print("mode\tBuild-only — Cartograph does not start its own server")
            print(f"detail\t{exc}")
            if refresh:
                print("refresh\tbust written; start host then open viewer URL")
            return 1
    if open_browser:
        try:
            import webbrowser

            webbrowser.open(url)
            print("opened\tbrowser")
        except Exception as exc:  # noqa: BLE001
            print(f"warn: could not launch browser ({exc})")
    return 0
