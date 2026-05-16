from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from rednote_kb.db import dao
from rednote_kb.index.tokenize import tokenize_unique


SITE_VERSION = 2  # bumped from 1 when posts.json schema changed (inverted index)

EXCERPT_CHARS = 140


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


def _copy_pwa(dist: Path) -> None:
    """PWA assets (manifest, sw, icon) must sit at the site root for SW scope."""
    src = Path(str(resources.files("rednote_kb.site").joinpath("pwa")))
    for f in src.iterdir():
        if f.is_file():
            shutil.copy2(f, dist / f.name)


def _excerpt(body: str, limit: int = EXCERPT_CHARS) -> str:
    body = (body or "").strip().replace("\n", " ")
    return body if len(body) <= limit else body[:limit].rstrip() + "…"


def _row_to_record(row, thumbs: list[str]) -> dict:
    try:
        tags = json.loads(row["tags"]) if row["tags"] else []
    except (ValueError, TypeError):
        tags = []
    title  = row["title"] or ""
    body   = row["body"]  or ""
    ocr    = row["ocr_text"] or ""
    author = row["author_nickname"] or row["author_handle"] or ""

    return {
        "id":            row["id"],
        "url":           row["url"],
        "title":         title,
        "body":          body,                 # stripped before serialising for search index
        "body_excerpt":  _excerpt(body),
        "author":        author,
        "tags":          tags,
        "published_at":  row["published_at"],
        "fetched_at":    row["fetched_at"],
        "like_count":    row["like_count"],
        "thumb":         thumbs[0] if thumbs else None,
        "ocr_text":      ocr,
        "_t": {
            "title":  tokenize_unique(title),
            "body":   tokenize_unique(body + " " + ocr),
            "tag":    tokenize_unique(" ".join(tags)),
            "author": tokenize_unique(author),
        },
    }


def _build_inverted_index(posts: list[dict]) -> dict[str, list[int]]:
    """token → sorted list of post indices that contain it in any field."""
    idx: dict[str, list[int]] = {}
    for i, p in enumerate(posts):
        seen: set[str] = set()
        for field in ("title", "body", "tag", "author"):
            for tok in p["_t"][field]:
                if tok in seen:
                    continue
                seen.add(tok)
                idx.setdefault(tok, []).append(i)
    return idx


def build(db_path: Path, dist: Path) -> dict:
    dist.mkdir(parents=True, exist_ok=True)
    env = _env()
    _ = env.get_template("base.html")  # parse-check
    index_tmpl = env.get_template("index.html")
    post_tmpl  = env.get_template("post.html")

    posts: list[dict] = []
    with dao.session(db_path) as conn:
        for row in dao.iter_active_posts(conn):
            thumbs = dao.post_thumbs(conn, row["id"])
            posts.append(_row_to_record(row, thumbs))
        st = dao.stats(conn)

    tok_index = _build_inverted_index(posts)
    built_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Render post pages from the full records (with body + ocr).
    posts_dir = dist / "p"
    posts_dir.mkdir(exist_ok=True)
    fresh_html: set[str] = set()
    for p in posts:
        view = {k: v for k, v in p.items() if k != "_t"}
        fname = f"{p['id']}.html"
        fresh_html.add(fname)
        (posts_dir / fname).write_text(
            post_tmpl.render(
                post=view,
                built_at=built_at,
                static_prefix="../static",
                root_prefix="../",
                home="../index.html",
            ),
            encoding="utf-8",
        )
    # Clean up stale per-post HTML from prior builds. Without this, deleted or
    # renamed posts linger as ghost pages after a rebuild — broken from the
    # search index but discoverable via crawled/old links.
    for existing in posts_dir.iterdir():
        if existing.is_file() and existing.suffix == ".html" and existing.name not in fresh_html:
            existing.unlink()

    # Strip full body/ocr from the shipped search index — display uses excerpts.
    search_posts = []
    for p in posts:
        sp = {k: v for k, v in p.items() if k not in ("body", "ocr_text")}
        search_posts.append(sp)

    (dist / "posts.json").write_text(
        json.dumps(
            {"v": SITE_VERSION, "built_at": built_at,
             "posts": search_posts, "tok": tok_index},
            ensure_ascii=False, separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    (dist / "index.html").write_text(
        index_tmpl.render(built_at=built_at, stats=st,
                          static_prefix="./static", root_prefix="./",
                          home="./index.html"),
        encoding="utf-8",
    )

    _copy_static(dist)
    _copy_pwa(dist)
    (dist / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")

    return {"posts": len(posts), "tokens": len(tok_index),
            "built_at": built_at, "stats": st}
