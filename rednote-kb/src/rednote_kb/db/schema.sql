-- RedNote KB schema. Build-side source of truth (local SQLite on the laptop).
-- v0: core tables only. v1 adds posts_fts (FTS5). v2 adds OCR. v4 adds posts_vec.

CREATE TABLE IF NOT EXISTS authors (
  id            TEXT PRIMARY KEY,
  handle        TEXT,
  nickname      TEXT,
  followed      INTEGER NOT NULL DEFAULT 0,
  last_crawled  TEXT
);

CREATE TABLE IF NOT EXISTS posts (
  id            TEXT PRIMARY KEY,           -- xhs note id
  url           TEXT NOT NULL,
  author_id     TEXT REFERENCES authors(id),
  title         TEXT,
  body          TEXT,
  ocr_text      TEXT,                       -- filled in v2
  tags          TEXT,                       -- JSON array as text
  like_count    INTEGER,
  collect_count INTEGER,
  published_at  TEXT,
  fetched_at    TEXT NOT NULL,
  source        TEXT,                       -- 'creator' | 'seed_query' | 'manual'
  deleted       INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_posts_author  ON posts(author_id);
CREATE INDEX IF NOT EXISTS idx_posts_fetched ON posts(fetched_at);

CREATE TABLE IF NOT EXISTS images (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id     TEXT NOT NULL REFERENCES posts(id),
  thumb_path  TEXT,                         -- pushed to site
  full_path   TEXT,                         -- local only (or R2 key)
  sha256      TEXT UNIQUE,                  -- dedup
  ocr_done    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_images_post ON images(post_id);

CREATE TABLE IF NOT EXISTS seed_queries (
  q             TEXT PRIMARY KEY,
  last_run      TEXT,
  result_count  INTEGER
);
