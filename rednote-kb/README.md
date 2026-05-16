# rednote-kb

Personal, static knowledge base over RedNote (Xiaohongshu / 小红书). v0 builds
a phone-friendly static site from pre-scraped post JSON and ships it to
GitHub Pages — no always-on server, no recurring cost.

See `../../.claude/plans/my-girlfriend-wants-to-goofy-backus.md` (Claude
plan file) for the full architecture and phased roadmap.

## What v0 ships

- SQLite store of posts + authors (`data/rednote.db`)
- A CLI: `init-db`, `ingest-json`, `add-creator`, `add-query`, `build`, `stats`
- A static site: search box (client-side substring match over `posts.json`)
  + one HTML page per post
- A deploy script that pushes the built site to a separate GitHub Pages repo

What it does **not** do yet: live scraping (you run XHS-Downloader yourself),
OCR, image thumbnails, semantic search, chat. See plan for v1–v4.

## Setup

```bash
cd rednote-kb
uv sync                    # or: python -m venv .venv && .venv/bin/pip install -e .
cp .env.example .env       # fill in XHS_COOKIE and SITE_REPO_DIR
uv run rednote-kb init-db
```

## Daily flow

Until v1 wires creator-feed sync into the timer, the loop is manual:

1. **Scrape with XHS-Downloader** on your laptop, with your cookies:

   ```bash
   # See https://github.com/JoeanAmier/XHS-Downloader
   XHS-Downloader --url <post-url-or-author-url>
   ```

2. **Normalise its output** to the schema in `src/rednote_kb/scrape/xhs_client.py`
   (write a tiny adapter once — the upstream tool's format changes).
   Drop the normalised `.json` files into a directory, then:

   ```bash
   uv run rednote-kb ingest-json ./scraped/ --source creator
   ```

3. **Mark followed creators / record seed queries** (v1 will use these to
   refresh automatically):

   ```bash
   uv run rednote-kb add-creator <author_id> --nickname "..." --handle "..."
   uv run rednote-kb add-query "上海 brunch 推荐"
   ```

4. **Build and deploy**:

   ```bash
   uv run rednote-kb build
   ./scripts/deploy.sh
   ```

   The site appears at `https://<you>.github.io/rednote-kb-site/`.

## Try it locally without scraping

```bash
uv run rednote-kb dev-fixture
uv run rednote-kb build
python -m http.server -d dist 8000
# open http://localhost:8000
```

## Tests

```bash
uv run pytest -q
```

## GitHub Pages caveat

Free-tier GitHub Pages requires a **public** repo. The deployed site
therefore contains thumbnails + extracted text only (full images stay on
your laptop), the deploy adds `robots.txt: Disallow: /`, and post pages
carry `<meta name="robots" content="noindex,nofollow">`. If publicness
becomes uncomfortable, switch the deploy target to Cloudflare Pages
(private repo OK, also free) — same `dist/` artifact.
