"""SQLite FTS5 fused coarse/rank driver."""

from __future__ import annotations

import re
import sqlite3
from typing import Any

_SAFE = re.compile(r"[A-Za-z0-9_]+")


def escape_query(text: str) -> str:
    tokens = _SAFE.findall(text)
    if not tokens:
        return '""'
    return " AND ".join(f'"{t}"' for t in tokens)


def search(
    conn: sqlite3.Connection,
    query: str,
    limit: int,
    weights: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    w = weights or {"primary": 5.0, "secondary": 2.0, "body": 1.0}
    q = escape_query(query)
    sql = """
    SELECT pages.id, pages.path, pages.title, pages.body,
           json_extract(pages.meta_json, '$.type') AS type,
           bm25(pages_fts, 0, ?, ?, ?) AS rank
    FROM pages_fts
    JOIN pages ON pages.id = pages_fts.id
    WHERE pages_fts MATCH ?
    ORDER BY rank ASC, pages.id ASC
    """
    params: list[Any] = [
        w.get("primary", 5.0),
        w.get("secondary", 2.0),
        w.get("body", 1.0),
        q,
    ]
    if limit and limit > 0:
        sql += " LIMIT ?"
        params.append(int(limit))
    cur = conn.execute(sql, params)
    out: list[dict[str, Any]] = []
    for row in cur:
        out.append(
            {
                "path": row[1],
                "score": float(row[5]),
                "score_orientation": "lower_better",
                "title": row[2] or "",
                "type": row[4] or "",
                "snippet": (row[3] or "")[:160].replace("\n", " ").strip(),
                "driver": "sqlite-fts5",
            }
        )
    return out
