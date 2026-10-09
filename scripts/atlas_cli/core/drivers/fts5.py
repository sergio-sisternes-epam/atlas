"""SQLite FTS5 fused coarse/rank driver."""

from __future__ import annotations

import sqlite3
import unicodedata
from typing import Any

# Mirrors SQLite's default ``unicode61`` tokenizer (the one ``pages_fts`` is
# built with): token characters are Unicode letters and numbers (L*, N*),
# private-use characters (Co) and, because ``remove_diacritics`` defaults to
# 1, non-spacing marks (Mn) such as a decomposed acute accent, which unicode61
# keeps inside the token and then folds away. Everything else separates
# tokens, including ``_`` (so ``foo_bar`` is two tokens), spacing marks (Mc),
# symbols such as emoji, and punctuation. Python's ``\w`` is not a match: it
# keeps ``_`` and splits on Mn. Case and diacritics are left to FTS5, which
# folds the quoted query terms the same way it folded the index, so ``café``
# and ``cafe`` match each other. A contiguous CJK run is one token on both
# sides, so ``東京`` does not match inside ``東京都`` (a unicode61 limitation).
# Python's Unicode tables may be newer than SQLite's; the gap is only in
# characters assigned since, which neither side is likely to meet.
_TOKEN_CATEGORIES = frozenset({"Co", "Mn"})


def _is_token_char(ch: str) -> bool:
    cat = unicodedata.category(ch)
    return cat[0] in "LN" or cat in _TOKEN_CATEGORIES


def query_tokens(text: str) -> list[str]:
    """Split ``text`` into tokens the way unicode61 would (case and diacritics kept)."""
    tokens: list[str] = []
    current: list[str] = []
    for ch in text or "":
        if _is_token_char(ch):
            current.append(ch)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tokens


def _quote(token: str) -> str:
    return '"' + token.replace('"', '""') + '"'


def _operator(operator: str) -> str:
    op = str(operator or "AND").strip().upper()
    if op not in ("AND", "OR"):
        raise ValueError(f"unsupported fts5 operator: {operator}")
    return op


def escape_query(text: str, operator: str = "AND") -> str:
    op = _operator(operator)
    tokens = query_tokens(text)
    if not tokens:
        return '""'
    return f" {op} ".join(_quote(t) for t in tokens)


_ALLOWED_TABLE = "atlas_allowed_ids"


def search(
    conn: sqlite3.Connection,
    query: str,
    limit: int,
    weights: dict[str, float] | None = None,
    operator: str = "AND",
    allowed: set[str] | frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """Ranked hits; ``allowed`` (page ids) is applied in SQL before ``limit``.

    Eligibility is joined through a TEMP table, so ``limit`` counts eligible
    rows only and the connection may be read-only.
    """
    w = weights or {"primary": 5.0, "secondary": 2.0, "body": 1.0}
    q = escape_query(query, operator)
    join = ""
    if allowed is not None:
        conn.execute(f"CREATE TEMP TABLE IF NOT EXISTS {_ALLOWED_TABLE} (id TEXT PRIMARY KEY)")
        conn.execute(f"DELETE FROM temp.{_ALLOWED_TABLE}")
        conn.executemany(
            f"INSERT OR IGNORE INTO temp.{_ALLOWED_TABLE} (id) VALUES (?)",
            ((str(i),) for i in sorted(allowed)),
        )
        join = f"JOIN temp.{_ALLOWED_TABLE} AS allowed ON allowed.id = pages.id"
    sql = f"""
    SELECT pages.id, pages.path, pages.title, pages.body,
           json_extract(pages.meta_json, '$.type') AS type,
           bm25(pages_fts, 0, ?, ?, ?) AS rank
    FROM pages_fts
    JOIN pages ON pages.id = pages_fts.id
    {join}
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
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        if allowed is not None:
            conn.execute(f"DROP TABLE IF EXISTS temp.{_ALLOWED_TABLE}")
    out: list[dict[str, Any]] = []
    for row in rows:
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


def search_eligible(
    conn: sqlite3.Connection,
    text: str,
    limit: int,
    weights: dict[str, float] | None,
    allowed: set[str] | frozenset[str] | None,
) -> tuple[list[dict[str, Any]], str]:
    """All-word hits among ``allowed``; any-word only when no eligible all-word hit exists.

    Returns ``(hits, match)`` with ``match`` ``"all"`` or ``"any"``. Both
    passes filter in SQL before ``limit`` (0 = unlimited), so an eligible
    all-word match is never lost behind higher-ranked ineligible pages.
    """
    hits = search(conn, text, limit, weights, "AND", allowed)
    if hits or len(query_tokens(text)) < 2:
        return hits, "all"
    hits = search(conn, text, limit, weights, "OR", allowed)
    for h in hits:
        h["match"] = "any"
    return hits, "any"
