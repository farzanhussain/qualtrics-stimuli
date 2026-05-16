from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from rednote_kb.db import dao


SITE_VERSION = 1  # bumped when posts.json schema changes


def _env() -> Environment:
    tmpl_dir = resources.files("rednote_kb.site").joinpath("templates")
    return Environment(
        loader=FileSystemLoader(str(tmpl_dir)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _copy_static(dist: Path) -> None:
    src = Path(str(resources.files("rednote_kb.site").joinpath("static")))
    dst = dist / "static"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _post_excerpt(body: str, limit: int = 240) -> str:
    body = (body or "").strip()
    return body if len(body) <= limit else body[:limit].rstrip() + "…"


def _row_to_record(row, thumbs: list[str]) -> dict:
    try:
        tags = json.loads(row["tags"]) if row["tags"] else []
    except (ValueError, TypeError):
        tags = []
    return {
        "id":            row["id"],
        "url":           row["url"],
        "title":         row["title"] or "",
        "body":          row["body"] or "",
        "body_excerpt":  _post_excerpt(row["body"] or ""),
        "ocr_text":      row["ocr_text"] or "",
        "tags":          tags,
        "author":        row["author_nickname"] or row["author_handle"] or "",
        "thumb":         thumbs[0] if thumbs else None,
        "published_at":  row["published_at"],
        "fetched_at":    row["fetched_at"],
    }


def build(db_path: Path, dist: Path) -> dict:
    dist.mkdir(parents=True, exist_ok=True)
    env = _env()
    base_tmpl   = env.get_template("base.html")  # noqa: F841  (loaded for syntax check)
    index_tmpl  = env.get_template("index.html")
    post_tmpl   = env.get_template("post.html")

    posts: list[dict] = []
    with dao.session(db_path) as conn:
        for row in dao.iter_active_posts(conn):
            thumbs = dao.post_thumbs(conn, row["id"])
            posts.append(_row_to_record(row, thumbs))
        st = dao.stats(conn)

    built_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    (dist / "posts.json").write_text(
        json.dumps(
            {"v": SITE_VERSION, "built_at": built_at, "posts": posts},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    (dist / "index.html").write_text(
        index_tmpl.render(built_at=built_at, stats=st),
        encoding="utf-8",
    )

    posts_dir = dist / "p"
    posts_dir.mkdir(exist_ok=True)
    for p in posts:
        (posts_dir / f"{p['id']}.html").write_text(
            post_tmpl.render(
                post=p,
                built_at=built_at,
                static_prefix="../static",
                home="../index.html",
            ),
            encoding="utf-8",
        )

    _copy_static(dist)

    (dist / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")

    return {"posts": len(posts), "built_at": built_at, "stats": st}
