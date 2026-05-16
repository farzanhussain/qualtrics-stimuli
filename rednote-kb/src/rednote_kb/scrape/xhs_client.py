"""Boundary between this project and the upstream scraper.

v0 takes pre-scraped post JSON files as input. Run XHS-Downloader
(https://github.com/JoeanAmier/XHS-Downloader) yourself on your laptop with
your own cookies, normalise its output to the schema documented below, then
hand a directory of those JSON files to ``rednote-kb ingest-json``.

This indirection insulates the build pipeline from XHS-Downloader's
monthly signature churn. v1 will optionally drive XHS-Downloader as a
subprocess once a stable CLI surface is wired up.

Input JSON schema (one file per post, or a JSON array of posts):

    {
      "id": "65f...",                          # required, xhs note id
      "url": "https://www.xiaohongshu.com/...",# required
      "title": "...",                          # optional
      "body": "...",                           # optional
      "tags": ["..."],                         # optional
      "author": {                              # optional
        "id": "...",
        "nickname": "...",
        "handle": "..."
      },
      "like_count": 0,                         # optional
      "collect_count": 0,                      # optional
      "published_at": "2026-01-01T00:00:00Z",  # optional, ISO8601
      "images": [                              # optional, used in v1+
        {"url": "https://...", "local_path": "/abs/path.jpg"}
      ],
      "source": "creator"                      # 'creator'|'seed_query'|'manual'
    }
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalise(raw: dict, default_source: str = "manual") -> dict:
    if "id" not in raw or "url" not in raw:
        raise ValueError(f"post missing required id/url: {raw!r:.120}")
    author = raw.get("author") or {}
    return {
        "id":            str(raw["id"]),
        "url":           raw["url"],
        "title":         raw.get("title", "") or "",
        "body":          raw.get("body", "") or "",
        "tags":          list(raw.get("tags") or []),
        "author_id":     author.get("id"),
        "author":        {
            "id":       author.get("id"),
            "nickname": author.get("nickname"),
            "handle":   author.get("handle"),
        },
        "like_count":    raw.get("like_count"),
        "collect_count": raw.get("collect_count"),
        "published_at":  raw.get("published_at"),
        "images":        list(raw.get("images") or []),
        "fetched_at":    raw.get("fetched_at") or _now(),
        "source":        raw.get("source") or default_source,
    }


def load_json_file(path: Path) -> list[dict]:
    data = json.loads(path.read_text("utf-8"))
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return data
    raise ValueError(f"{path}: expected JSON object or array, got {type(data).__name__}")


def iter_post_files(root: Path) -> Iterator[Path]:
    if root.is_file():
        yield root
        return
    yield from sorted(root.rglob("*.json"))
