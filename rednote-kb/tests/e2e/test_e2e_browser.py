"""Real-browser end-to-end test driven by Playwright (Node).

Builds the fixture site into a tmp dir, serves it on a free port, runs the
Node-side Playwright script that exercises the search UI / SW / PWA / mobile
layout, then asserts the script reported all scenarios green.

Skips cleanly when Node, the Playwright npm package, or a usable Chromium
binary aren't available (CI environments without browser downloads).
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from contextlib import closing
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from rednote_kb.db import dao
from rednote_kb.scrape import xhs_client
from rednote_kb.site import build as site_build


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE   = REPO_ROOT / "tests" / "fixtures" / "sample_posts.json"
E2E_JS    = Path(__file__).parent / "playwright_e2e.js"

# Where Playwright's chromium tarball is usually unpacked.
PW_BROWSERS = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _resolve_playwright_module() -> str | None:
    """Return absolute path to the playwright npm module, or None if missing."""
    for candidate in (
        "/opt/node22/lib/node_modules/playwright",
        "/usr/lib/node_modules/playwright",
        "/usr/local/lib/node_modules/playwright",
    ):
        if Path(candidate, "package.json").exists():
            return candidate
    # last resort: ask `node` itself
    try:
        out = subprocess.check_output(
            ["node", "-e", "console.log(require.resolve('playwright'))"],
            stderr=subprocess.DEVNULL, text=True, timeout=5,
        ).strip()
        return str(Path(out).parent) if out else None
    except Exception:
        return None


def _have_chromium() -> bool:
    p = Path(PW_BROWSERS)
    if not p.is_dir():
        return False
    return any(p.glob("chromium*/chrome-linux/chrome")) or \
           any(p.glob("chromium*/chrome-linux/headless_shell"))


@pytest.fixture(scope="module")
def built_site(tmp_path_factory) -> Path:
    """Build a fresh site from the fixture into a tmp dist/ and return its path."""
    tmp = tmp_path_factory.mktemp("e2e_site")
    db   = tmp / "rednote.db"
    dist = tmp / "dist"
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


@pytest.fixture(scope="module")
def http_server(built_site: Path):
    """Serve built_site on a free port for the duration of the module."""
    port = _free_port()
    cwd = os.getcwd()
    # SimpleHTTPRequestHandler resolves relative to cwd, so chdir into dist.
    os.chdir(built_site)

    class Handler(SimpleHTTPRequestHandler):
        # ensure .webmanifest gets a sensible content-type
        extensions_map = {**SimpleHTTPRequestHandler.extensions_map,
                          ".webmanifest": "application/manifest+json"}

        def log_message(self, *_a, **_k):  # noqa: D401  — silence test noise
            return

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    # tiny readiness wait
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        os.chdir(cwd)


def test_browser_e2e(http_server: str) -> None:
    if not shutil.which("node"):
        pytest.skip("node not installed")
    pw_module = _resolve_playwright_module()
    if not pw_module:
        pytest.skip("playwright npm package not installed (run `npm i -g playwright`)")
    if not _have_chromium():
        pytest.skip(
            f"no chromium binary under {PW_BROWSERS} — run "
            f"`PLAYWRIGHT_BROWSERS_PATH={PW_BROWSERS} playwright install chromium`"
        )

    env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": PW_BROWSERS}
    # The js script hard-codes the playwright module path under /opt/node22,
    # but allow it to be overridden via NODE_PATH for portability.
    env.setdefault("NODE_PATH", str(Path(pw_module).parent))

    proc = subprocess.run(
        ["node", str(E2E_JS), http_server],
        env=env, capture_output=True, text=True, timeout=120,
    )

    # Parse the JSON lines the script emits, surface failures clearly.
    scenarios: list[dict] = []
    summary: dict | None = None
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if obj.get("name") == "_summary_":
            summary = obj
        else:
            scenarios.append(obj)

    # Build a readable failure message if anything went red.
    if proc.returncode != 0 or not summary or not summary.get("pass"):
        msg_lines = [f"e2e exit={proc.returncode}"]
        if summary:
            msg_lines.append(f"summary: {summary}")
        for s in scenarios:
            if not s.get("pass"):
                msg_lines.append(f"FAILED {s['name']}: {s.get('info')}")
        if proc.stderr.strip():
            msg_lines.append("--- stderr ---")
            msg_lines.append(proc.stderr.strip())
        pytest.fail("\n".join(msg_lines))

    # Sanity: did all expected scenarios actually run?
    expected = {
        "home_renders",
        "manifest_link_resolves",
        "search_kyoto_finds_003",
        "search_multi_token",
        "click_navigates_to_post",
        "no_match_shows_empty_msg",
        "service_worker_registers",
        "mobile_layout",
    }
    got = {s["name"] for s in scenarios}
    missing = expected - got
    assert not missing, f"missing scenarios: {missing}; stdout={proc.stdout}"
