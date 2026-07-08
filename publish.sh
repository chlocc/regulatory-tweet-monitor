#!/usr/bin/env bash
# Publish latest site/ to GitHub Pages (push triggers deploy workflow).
set -euo pipefail
cd "$(dirname "$0")"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "Run from a git repo. First-time setup:"
  echo "  git init && git add . && git commit -m 'Initial commit'"
  echo "  gh repo create regulatory-tweet-monitor --public --source=. --push"
  exit 1
fi

git add site/data/tweets.json site/index.html
git diff --staged --quiet || git commit -m "Update regulatory tweet feed"
git push origin main
echo "Pushed — GitHub Actions will deploy site/ to Pages."
