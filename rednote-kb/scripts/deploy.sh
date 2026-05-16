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
  cat >&2 <<EOM
$SITE_REPO_DIR is not a git checkout.

If you haven't cloned the site repo yet:
  git clone git@github.com:<you>/rednote-kb-site.git "$SITE_REPO_DIR"

If the GitHub repo is empty (no commits / no default branch), cloning will
warn "You appear to have cloned an empty repository" — that's fine. After
the first push from this script the 'main' branch is created on the remote;
then go to repo Settings → Pages and set source = main / (root).
EOM
  exit 1
fi

# A fresh-cloned-empty-repo has no HEAD until the first commit. Set the local
# default branch to 'main' so `git push origin HEAD` creates it remotely.
if ! git -C "$SITE_REPO_DIR" rev-parse --verify HEAD >/dev/null 2>&1; then
  git -C "$SITE_REPO_DIR" symbolic-ref HEAD refs/heads/main
fi

# Mirror dist/ into the site repo, deleting stale files.
# Excludes (preserved in the site repo across builds):
#   - .git/         : keep the repo itself
#   - .github/      : Actions workflows live in the site repo, not in dist/
#   - CNAME         : custom-domain config; deleting it un-configures the domain
#   - README.md     : the site repo may have its own root README distinct from dist/
# .nojekyll is produced by `rednote-kb build` and always pushed.
rsync -a --delete \
  --exclude=.git/ \
  --exclude=.github/ \
  --exclude=CNAME \
  --exclude=README.md \
  "$DIST_DIR"/ "$SITE_REPO_DIR"/

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
