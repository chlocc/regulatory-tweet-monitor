"""
Preset B — Full sweep: crawl all 76 accounts.
Legacy wrapper; live cron uses fetch_and_classify.py in 5 batches/day.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT / "scripts" / "fetch_and_classify.py"
STATE_DIR = PROJECT / "state"


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    env = os.environ.copy()
    env.update({
        "REG_MONITOR_MAX_ACCOUNTS_PER_RUN": "76",
        "REG_MONITOR_PAGES_PER_USER": "1",
        "SC_CALLER_ID": "job:reg-monitor-sweep",
    })

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(PROJECT),
        timeout=900,
    )

    try:
        last = json.loads((STATE_DIR / "last_run.json").read_text())
        new_tweets = last.get("new_tweets_this_run", 0)
        attempted = last.get("attempted", 0)
        total = last.get("accounts_total", 76)
        rate_limited = last.get("rate_limited", False)
    except Exception:
        new_tweets = -1
        attempted = 0
        total = 76
        rate_limited = False

    print(
        f"Sweep ({now}): {new_tweets} new tweets across {attempted}/{total} accounts"
        + (" (rate-limited)" if rate_limited else "")
    )
    if result.returncode != 0:
        print(result.stderr[-500:], file=sys.stderr)
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
