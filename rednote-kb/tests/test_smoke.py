"""End-to-end smoke: fixture → DB → built dist/. Run with `pytest -q`."""
from __future__ import annotations

import json
from pathlib import Path

from rednote_kb.db import dao
from rednote_kb.scrape import xhs_client
from rednote_kb.site import build as site_build


FIXTURE = Path(__file__).parent / "fixtures" / "sample_posts.json"


def _ingest_fixture(db: Path) -> int:
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
    return len(raws)


def test_build_from_fixture(tmp_path: Path) -> None:
    db = tmp_path / "rednote.db"
    dist = tmp_path / "dist"
    n = _ingest_fixture(db)

    result = site_build.build(db, dist)
    assert result["posts"] == n
    assert result["tokens"] > 0

    index_html = (dist / "index.html").read_text("utf-8")
    assert "小红书 KB" in index_html
    assert f"{n} posts" in index_html
    assert "manifest.webmanifest" in index_html

    payload = json.loads((dist / "posts.json").read_text("utf-8"))
    assert payload["v"] == site_build.SITE_VERSION
    assert len(payload["posts"]) == n
    titles = {p["title"] for p in payload["posts"]}
    assert "日本京都 5 日游攻略" in titles

    # Per-field token sets shipped, but raw body/ocr stripped from search payload.
    p0 = payload["posts"][0]
    assert "_t" in p0 and {"title", "body", "tag", "author"}.issubset(p0["_t"])
    assert "body" not in p0, "raw body should be stripped from search index"
    assert "ocr_text" not in p0

    # Inverted index covers known terms.
    assert "京" in payload["tok"]
    assert "brunch" in payload["tok"]
    assert isinstance(payload["tok"]["京"], list)

    assert (dist / "p" / "fixture-001.html").exists()
    post_html = (dist / "p" / "fixture-001.html").read_text("utf-8")
    assert "../static/style.css" in post_html
    assert "../index.html" in post_html
    assert "../manifest.webmanifest" in post_html
    assert "周末和朋友" in post_html  # full body rendered on post page

    # PWA assets at site root, not under static/.
    assert (dist / "manifest.webmanifest").exists()
    assert (dist / "sw.js").exists()
    assert (dist / "icon.svg").exists()
    # PNG icons for iOS Safari (SVG isn't reliably honoured for apple-touch-icon).
    for size in (180, 192, 512):
        png = dist / f"icon-{size}.png"
        assert png.exists(), f"missing {png.name}"
        assert png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"), f"{png.name} not a valid PNG"
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


def test_empty_db_builds_cleanly(tmp_path: Path) -> None:
    """Pipeline must not crash on an empty database — the canary expects this."""
    db = tmp_path / "rednote.db"
    dist = tmp_path / "dist"
    result = site_build.build(db, dist)
    assert result["posts"] == 0
    payload = json.loads((dist / "posts.json").read_text("utf-8"))
    assert payload["posts"] == []
    assert payload["tok"] == {}
    assert (dist / "index.html").exists()
    assert (dist / "sw.js").exists()
