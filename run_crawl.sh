#!/usr/bin/env bash
# Run one crawl batch. Usage: ./run_crawl.sh [next_index]
set -euo pipefail
cd "$(dirname "$0")"

NEXT_INDEX="${1:-0}"
echo "{\"next_index\": ${NEXT_INDEX}, \"cooldown_until\": 0}" > state/crawl_progress.json

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export REG_MONITOR_MAX_ACCOUNTS_PER_RUN="${REG_MONITOR_MAX_ACCOUNTS_PER_RUN:-15}"
python3 scripts/fetch_and_classify.py

if [ "${REG_MONITOR_ENRICH_AFTER_CRAWL:-false}" = "true" ]; then
  echo "Running Claude Code enrichment..."
  ./scripts/enrich_with_claude_code.sh
fi
