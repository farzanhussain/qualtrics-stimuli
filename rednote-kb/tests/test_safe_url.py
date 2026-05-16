"""Defends against `javascript:` / `data:` URIs surviving from ingest into rendered HTML."""
from __future__ import annotations

import json
from pathlib import Path

from rednote_kb.db import dao
from rednote_kb.scrape import xhs_client
from rednote_kb.site import build as site_build
from rednote_kb.site.build import _safe_url


def test_safe_url_allows_http_and_https() -> None:
    assert _safe_url("https://www.xiaohongshu.com/explore/abc") == \
        "https://www.xiaohongshu.com/explore/abc"
    assert _safe_url("http://example.com") == "http://example.com"


def test_safe_url_strips_javascript_uris() -> None:
    assert _safe_url("javascript:alert(1)") == ""
    assert _safe_url("JaVaScRiPt:alert(1)") == ""  # case-insensitive scheme
    assert _safe_url("  javascript:alert(1)") == ""


def test_safe_url_strips_data_uris() -> None:
    assert _safe_url("data:text/html,<script>alert(1)</script>") == ""


def test_safe_url_strips_other_schemes() -> None:
    for bad in ("file:///etc/passwd", "vbscript:msgbox", "about:blank", "ftp://x"):
        assert _safe_url(bad) == "", f"should reject {bad!r}"


def test_safe_url_none_and_empty() -> None:
    assert _safe_url(None) == ""
    assert _safe_url("") == ""
    assert _safe_url("   ") == ""


def test_safe_url_applied_in_build(tmp_path: Path) -> None:
    """A post ingested with a javascript: URL must not surface as a clickable href."""
    db = tmp_path / "rednote.db"
    dist = tmp_path / "dist"
    raw = {
        "id": "evil-001",
        "url": "javascript:alert('xss')",
        "title": "ostensibly innocent title",
        "body": "body",
        "author": {"id": "a", "nickname": "a"},
        "source": "manual",
    }
    with dao.session(db) as conn:
        post = xhs_client.normalise(raw)
        dao.upsert_author(conn, {
            "id": "a", "handle": None, "nickname": "a", "followed": 0,
        })
        dao.upsert_post(conn, post)
    site_build.build(db, dist)

    page = (dist / "p" / "evil-001.html").read_text("utf-8")
    assert "javascript:" not in page.lower(), \
        "javascript: URI must not survive into rendered href"

    payload = json.loads((dist / "posts.json").read_text("utf-8"))
    [p] = payload["posts"]
    assert p["url"] == "", "search index must also strip unsafe url"
