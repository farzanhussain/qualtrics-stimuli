"""Adapter around JoeanAmier/XHS-Downloader (https://github.com/JoeanAmier/XHS-Downloader).

XHS-Downloader returns dicts with Chinese keys; we map them to our internal
schema so the rest of the pipeline never sees vendor-specific shapes.

The upstream package is imported lazily so the rest of the project still works
when it isn't installed. On the laptop, install per its README:

    git clone https://github.com/JoeanAmier/XHS-Downloader vendor/XHS-Downloader
    pip install -r vendor/XHS-Downloader/requirements.txt
    export PYTHONPATH=$PWD/vendor/XHS-Downloader:$PYTHONPATH

then set XHS_COOKIE in .env and run:

    uv run rednote-kb scrape <url> [<url> ...]
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Iterable


CHINESE_TO_INTERNAL = {
    "作品ID":     "id",
    "作品链接":   "url",
    "作品标题":   "title",
    "作品描述":   "body",
    "作品标签":   "tags",
    "作者ID":     "_author_id",
    "作者昵称":   "_author_nickname",
    "点赞数量":   "like_count",
    "收藏数量":   "collect_count",
    "发布时间":   "_published_at_xhs",
    "下载地址":   "_image_urls",
}


class XHSDownloaderNotInstalled(RuntimeError):
    pass


def _parse_int(v) -> int | None:
    if v in (None, "", "NaN"):
        return None
    try:
        return int(str(v).replace(",", "").strip())
    except ValueError:
        return None


def _parse_published(v: str | None) -> str | None:
    """XHS format: '2024-01-15_10:20:30' (or empty). Emit ISO8601 (UTC assumed)."""
    if not v or v in ("NaN",):
        return None
    try:
        dt = datetime.strptime(v, "%Y-%m-%d_%H:%M:%S")
        return dt.replace(tzinfo=timezone.utc).isoformat(timespec="seconds")
    except ValueError:
        return v  # leave as-is rather than drop


def _split_space(v: str | None) -> list[str]:
    if not v or v == "NaN":
        return []
    return [t for t in str(v).split() if t and t != "NaN"]


def to_internal(raw: dict, source: str = "manual") -> dict | None:
    """Map XHS-Downloader's Chinese-keyed dict to our schema. None on empty/failure."""
    if not raw or not raw.get("作品ID"):
        return None
    mapped = {our: raw.get(zh) for zh, our in CHINESE_TO_INTERNAL.items()}
    return {
        "id":            mapped["id"],
        "url":           mapped["url"] or f"https://www.xiaohongshu.com/explore/{mapped['id']}",
        "title":         mapped["title"] or "",
        "body":          mapped["body"]  or "",
        "tags":          _split_space(mapped["tags"]),
        "author": {
            "id":       mapped["_author_id"],
            "nickname": mapped["_author_nickname"],
            "handle":   None,
        },
        "like_count":    _parse_int(mapped["like_count"]),
        "collect_count": _parse_int(mapped["collect_count"]),
        "published_at":  _parse_published(mapped["_published_at_xhs"]),
        "images":        [{"url": u} for u in _split_space(mapped["_image_urls"])],
        "fetched_at":    datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source":        source,
    }


async def _extract_one(xhs, url: str) -> dict | None:
    results = await xhs.extract(url, download=False)
    if not results:
        return None
    raw = results[0] if isinstance(results, list) else results
    return raw if raw else None


async def scrape_urls(urls: Iterable[str], cookie: str | None = None,
                       source: str = "manual") -> list[dict]:
    """Drive XHS-Downloader's Python API for a batch of note URLs.

    Returns the internal-schema records (one per successful URL).
    Raises XHSDownloaderNotInstalled if the upstream package isn't importable.
    """
    try:
        from source import XHS  # type: ignore[import-not-found]
    except ImportError as e:
        raise XHSDownloaderNotInstalled(
            "XHS-Downloader is not importable. See "
            "rednote_kb/scrape/xhs_downloader.py docstring for install steps."
        ) from e

    cookie = cookie or os.environ.get("XHS_COOKIE", "") or ""
    if not cookie:
        # Many endpoints work without cookie but quality degrades; warn loudly.
        import sys
        print("[warn] XHS_COOKIE is empty — some content may not extract cleanly",
              file=sys.stderr)

    out: list[dict] = []
    async with XHS(
        cookie=cookie,
        record_data=False,      # we manage our own DB
        download_record=False,  # we manage dedup
    ) as xhs:
        for url in urls:
            raw = await _extract_one(xhs, url)
            if not raw:
                print(f"[skip] no data for {url}", file=__import__("sys").stderr)
                continue
            rec = to_internal(raw, source=source)
            if rec:
                out.append(rec)
    return out


def scrape_urls_sync(urls: Iterable[str], cookie: str | None = None,
                     source: str = "manual") -> list[dict]:
    return asyncio.run(scrape_urls(urls, cookie=cookie, source=source))
