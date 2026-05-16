# rednote-kb

Personal static knowledge base over RedNote (Xiaohongshu / 小红书). Builds a
phone-friendly **PWA** from scraped post data and deploys it to GitHub Pages —
no always-on server, no recurring cost. CJK-aware client-side search; sub-100ms
on a 1000-post corpus.

Full architecture and roadmap: `../.claude/plans/my-girlfriend-wants-to-goofy-backus.md`.

## What's shipped (v1)

- **SQLite** store (`data/rednote.db`) + Typer CLI
- **Scraping**: drives JoeanAmier/XHS-Downloader programmatically (or ingest pre-built JSON)
- **Search index**: per-field token sets + inverted index, built in Python from a
  CJK-aware tokenizer; mirrored byte-for-byte in JavaScript so the browser query path
  matches what was indexed. Field weights: title 10 · tag 5 · author 3 · body 1.
- **PWA**: installable to phone home screen, offline-capable (service worker
  caches the shell + post pages and serves `posts.json` network-first).
- **systemd timer** (`systemd/rednote-build.timer`) rebuilds every 6h with
  canary protection so a broken build can't replace a working one.
- **Tests**: Python unit tests, end-to-end build smoke, **Python↔JS tokenizer
  parity** test, **end-to-end JS search** test (built site exercised in Node).

## Setup (one-time, on your laptop)

```bash
cd rednote-kb
uv sync                                # creates .venv, installs deps
cp .env.example .env                   # fill XHS_COOKIE and SITE_REPO_DIR
uv run rednote-kb init-db
```

Create the **public** site repo on GitHub (e.g. `rednote-kb-site`) and clone
it alongside this project:

```bash
git clone git@github.com:<you>/rednote-kb-site.git ../rednote-kb-site
```

Enable Pages on that repo (Settings → Pages → branch `main` / `/`). The first
deploy fills it with content.

Install [XHS-Downloader](https://github.com/JoeanAmier/XHS-Downloader) so
`rednote-kb scrape` works:

```bash
git clone https://github.com/JoeanAmier/XHS-Downloader vendor/XHS-Downloader
pip install -r vendor/XHS-Downloader/requirements.txt
echo 'export PYTHONPATH=$PWD/vendor/XHS-Downloader:$PYTHONPATH' >> .env
```

## Quickstart with fixture data (no scraping needed)

```bash
uv run rednote-kb dev-fixture
uv run rednote-kb build
uv run rednote-kb serve           # http://127.0.0.1:8765
```

## Daily flow

```bash
# 1. Scrape new posts (URLs as args OR from a file)
uv run rednote-kb scrape https://www.xiaohongshu.com/explore/<id> --source creator
uv run rednote-kb scrape --from-file urls.txt --source seed_query

# 2. Mark a creator as followed (used by future RSSHub auto-sync)
uv run rednote-kb add-creator <author_id> --nickname "..."

# 3. Build the site and ship it
uv run rednote-kb build
./scripts/deploy.sh

# 4. Inspect
uv run rednote-kb stats
```

## Auto-rebuild every 6h (optional)

```bash
mkdir -p ~/.config/systemd/user
cp systemd/rednote-build.{service,timer} ~/.config/systemd/user/
# edit the WorkingDirectory in the .service file to point at this checkout
loginctl enable-linger $USER      # so the timer fires while you're logged out
systemctl --user daemon-reload
systemctl --user enable --now rednote-build.timer
systemctl --user list-timers
journalctl --user -u rednote-build.service -f
```

The service runs `scripts/canary.py` before building; if the canary fails,
deploy is skipped and `data/health.json` records why.

## Tests

```bash
uv run pytest -q                  # all tests
uv run pytest tests/test_js_parity.py -q   # requires Node
uv run pytest tests/test_js_search.py -q   # requires Node
```

## GitHub Pages caveat

Free GitHub Pages needs a public repo. v1 mitigates the privacy hit:
- `robots.txt: Disallow: /`
- `<meta name="robots" content="noindex,nofollow">` on every page
- thumbnails-only in the deployed repo (full images stay local; v3 may push to R2)

If publicness still doesn't sit right, swap the deploy target to **Cloudflare
Pages** (private repo OK, free) — `dist/` is the same artifact.

## Layout

```
rednote-kb/
  src/rednote_kb/
    cli.py                  # Typer entry — all user-facing commands
    db/{schema.sql, dao.py} # SQLite source of truth
    scrape/
      xhs_client.py         # JSON-ingest path (vendor-agnostic schema)
      xhs_downloader.py     # XHS-Downloader programmatic adapter
    index/tokenize.py       # CJK-aware tokenizer (Python; mirror in search.js)
    site/
      build.py              # SQLite → posts.json + HTML
      templates/            # Jinja2 base / index / post
      static/               # style.css, search.js (client-side index + ranking)
      pwa/                  # manifest, sw.js, icon.svg (copied to dist root)
  systemd/                  # user-mode service + timer
  scripts/
    canary.py               # pre-build health check
    deploy.sh               # rsync dist/ → site repo → push
  tests/                    # unit + end-to-end + JS parity + JS search
  data/                     # rednote.db, health.json (gitignored)
  dist/                     # built site (gitignored)
```
