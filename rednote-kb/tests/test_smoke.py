"""End-to-end smoke: fixture → DB → built dist/. Run with `pytest -q`."""
from __future__ import annotations

import json
from pathlib import Path

from rednote_kb.db import dao
from rednote_kb.scrape import xhs_client
from rednote_kb.site import build as site_build


FIXTURE = Path(__file__).parent / "fixtures" / "sample_posts.json"


def test_build_from_fixture(tmp_path: Path) -> None:
    db = tmp_path / "rednote.db"
    dist = tmp_path / "dist"

    raws = xhs_client.load_json_file(FIXTURE)
    with dao.session(db) as conn:
        for raw in raws:
            post = xhs_client.normalise(raw)
            if post["author_id"]:
                dao.upsert_author(conn, {
                    "id":       post["author"]["id"],
                    "handle":   post["author"]["handle"],
                    "nickname": post["author"]["nickname"],
                    "followed": 1,
                })
            dao.upsert_post(conn, post)

    result = site_build.build(db, dist)
    assert result["posts"] == len(raws)

    index_html = (dist / "index.html").read_text("utf-8")
    assert "小红书 KB" in index_html
    assert f"{len(raws)} posts" in index_html

    payload = json.loads((dist / "posts.json").read_text("utf-8"))
    assert payload["v"] == site_build.SITE_VERSION
    assert len(payload["posts"]) == len(raws)
    titles = {p["title"] for p in payload["posts"]}
    assert "日本京都 5 日游攻略" in titles

    assert (dist / "p" / "fixture-001.html").exists()
    post_html = (dist / "p" / "fixture-001.html").read_text("utf-8")
    assert "../static/style.css" in post_html, "post page must reference static one level up"
    assert "../index.html" in post_html

    assert (dist / "static" / "search.js").exists()
    assert (dist / "static" / "style.css").exists()
    assert (dist / "robots.txt").read_text("utf-8").startswith("User-agent: *")


def test_upsert_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "rednote.db"
    raws = xhs_client.load_json_file(FIXTURE)
    with dao.session(db) as conn:
        for _ in range(2):
            for raw in raws:
                post = xhs_client.normalise(raw)
                if post["author_id"]:
                    dao.upsert_author(conn, {
                        "id":       post["author"]["id"],
                        "handle":   post["author"]["handle"],
                        "nickname": post["author"]["nickname"],
                        "followed": 1,
                    })
                dao.upsert_post(conn, post)
        st = dao.stats(conn)
    assert st["posts"] == len(raws)
