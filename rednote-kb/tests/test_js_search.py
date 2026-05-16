"""Build the fixture site, then run the browser search.js against it in Node.

Catches regressions in tokenization, inverted-index lookup, and scoring as one.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from rednote_kb.db import dao
from rednote_kb.scrape import xhs_client
from rednote_kb.site import build as site_build

FIXTURE = Path(__file__).parent / "fixtures" / "sample_posts.json"
JS_PATH = Path(__file__).resolve().parent.parent / "src" / "rednote_kb" / "site" / "static" / "search.js"


def _build_site(tmp_path: Path) -> Path:
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
    site_build.build(db, dist)
    return dist


def _run_search(dist: Path, queries: list[str]) -> list[list[str]]:
    """For each query: return [post.id, ...] from the JS search ranked top first."""
    if not shutil.which("node"):
        pytest.skip("node not installed")

    posts_json = (dist / "posts.json").read_text("utf-8")
    src = JS_PATH.read_text("utf-8")
    # Take everything up to (and including) the search() function definition.
    src = src.split("function escapeHtml")[0]

    program = textwrap.dedent(f"""
        {src}
        const index = {posts_json};
        const queries = {json.dumps(queries, ensure_ascii=False)};
        const out = queries.map(q => search(index, q).hits.map(h => h.id));
        process.stdout.write(JSON.stringify(out));
    """)
    res = subprocess.run(["node", "-e", program], check=True,
                         capture_output=True, text=True)
    return json.loads(res.stdout)


def test_cjk_query_finds_post(tmp_path: Path) -> None:
    dist = _build_site(tmp_path)
    out = _run_search(dist, ["京都", "brunch", "敏感肌", "燕麦", "武康"])
    kyoto, brunch, sensitive, oats, wukang = out
    assert "fixture-003" in kyoto
    assert "fixture-001" in brunch                # title hit, ranks first
    assert "fixture-002" in sensitive
    assert "fixture-004" in oats
    assert "fixture-005" in wukang


def test_multi_token_query_intersects(tmp_path: Path) -> None:
    dist = _build_site(tmp_path)
    out = _run_search(dist, ["上海 brunch", "上海 武康"])
    sh_brunch, sh_wukang = out
    assert "fixture-001" in sh_brunch
    assert "fixture-005" in sh_wukang
    # fixture-003 (Kyoto) does not mention 上海 — must be excluded.
    assert "fixture-003" not in sh_brunch
    assert "fixture-003" not in sh_wukang


def test_no_match_returns_empty(tmp_path: Path) -> None:
    dist = _build_site(tmp_path)
    out = _run_search(dist, ["zzznotfoundzzz", "孫悟空火星基地"])
    for r in out:
        assert r == []


def test_title_outranks_body(tmp_path: Path) -> None:
    """Posts that hit a query term in the TITLE should rank above posts that
    only hit it in the body (field-weighted scoring)."""
    dist = _build_site(tmp_path)
    # 'brunch' appears in fixture-001 title and body, and in fixture-005 body only.
    out = _run_search(dist, ["brunch"])
    [hits] = out
    assert hits[0] == "fixture-001", f"title hit should be first; got {hits}"


def test_empty_query_returns_empty(tmp_path: Path) -> None:
    dist = _build_site(tmp_path)
    out = _run_search(dist, ["", "   "])
    for r in out:
        assert r == []
