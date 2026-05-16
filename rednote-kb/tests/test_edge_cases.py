"""Adversarial / edge-case coverage for the ingest → DB → build pipeline.

Each test either documents a real bug (and asserts the post-fix behaviour) or
locks in defensible existing behaviour against silent regression. Stdlib +
pytest only — no new runtime deps.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

import pytest

from rednote_kb.db import dao
from rednote_kb.index.tokenize import is_cjk, tokenize, tokenize_unique
from rednote_kb.scrape import xhs_client
from rednote_kb.scrape.xhs_downloader import (
    _parse_int,
    _parse_published,
    _split_space,
    to_internal,
)
from rednote_kb.site import build as site_build


# ---------------------------------------------------------------------------
# xhs_client.normalise — input validation & robustness
# ---------------------------------------------------------------------------

def test_normalise_null_optional_fields() -> None:
    """JSON nulls everywhere optional must coerce to safe defaults, not crash."""
    rec = xhs_client.normalise({
        "id": "p1", "url": "https://x/p1",
        "title": None, "body": None, "tags": None, "author": None,
    })
    assert rec["title"] == ""
    assert rec["body"] == ""
    assert rec["tags"] == []
    assert rec["author_id"] is None
    assert rec["author"] == {"id": None, "nickname": None, "handle": None}


def test_normalise_requires_both_id_and_url() -> None:
    with pytest.raises(ValueError):
        xhs_client.normalise({"id": "p1"})            # no url
    with pytest.raises(ValueError):
        xhs_client.normalise({"url": "https://x/p"})  # no id


def test_normalise_rejects_empty_or_whitespace_id() -> None:
    """Empty id silently collides on the SQLite PK and produces a stray
    ``.html`` file at ``dist/p/.html``. Normalise rejects it instead."""
    for bad in ("", "   ", "\t\n"):
        with pytest.raises(ValueError):
            xhs_client.normalise({"id": bad, "url": "https://x/p"})


def test_normalise_rejects_path_traversal_id() -> None:
    """Post id ends up in ``dist/p/<id>.html``. An id with a path separator,
    a leading ``..``, or a NUL byte either crashes the build (FileNotFoundError
    on a missing parent) or — worse — writes outside ``dist/p``."""
    for bad in (".", "..", "../etc/passwd", "a/b", "a\\b", "a\x00b"):
        with pytest.raises(ValueError):
            xhs_client.normalise({"id": bad, "url": "https://x/p"})


def test_normalise_accepts_unicode_id_and_strips_whitespace() -> None:
    rec = xhs_client.normalise({"id": "  6中6  ", "url": "u"})
    assert rec["id"] == "6中6"


def test_normalise_coerces_int_id_to_str() -> None:
    rec = xhs_client.normalise({"id": 1234567890123, "url": "u"})
    assert rec["id"] == "1234567890123"


def test_normalise_preserves_weird_tags_verbatim() -> None:
    """Tag list contents aren't this layer's concern — only the surrounding
    container shape is. Downstream (search index, templates) must cope."""
    weird = [None, "", "  ", "tag,with,commas", 'tag"with"quotes', "tag\nwith\nnewline"]
    rec = xhs_client.normalise({"id": "p", "url": "u", "tags": weird})
    assert rec["tags"] == weird


def test_normalise_preserves_unusual_count_types() -> None:
    """We don't coerce counts here; the JSON adapter (xhs_downloader._parse_int)
    is the place that knows how to parse them. Locking in 'pass-through'."""
    rec = xhs_client.normalise({
        "id": "p", "url": "u",
        "like_count": "1.2k", "collect_count": None,
    })
    assert rec["like_count"] == "1.2k"
    assert rec["collect_count"] is None


def test_normalise_negative_counts_pass_through() -> None:
    rec = xhs_client.normalise({"id": "p", "url": "u", "like_count": -5})
    assert rec["like_count"] == -5


def test_normalise_images_missing_url_key_preserved() -> None:
    """Boundary-layer normalise doesn't validate image dict shape — the media
    pipeline (v3) does. Document the current pass-through."""
    rec = xhs_client.normalise({
        "id": "p", "url": "u",
        "images": [{"local_path": "/tmp/a.jpg"}, {}, {"url": "https://x/i.jpg"}],
    })
    assert len(rec["images"]) == 3
    assert rec["images"][0] == {"local_path": "/tmp/a.jpg"}


# ---------------------------------------------------------------------------
# DB round-trip for unusual but valid ids
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pid", [
    "65f1234abc",              # normal
    "id-with-dash",
    "id_with_underscore",
    "中文ID2024",                # CJK
    "a" * 64,                   # long but plausible
    ".hidden",                   # leading dot — legal as a filename component
    "65f.note.id",               # dots inside
    "id with spaces",            # whitespace mid-string
])
def test_post_id_round_trips_through_db_and_build(tmp_path: Path, pid: str) -> None:
    db = tmp_path / "rednote.db"
    dist = tmp_path / "dist"
    rec = xhs_client.normalise({"id": pid, "url": f"https://x/{pid}", "title": "t"})
    with dao.session(db) as conn:
        dao.upsert_post(conn, rec)
    site_build.build(db, dist)
    assert (dist / "p" / f"{pid}.html").is_file()


def test_duplicate_post_ids_in_same_file_dedup_via_upsert(tmp_path: Path) -> None:
    """Two posts with the same id in the same JSON file: the second wins."""
    db = tmp_path / "rednote.db"
    with dao.session(db) as conn:
        dao.upsert_post(conn, xhs_client.normalise(
            {"id": "p1", "url": "https://x/a", "title": "first"}))
        dao.upsert_post(conn, xhs_client.normalise(
            {"id": "p1", "url": "https://x/b", "title": "second"}))
        rows = list(conn.execute("SELECT id, title, url FROM posts"))
    assert len(rows) == 1
    assert rows[0]["title"] == "second"
    assert rows[0]["url"] == "https://x/b"


# ---------------------------------------------------------------------------
# Title / body extreme content
# ---------------------------------------------------------------------------

def test_huge_body_excerpt_truncates_fast(tmp_path: Path) -> None:
    """100k-char body: excerpt must be bounded, build must finish quickly."""
    db = tmp_path / "rednote.db"
    dist = tmp_path / "dist"
    big = "上" * 100_000
    with dao.session(db) as conn:
        dao.upsert_post(conn, xhs_client.normalise(
            {"id": "big", "url": "u", "title": "t", "body": big}))
    t0 = time.perf_counter()
    site_build.build(db, dist)
    elapsed = time.perf_counter() - t0
    assert elapsed < 5.0, f"100k-char body build too slow: {elapsed:.2f}s"
    payload = json.loads((dist / "posts.json").read_text("utf-8"))
    p = payload["posts"][0]
    assert len(p["body_excerpt"]) <= site_build.EXCERPT_CHARS + 1  # +1 for '…'
    assert p["body_excerpt"].endswith("…")
    # Tokenization dedups, so a 100k-char run of one char collapses to 1 token.
    assert p["_t"]["body"] == ["上"]


def test_title_with_emoji_rtl_zero_width(tmp_path: Path) -> None:
    """Wild Unicode must survive ingestion + build without exceptions, and
    non-tokenizable characters must not appear as ghost tokens."""
    db = tmp_path / "rednote.db"
    dist = tmp_path / "dist"
    # Emoji + RTL Hebrew + zero-width joiner + word joiner.
    title = "brunch \U0001f60a ‮RTL‬ zero​width⁠here"
    with dao.session(db) as conn:
        dao.upsert_post(conn, xhs_client.normalise(
            {"id": "wild", "url": "u", "title": title, "body": ""}))
    site_build.build(db, dist)
    payload = json.loads((dist / "posts.json").read_text("utf-8"))
    title_toks = payload["posts"][0]["_t"]["title"]
    # 'brunch' and 'rtl' and 'zero' / 'width' / 'here' survive; the rest dropped.
    assert "brunch" in title_toks
    assert "rtl" in title_toks
    # Hebrew/emoji/ZW chars must not leak in as standalone tokens.
    assert all(re.fullmatch(r"[a-z0-9_]+|[㐀-䶿一-鿿]", t)
               for t in title_toks), title_toks


def test_punctuation_only_post_has_no_tokens(tmp_path: Path) -> None:
    """A post whose title+body+tags are all punctuation is *unsearchable* (it
    contributes no postings) but still appears in the ``posts`` array so the
    per-post HTML page is reachable by direct URL."""
    db = tmp_path / "rednote.db"
    dist = tmp_path / "dist"
    with dao.session(db) as conn:
        dao.upsert_post(conn, xhs_client.normalise({
            "id": "punct", "url": "u",
            "title": "!!! ??? ...", "body": "—— ：；！", "tags": ["!!!"],
        }))
    site_build.build(db, dist)
    payload = json.loads((dist / "posts.json").read_text("utf-8"))
    assert len(payload["posts"]) == 1
    assert payload["posts"][0]["_t"] == {
        "title": [], "body": [], "tag": [], "author": [],
    }
    # No postings reference index 0 — search will never find it.
    for postings in payload["tok"].values():
        assert 0 not in postings
    assert (dist / "p" / "punct.html").is_file()


def test_tag_doubles_as_body_word_scores_both_fields(tmp_path: Path) -> None:
    """If a token appears in both the tag and the body, the inverted index
    should still list the post exactly once, but the score-time code in
    search.js sums field weights — so the per-field token sets must include
    the token in both places so scoring picks up both hits."""
    db = tmp_path / "rednote.db"
    dist = tmp_path / "dist"
    with dao.session(db) as conn:
        dao.upsert_post(conn, xhs_client.normalise({
            "id": "p1", "url": "u",
            "title": "...", "body": "brunch is great",
            "tags": ["brunch"],
        }))
    site_build.build(db, dist)
    payload = json.loads((dist / "posts.json").read_text("utf-8"))
    p = payload["posts"][0]
    assert "brunch" in p["_t"]["body"]
    assert "brunch" in p["_t"]["tag"]
    # Inverted index lists it exactly once.
    assert payload["tok"]["brunch"] == [0]


# ---------------------------------------------------------------------------
# XHS-Downloader adapter
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("", None),
    ("NaN", None),
    (None, None),
    ("0", 0),
    ("  123  ", 123),
    ("1,234,567", 1234567),
    ("-5", -5),
    ("1.5", None),       # float string is *not* a valid int — lock current behaviour
    ("1.2k", None),      # human-formatted counts not parsed (yet)
    ("abc", None),
])
def test_parse_int(raw, expected) -> None:
    assert _parse_int(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("", None),
    ("NaN", None),
    (None, None),
    ("2024-01-15_10:20:30", "2024-01-15T10:20:30+00:00"),
    # Unparseable strings are passed through verbatim — better to surface a
    # weird value in the DB than to drop the field silently. Lock it in.
    ("2024/01/15 10:20", "2024/01/15 10:20"),
    ("invalid", "invalid"),
])
def test_parse_published(raw, expected) -> None:
    assert _parse_published(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("", []),
    ("NaN", []),
    (None, []),
    ("a  b   c", ["a", "b", "c"]),
    ("a\tb", ["a", "b"]),
    ("a NaN b", ["a", "b"]),     # mid-string NaN tokens are dropped, not kept
    ("NaN NaN NaN", []),
    ("   ", []),
])
def test_split_space(raw, expected) -> None:
    assert _split_space(raw) == expected


def test_to_internal_missing_id_returns_none() -> None:
    """Required key missing — must return None, never crash."""
    assert to_internal({}) is None
    assert to_internal({"作品标题": "no id here"}) is None
    assert to_internal(None) is None  # type: ignore[arg-type]


def test_to_internal_synthesises_url_when_missing() -> None:
    rec = to_internal({"作品ID": "abc123"})
    assert rec is not None
    assert rec["url"] == "https://www.xiaohongshu.com/explore/abc123"
    assert rec["tags"] == []
    assert rec["images"] == []


def test_to_internal_maps_full_record() -> None:
    rec = to_internal({
        "作品ID": "n1", "作品链接": "https://x/n1",
        "作品标题": "标题", "作品描述": "body",
        "作品标签": "上海 brunch", "作者ID": "a1", "作者昵称": "周末探店",
        "点赞数量": "1,820", "收藏数量": "945",
        "发布时间": "2024-01-15_10:20:30",
        "下载地址": "https://img/1.jpg https://img/2.jpg",
    })
    assert rec is not None
    assert rec["tags"] == ["上海", "brunch"]
    assert rec["like_count"] == 1820
    assert rec["author"]["nickname"] == "周末探店"
    assert rec["published_at"] == "2024-01-15T10:20:30+00:00"
    assert rec["images"] == [{"url": "https://img/1.jpg"}, {"url": "https://img/2.jpg"}]


# ---------------------------------------------------------------------------
# Tokenizer — beyond the existing parity tests
# ---------------------------------------------------------------------------

def test_tokenize_whitespace_only() -> None:
    assert tokenize("   ") == []
    assert tokenize("\t\n\r ") == []
    assert tokenize_unique("   ") == []


def test_tokenize_mixed_hangul_hiragana_cjk_drops_non_cjk() -> None:
    """Current rule: only CJK Unified (U+4E00–9FFF) + Ext-A (U+3400–4DBF)
    are kept as ideographs. Hangul (U+AC00+) and hiragana (U+3040+) are
    treated as boundaries — they vanish. Lock this in; if it ever changes,
    static/search.js MUST move in lockstep."""
    # CJK 中 + hiragana の + hangul 한 + latin abc
    assert tokenize("中のabc한") == ["中", "abc"]


def test_tokenize_cjk_ext_b_supplementary_plane() -> None:
    """U+20000+ (CJK Ext-B and beyond) is *not* matched as CJK by either side:

    - Python sees a single char with ``ord() > 0xFFFF`` — outside our range.
    - JS sees two surrogate halves (high 0xD840+, low 0xDC00+) — outside too.

    Both sides drop the supplementary char as a boundary, which keeps parity
    accidentally. Locking in current behaviour so a future tokenizer fix on
    one side doesn't silently break recall on the other."""
    ext_b = chr(0x20000)              # 𠀀
    assert not is_cjk(ext_b)
    assert tokenize(f"{ext_b}abc") == ["abc"]
    assert tokenize(f"a{ext_b}b") == ["a", "b"]


# ---------------------------------------------------------------------------
# Inverted index & build pipeline
# ---------------------------------------------------------------------------

def test_inverted_index_postings_sorted(tmp_path: Path) -> None:
    """search.js does sorted-merge intersection; postings MUST be ascending."""
    db = tmp_path / "rednote.db"
    dist = tmp_path / "dist"
    with dao.session(db) as conn:
        for i in range(20):
            dao.upsert_post(conn, xhs_client.normalise({
                "id": f"p{i:02d}", "url": f"u/{i}",
                "title": "brunch", "tags": ["上海"],
            }))
    site_build.build(db, dist)
    payload = json.loads((dist / "posts.json").read_text("utf-8"))
    for tok, postings in payload["tok"].items():
        assert postings == sorted(postings), f"{tok!r} postings not sorted"
        assert len(postings) == len(set(postings)), f"{tok!r} has duplicate postings"


def test_index_size_under_1mb_for_1000_posts(tmp_path: Path) -> None:
    """README budget: ~1MB JSON per 1000 posts. If this regresses, the PWA
    payload bloats and her phone takes longer to first-search."""
    db = tmp_path / "rednote.db"
    dist = tmp_path / "dist"
    with dao.session(db) as conn:
        for i in range(1000):
            dao.upsert_post(conn, xhs_client.normalise({
                "id": f"p{i:04d}",
                "url": f"https://x/{i}",
                "title": f"笔记 {i} 上海 brunch",
                "body": "周末和朋友去了几家徐汇区的 brunch " * 5,
                "tags": ["上海", "brunch", f"tag{i % 10}"],
            }))
    site_build.build(db, dist)
    size = (dist / "posts.json").stat().st_size
    assert size < 1_000_000, f"posts.json {size} bytes — over 1 MB budget"


def test_foreign_key_blocks_orphan_author_post(tmp_path: Path) -> None:
    """Inserting a post whose ``author_id`` doesn't exist in ``authors`` must
    fail the FK check — better to surface the bug at ingest time than to ship
    a post with a missing author link to the static site."""
    db = tmp_path / "rednote.db"
    with dao.session(db) as conn:
        post = xhs_client.normalise(
            {"id": "p", "url": "u", "author": {"id": "ghost"}})
        with pytest.raises(sqlite3.IntegrityError):
            dao.upsert_post(conn, post)


def test_build_is_deterministic_modulo_timestamp(tmp_path: Path) -> None:
    """Two consecutive builds of the same DB must differ only in ``built_at``
    (and any rendered representation of it). Important for CI diff hygiene."""
    db = tmp_path / "rednote.db"
    d1 = tmp_path / "d1"
    d2 = tmp_path / "d2"
    fixture = Path(__file__).parent / "fixtures" / "sample_posts.json"
    raws = xhs_client.load_json_file(fixture)
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
    site_build.build(db, d1)
    time.sleep(1.1)  # force a different ISO-second built_at
    site_build.build(db, d2)

    p1 = json.loads((d1 / "posts.json").read_text("utf-8"))
    p2 = json.loads((d2 / "posts.json").read_text("utf-8"))
    assert p1["built_at"] != p2["built_at"]
    p1.pop("built_at"); p2.pop("built_at")
    assert p1 == p2

    ts = re.compile(r"20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00")
    for f in (d1 / "p").iterdir():
        a = ts.sub("TS", f.read_text("utf-8"))
        b = ts.sub("TS", (d2 / "p" / f.name).read_text("utf-8"))
        assert a == b, f"per-post HTML for {f.name} differs across builds"


def test_rebuild_removes_stale_post_html(tmp_path: Path) -> None:
    """Soft-deleting a post and rebuilding must drop its HTML page from
    ``dist/p/``. Previously, ghost pages lingered: still discoverable by
    direct URL, completely absent from the search index, broken UX."""
    db = tmp_path / "rednote.db"
    dist = tmp_path / "dist"
    with dao.session(db) as conn:
        dao.upsert_post(conn, xhs_client.normalise(
            {"id": "old", "url": "u/old", "title": "first"}))
    site_build.build(db, dist)
    assert (dist / "p" / "old.html").is_file()

    # Soft-delete the old post, ingest a new one, rebuild.
    raw = sqlite3.connect(db)
    raw.execute("UPDATE posts SET deleted = 1 WHERE id = ?", ("old",))
    raw.commit()
    raw.close()
    with dao.session(db) as conn:
        dao.upsert_post(conn, xhs_client.normalise(
            {"id": "new", "url": "u/new", "title": "second"}))
    site_build.build(db, dist)

    assert (dist / "p" / "new.html").is_file()
    assert not (dist / "p" / "old.html").exists(), \
        "stale per-post HTML from prior build was not cleaned up"
