#!/usr/bin/env bash
# Enrich tweet summaries via Claude Code CLI (subscription, not API key).
# Usage: ./scripts/enrich_with_claude_code.sh [--force] [--dry-run] [--limit N]
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v claude >/dev/null 2>&1; then
  echo "Error: Claude Code CLI not found. Install from https://docs.anthropic.com/en/docs/claude-code" >&2
  exit 1
fi

python3 scripts/enrich_with_claude_code.py "$@"
