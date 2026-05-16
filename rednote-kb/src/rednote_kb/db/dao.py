from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Iterable, Iterator


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    sql = resources.files("rednote_kb.db").joinpath("schema.sql").read_text("utf-8")
    conn.executescript(sql)
    conn.commit()


@contextmanager
def session(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        init_schema(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_author(conn: sqlite3.Connection, author: dict) -> None:
    conn.execute(
        """
        INSERT INTO authors (id, handle, nickname, followed, last_crawled)
        VALUES (:id, :handle, :nickname, :followed, :last_crawled)
        ON CONFLICT(id) DO UPDATE SET
          handle       = COALESCE(excluded.handle, handle),
          nickname     = COALESCE(excluded.nickname, nickname),
          followed     = MAX(followed, excluded.followed),
          last_crawled = excluded.last_crawled
        """,
        {
            "id": author["id"],
            "handle": author.get("handle"),
            "nickname": author.get("nickname"),
            "followed": int(author.get("followed", 0)),
            "last_crawled": _now(),
        },
    )


def upsert_post(conn: sqlite3.Connection, post: dict) -> None:
    conn.execute(
        """
        INSERT INTO posts (
          id, url, author_id, title, body, ocr_text, tags,
          like_count, collect_count, published_at, fetched_at, source, deleted
        )
        VALUES (
          :id, :url, :author_id, :title, :body, :ocr_text, :tags,
          :like_count, :collect_count, :published_at, :fetched_at, :source, 0
        )
        ON CONFLICT(id) DO UPDATE SET
          url           = excluded.url,
          author_id     = COALESCE(excluded.author_id, author_id),
          title         = excluded.title,
          body          = excluded.body,
          tags          = excluded.tags,
          like_count    = excluded.like_count,
          collect_count = excluded.collect_count,
          published_at  = COALESCE(excluded.published_at, published_at),
          fetched_at    = excluded.fetched_at,
          source        = COALESCE(posts.source, excluded.source)
        """,
        {
            "id": post["id"],
            "url": post["url"],
            "author_id": post.get("author_id"),
            "title": post.get("title", ""),
            "body": post.get("body", ""),
            "ocr_text": post.get("ocr_text"),
            "tags": json.dumps(post.get("tags", []), ensure_ascii=False),
            "like_count": post.get("like_count"),
            "collect_count": post.get("collect_count"),
            "published_at": post.get("published_at"),
            "fetched_at": post.get("fetched_at") or _now(),
            "source": post.get("source", "manual"),
        },
    )


def add_image(conn: sqlite3.Connection, post_id: str, thumb_path: str | None,
              full_path: str | None, sha256: str) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO images (post_id, thumb_path, full_path, sha256)
        VALUES (?, ?, ?, ?)
        """,
        (post_id, thumb_path, full_path, sha256),
    )


def record_seed_query(conn: sqlite3.Connection, q: str, result_count: int) -> None:
    conn.execute(
        """
        INSERT INTO seed_queries (q, last_run, result_count)
        VALUES (?, ?, ?)
        ON CONFLICT(q) DO UPDATE SET
          last_run     = excluded.last_run,
          result_count = excluded.result_count
        """,
        (q, _now(), result_count),
    )


def iter_active_posts(conn: sqlite3.Connection) -> Iterable[sqlite3.Row]:
    return conn.execute(
        """
        SELECT p.*, a.nickname AS author_nickname, a.handle AS author_handle
        FROM posts p
        LEFT JOIN authors a ON a.id = p.author_id
        WHERE p.deleted = 0
        ORDER BY COALESCE(p.published_at, p.fetched_at) DESC
        """
    )


def post_thumbs(conn: sqlite3.Connection, post_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT thumb_path FROM images WHERE post_id = ? AND thumb_path IS NOT NULL",
        (post_id,),
    ).fetchall()
    return [r["thumb_path"] for r in rows]


def stats(conn: sqlite3.Connection) -> dict:
    return {
        "posts":   conn.execute("SELECT COUNT(*) c FROM posts  WHERE deleted = 0").fetchone()["c"],
        "authors": conn.execute("SELECT COUNT(*) c FROM authors").fetchone()["c"],
        "images":  conn.execute("SELECT COUNT(*) c FROM images").fetchone()["c"],
    }
