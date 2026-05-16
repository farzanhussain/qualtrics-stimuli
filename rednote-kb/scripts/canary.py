#!/usr/bin/env python3
"""Pre-build health check. Exits non-zero if the pipeline can't be trusted.

Run by the systemd timer before `rednote-kb build && deploy`. Designed to
prevent shipping a broken or stale site on top of a working one.

Checks (cheap, fast — under a few seconds):
  1. Schema initialises cleanly.
  2. Inverted index rebuilds from current DB content without error.
  3. Build output exists and `posts.json` is non-empty (unless DB is empty —
     fresh installs are allowed to pass with 0 posts).
  4. (optional) If XHS_COOKIE is set and XHS-Downloader is importable, do NOT
     call the network here — keeping the canary offline-safe; cookie-validity
     checks live in their own ad-hoc script.

Writes a health summary to data/health.json so the site can surface it.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from rednote_kb.db import dao
from rednote_kb.index.tokenize import tokenize
from rednote_kb.site import build as site_build

# CLI auto-loads .env via typer; the canary runs standalone under systemd,
# so load it explicitly or REDNOTE_DB / paths silently fall back to defaults.
load_dotenv()


def main() -> int:
    db = Path(os.environ.get("REDNOTE_DB", "./data/rednote.db"))
    health = {
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ok": False,
        "errors": [],
        "posts": 0,
        "tokens_smoke": 0,
    }

    try:
        with dao.session(db) as conn:
            st = dao.stats(conn)
        health["posts"] = st["posts"]

        # Tokenizer canary — must produce expected tokens for a known input.
        sample = tokenize("上海 brunch 推荐 iPhone 15")
        expected = ["上", "海", "brunch", "推", "荐", "iphone", "15"]
        if sample != expected:
            health["errors"].append(f"tokenizer drift: {sample!r} != {expected!r}")
        health["tokens_smoke"] = len(sample)

        # Build into a tmpdir (no side effects on dist/).
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "dist"
            result = site_build.build(db, tmp)
            payload = json.loads((tmp / "posts.json").read_text("utf-8"))
            if payload.get("v") != site_build.SITE_VERSION:
                health["errors"].append(f"posts.json v={payload.get('v')}")
            if st["posts"] and not payload.get("posts"):
                health["errors"].append("posts.json is empty despite posts in DB")
            if st["posts"] and not payload.get("tok"):
                health["errors"].append("inverted index is empty despite posts in DB")
            health["built_in_temp"] = result["posts"]

    except Exception:
        health["errors"].append("exception: " + traceback.format_exc().strip().splitlines()[-1])

    health["ok"] = not health["errors"]
    out = Path("data") / "health.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(health, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(health, ensure_ascii=False))
    return 0 if health["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
