"""
Preset B — Priority refresh: crawl top-10 most active accounts every 6h.
Legacy wrapper; live cron uses fetch_and_classify.py directly.
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

TOP10 = [
    "laurashin",
    "HaileyLennonBTC",
    "EleanorTerrett",
    "lex_node",
    "theblockprof",
    "BlockchainAssn",
    "prestonjbyrne",
    "iampaulgrewal",
    "RebeccaRettig1",
    "standwithcrypto",
]


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    env = os.environ.copy()
    env.update({
        "REG_MONITOR_MAX_ACCOUNTS_PER_RUN": "10",
        "REG_MONITOR_PAGES_PER_USER": "1",
        "REG_MONITOR_PRIORITY_HANDLES": ",".join(TOP10),
        "SC_CALLER_ID": "job:reg-monitor-priority",
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
    except Exception:
        new_tweets = -1

    print(f"Priority refresh ({now}): {new_tweets} new tweets")
    if result.returncode != 0:
        print(result.stderr[-500:], file=sys.stderr)
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
