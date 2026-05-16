from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv

from rednote_kb.db import dao
from rednote_kb.scrape import xhs_client
from rednote_kb.site import build as site_build


load_dotenv()

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="RedNote KB build pipeline.")


DEFAULT_DB   = Path(os.environ.get("REDNOTE_DB",   "./data/rednote.db"))
DEFAULT_DIST = Path(os.environ.get("DIST_DIR",     "./dist"))


def _persist_records(records: list[dict], db: Path, default_source: str) -> tuple[int, int]:
    """Returns (posts ingested, author rows touched)."""
    n_posts = n_authors = 0
    with dao.session(db) as conn:
        for raw in records:
            post = xhs_client.normalise(raw, default_source=default_source)
            if post["author_id"]:
                dao.upsert_author(conn, {
                    "id":       post["author"]["id"],
                    "handle":   post["author"]["handle"],
                    "nickname": post["author"]["nickname"],
                    "followed": 1 if default_source == "creator" else 0,
                })
                n_authors += 1
            dao.upsert_post(conn, post)
            n_posts += 1
    return n_posts, n_authors


@app.command("init-db")
def init_db(db: Path = DEFAULT_DB) -> None:
    """Create the SQLite schema (idempotent)."""
    with dao.session(db) as conn:
        st = dao.stats(conn)
    typer.echo(f"db ready at {db}  ({st['posts']} posts, {st['authors']} authors)")


@app.command("ingest-json")
def ingest_json(
    path: Path = typer.Argument(..., exists=True, readable=True,
                                help="JSON file or directory of JSON files"),
    source: str = typer.Option("manual", help="'creator' | 'seed_query' | 'manual'"),
    db: Path = DEFAULT_DB,
) -> None:
    """Ingest pre-scraped posts (see src/rednote_kb/scrape/xhs_client.py for the schema)."""
    files = list(xhs_client.iter_post_files(path))
    if not files:
        typer.echo(f"no .json files under {path}", err=True)
        raise typer.Exit(1)
    records: list[dict] = []
    for f in files:
        records.extend(xhs_client.load_json_file(f))
    n_posts, n_authors = _persist_records(records, db, source)
    typer.echo(f"ingested {n_posts} posts (from {len(files)} files), "
               f"touched {n_authors} author rows")


@app.command("scrape")
def scrape_cmd(
    urls: list[str] = typer.Argument(None, help="Note URLs (or pass --from-file)"),
    from_file: Optional[Path] = typer.Option(
        None, "--from-file", "-f", exists=True, readable=True,
        help="Read URLs from file, one per line (# comments OK).",
    ),
    source: str = typer.Option("manual", help="'creator' | 'seed_query' | 'manual'"),
    db: Path = DEFAULT_DB,
) -> None:
    """Scrape RedNote URLs via XHS-Downloader and ingest into the local DB."""
    from rednote_kb.scrape import xhs_downloader

    all_urls: list[str] = list(urls or [])
    if from_file:
        for line in from_file.read_text("utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                all_urls.append(line)
    if not all_urls:
        typer.echo("no URLs provided (pass positional args or --from-file)", err=True)
        raise typer.Exit(2)

    try:
        records = xhs_downloader.scrape_urls_sync(all_urls, source=source)
    except xhs_downloader.XHSDownloaderNotInstalled as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(3)

    if not records:
        typer.echo("scraped 0 posts (all URLs returned empty or failed)", err=True)
        raise typer.Exit(1)

    n_posts, n_authors = _persist_records(records, db, source)
    typer.echo(f"scraped {n_posts} posts from {len(all_urls)} urls; "
               f"touched {n_authors} author rows")


@app.command("add-creator")
def add_creator(
    author_id: str,
    nickname: Optional[str] = typer.Option(None),
    handle: Optional[str] = typer.Option(None),
    db: Path = DEFAULT_DB,
) -> None:
    """Mark a creator as followed (used by v1 creator-feed sync)."""
    with dao.session(db) as conn:
        dao.upsert_author(conn, {
            "id": author_id, "handle": handle, "nickname": nickname, "followed": 1,
        })
    typer.echo(f"followed creator {author_id}")


@app.command("add-query")
def add_query(q: str, db: Path = DEFAULT_DB) -> None:
    """Record a seed search query (used by v1 nightly seed-query refresh)."""
    with dao.session(db) as conn:
        dao.record_seed_query(conn, q, result_count=0)
    typer.echo(f"recorded seed query: {q}")


@app.command("build")
def build_cmd(
    db: Path = DEFAULT_DB,
    dist: Path = DEFAULT_DIST,
) -> None:
    """Build the static site into DIST_DIR."""
    result = site_build.build(db, dist)
    typer.echo(f"built {result['posts']} posts ({result['tokens']} tokens) "
               f"→ {dist}  @ {result['built_at']}")


@app.command("serve")
def serve_cmd(
    dist: Path = DEFAULT_DIST,
    port: int = typer.Option(8765, "--port", "-p"),
    bind: str = typer.Option("127.0.0.1", "--bind", "-b"),
) -> None:
    """Serve dist/ locally for browser preview."""
    import http.server, socketserver  # noqa
    if not dist.is_dir():
        typer.echo(f"no built site at {dist} — run `rednote-kb build` first", err=True)
        raise typer.Exit(1)
    os.chdir(dist)

    class Handler(http.server.SimpleHTTPRequestHandler):
        extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                          ".webmanifest": "application/manifest+json"}

    with socketserver.TCPServer((bind, port), Handler) as httpd:
        typer.echo(f"serving {dist} at http://{bind}:{port}/  (Ctrl-C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            typer.echo("stopped")


@app.command("stats")
def stats_cmd(db: Path = DEFAULT_DB) -> None:
    with dao.session(db) as conn:
        st = dao.stats(conn)
    typer.echo(json.dumps(st, indent=2))


@app.command("dev-fixture")
def dev_fixture(db: Path = DEFAULT_DB) -> None:
    """Load a tiny set of fake posts for local development / smoke tests."""
    here = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "sample_posts.json"
    if not here.exists():
        typer.echo(f"fixture not found at {here}", err=True)
        raise typer.Exit(1)
    ingest_json(here, source="manual", db=db)


if __name__ == "__main__":
    app()
