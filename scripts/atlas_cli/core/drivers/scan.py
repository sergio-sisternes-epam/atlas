"""Substring scan coarse/rank driver."""

from __future__ import annotations

import re
from typing import Any

from ..projection import ProjectedPage

_TOKEN = re.compile(r"[^\w]+")


def tokenise(q: str) -> list[str]:
    return [t for t in _TOKEN.split(q.lower()) if len(t) > 1]


def score_page(page: ProjectedPage, tokens: list[str]) -> tuple[float, list[str]]:
    if page.role == "log":
        return 0.0, []
    title = page.title.lower()
    desc = page.description.lower()
    body = page.body.lower()
    blob = f"{title}\n{desc}\n{body}"
    score = 0.0
    hits: list[str] = []
    for t in tokens:
        c = blob.count(t)
        if not c:
            continue
        hits.append(t)
        score += c
        if t in title:
            score += 5
        if t in desc:
            score += 2
    return score, hits


def search(pages: list[ProjectedPage], query: str, limit: int) -> list[dict[str, Any]]:
    tokens = tokenise(query)
    hits: list[dict[str, Any]] = []
    if not tokens:
        return hits
    for page in pages:
        if page.role == "log":
            continue
        score, terms = score_page(page, tokens)
        if score <= 0:
            continue
        hits.append(
            {
                "path": page.path,
                "score": score,
                "title": page.title,
                "type": str(page.meta.get("type") or ""),
                "terms": terms,
                "snippet": page.body[:160].replace("\n", " ").strip(),
                "driver": "scan",
            }
        )
    hits.sort(key=lambda h: (-h["score"], h["path"]))
    return hits[:limit] if limit else hits
