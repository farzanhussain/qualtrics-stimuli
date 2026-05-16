#!/usr/bin/env bash
# Sync ./dist into the separate public site repo and push to GitHub Pages.
# Run AFTER `rednote-kb build`. Idempotent; commits only if anything changed.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

# shellcheck disable=SC1091
[ -f .env ] && source .env

DIST_DIR="${DIST_DIR:-./dist}"
SITE_REPO_DIR="${SITE_REPO_DIR:-../rednote-kb-site}"

if [ ! -d "$DIST_DIR" ]; then
  echo "no built site at $DIST_DIR — run 'rednote-kb build' first" >&2
  exit 1
fi
if [ ! -d "$SITE_REPO_DIR/.git" ]; then
  echo "$SITE_REPO_DIR is not a git checkout" >&2
  echo "create the public site repo on GitHub, then:" >&2
  echo "  git clone git@github.com:<you>/rednote-kb-site.git $SITE_REPO_DIR" >&2
  exit 1
fi

# Mirror dist/ into the site repo, deleting stale files, but keep .git intact.
rsync -a --delete --exclude=.git/ "$DIST_DIR"/ "$SITE_REPO_DIR"/

cd "$SITE_REPO_DIR"
git add -A
if git diff --cached --quiet; then
  echo "no changes to deploy"
  exit 0
fi
STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
git commit -m "build: $STAMP"
git push origin HEAD
echo "deployed @ $STAMP"
