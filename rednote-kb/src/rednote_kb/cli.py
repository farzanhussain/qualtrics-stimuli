from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv

from rednote_kb.db import dao
from rednote_kb.scrape import xhs_client
from rednote_kb.site import build as site_build


load_dotenv()

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="RedNote KB build pipeline (v0).")


DEFAULT_DB   = Path(os.environ.get("REDNOTE_DB",   "./data/rednote.db"))
DEFAULT_DIST = Path(os.environ.get("DIST_DIR",     "./dist"))


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
    """Ingest pre-scraped posts (see scrape/xhs_client.py for the schema)."""
    files = list(xhs_client.iter_post_files(path))
    if not files:
        typer.echo(f"no .json files under {path}", err=True)
        raise typer.Exit(1)

    n_posts = 0
    n_authors = 0
    with dao.session(db) as conn:
        for f in files:
            for raw in xhs_client.load_json_file(f):
                post = xhs_client.normalise(raw, default_source=source)
                if post["author_id"]:
                    dao.upsert_author(conn, {
                        "id":       post["author"]["id"],
                        "handle":   post["author"]["handle"],
                        "nickname": post["author"]["nickname"],
                        "followed": 1 if source == "creator" else 0,
                    })
                    n_authors += 1
                dao.upsert_post(conn, post)
                n_posts += 1
    typer.echo(f"ingested {n_posts} posts (from {len(files)} files), "
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
    typer.echo(f"built {result['posts']} posts → {dist}  @ {result['built_at']}")


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
