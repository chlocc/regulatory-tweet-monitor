#!/usr/bin/env python3
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone, time as dtime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from http_client import proxied_get
from keyword_filter import should_send_to_llm
from llm_filter import classify_tweet

BASE = Path(__file__).resolve().parents[1]
CONFIG = BASE / "config"
STATE = BASE / "state"
SITE_DATA = BASE / "site" / "data"

ACCOUNTS_PATH = CONFIG / "accounts.json"
TAXONOMY_PATH = CONFIG / "taxonomy.json"
SEEN_PATH = STATE / "seen_ids.json"
STORE_PATH = STATE / "tweet_store.json"
PROGRESS_PATH = STATE / "crawl_progress.json"
TWEETS_OUT = SITE_DATA / "tweets.json"
DIGEST_OUT = SITE_DATA / "morning_digest.md"
LAST_RUN_OUT = STATE / "last_run.json"
REJECTED_TWEETS_LOG = STATE / "rejected_tweets.jsonl"

API_URL_TMPL = "https://scrapebadger.com/v1/twitter/users/{username}/latest_tweets"


class RateLimitError(Exception):
    def __init__(self, message: str, reset_at: Optional[int] = None):
        super().__init__(message)
        self.reset_at = reset_at


def read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def flatten_accounts(accounts_cfg: Dict) -> Tuple[List[str], Dict[str, str]]:
    handles: List[str] = []
    handle_group: Dict[str, str] = {}
    groups = accounts_cfg.get("groups", {})
    for group, arr in groups.items():
        for h in arr:
            h2 = h.replace("@", "").strip()
            if not h2:
                continue
            if h2 not in handle_group:
                handle_group[h2] = group
                handles.append(h2)
    return handles, handle_group


def parse_created_at(raw: str) -> datetime:
    if not raw:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)

    s = str(raw).strip()

    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


def normalize_text(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()


def tweet_type(t: Dict) -> str:
    if t.get("is_retweet"):
        return "retweet"
    if t.get("in_reply_to_status_id"):
        return "reply"
    if t.get("is_quote_status"):
        return "quote"
    return "original"


def parse_rate_limit(resp_text: str) -> Tuple[str, Optional[int]]:
    try:
        obj = json.loads(resp_text)
        msg = obj.get("detail") or obj.get("error") or "Rate limit exceeded"
        reset_at = obj.get("reset_at")
        if isinstance(reset_at, str) and reset_at.isdigit():
            reset_at = int(reset_at)
        if not isinstance(reset_at, int):
            reset_at = None
        return str(msg), reset_at
    except Exception:
        return "Rate limit exceeded", None


def fetch_user_tweets(
    username: str,
    api_key: str,
    caller_id: str,
    pages_per_user: int,
) -> List[Dict]:
    out: List[Dict] = []
    cursor = None
    pages = 0

    while True:
        params = {}
        if cursor:
            params["cursor"] = cursor

        resp = proxied_get(
            API_URL_TMPL.format(username=username),
            params=params,
            headers={
                "x-api-key": api_key,
                "SC-CALLER-ID": caller_id,
            },
            timeout=30,
        )

        if resp.status_code == 429:
            msg, reset_at = parse_rate_limit(resp.text)
            raise RateLimitError(f"{username}: HTTP 429 - {msg}", reset_at=reset_at)

        if resp.status_code != 200:
            raise RuntimeError(f"{username}: HTTP {resp.status_code} - {resp.text[:250]}")

        body = resp.json()
        data = body.get("data") or []
        out.extend(data)

        cursor = body.get("next_cursor")
        pages += 1
        if not cursor or pages >= pages_per_user:
            break

    return out


def build_row(t: Dict, fallback_username: str, group: str, rejected_log_file) -> Optional[Dict]:
    """Build row with keyword pre-filter + LLM filtering and classification."""
    tid = str(t.get("id", "")).strip()
    if not tid:
        return None

    text = normalize_text(t.get("full_text") or t.get("text") or "")
    if not text:
        return None

    created_at = parse_created_at(t.get("created_at", ""))
    username = t.get("username") or fallback_username
    url = f"https://x.com/{username}/status/{tid}"

    should_process, filter_reason = should_send_to_llm(text, username)

    if not should_process:
        rejected_entry = {
            "id": tid,
            "username": username,
            "created_at": created_at.isoformat(),
            "text": text,
            "url": url,
            "reject_reason": filter_reason,
            "logged_at": datetime.now(timezone.utc).isoformat(),
        }
        rejected_log_file.write(json.dumps(rejected_entry, ensure_ascii=False) + "\n")
        return None

    class_result = classify_tweet(text, url)
    if class_result is None:
        return None

    category = class_result["category"]
    summary = class_result["summary"]

    is_retweet = text.strip().startswith("RT @")
    original_author = None
    if is_retweet:
        rt_match = re.match(r"^RT @(\w+):", text)
        if rt_match:
            original_author = rt_match.group(1)

    return {
        "id": tid,
        "is_retweet": is_retweet,
        "original_author": original_author,
        "username": username,
        "display_name": t.get("user_name") or username,
        "group": group,
        "created_at": created_at.isoformat(),
        "text": text,
        "summary": summary,
        "url": url,
        "type": tweet_type(t),
        "categories": [category],
        "relevance": 0.85,
        "confidence": 0.90,
        "metrics": {
            "likes": t.get("favorite_count", 0),
            "retweets": t.get("retweet_count", 0),
            "replies": t.get("reply_count", 0),
            "quotes": t.get("quote_count", 0),
            "views": t.get("view_count"),
        },
    }


def compute_cutoff(now: datetime, mode: str, hours: int) -> datetime:
    if mode == "et_noon_rolling_24h":
        try:
            import zoneinfo

            et_tz = zoneinfo.ZoneInfo("America/New_York")
        except ImportError:
            return now - timedelta(hours=hours)

        now_et = now.astimezone(et_tz)
        noon_et_today = now_et.replace(hour=12, minute=0, second=0, microsecond=0)
        cutoff_et = noon_et_today - timedelta(hours=24)
        return cutoff_et.astimezone(timezone.utc)

    if mode == "prev_day_2359_utc":
        prev_day = (now - timedelta(days=1)).date()
        return datetime.combine(prev_day, dtime(23, 59), tzinfo=timezone.utc)

    return now - timedelta(hours=hours)


def main():
    now = datetime.now(timezone.utc)
    now_ts = int(time.time())

    api_key = os.environ.get("SCRAPEBADGER_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Missing SCRAPEBADGER_API_KEY")

    window_mode = os.environ.get("REG_MONITOR_WINDOW_MODE", "et_noon_rolling_24h").strip()
    since_hours = int(os.environ.get("REG_MONITOR_SINCE_HOURS", "24"))
    cutoff_new = compute_cutoff(now, window_mode, since_hours)

    site_window_hours = int(os.environ.get("REG_MONITOR_SITE_WINDOW_HOURS", "24"))
    cutoff_site = compute_cutoff(now, window_mode, site_window_hours)

    max_accounts_per_run = max(1, int(os.environ.get("REG_MONITOR_MAX_ACCOUNTS_PER_RUN", "4")))
    pages_per_user = max(1, int(os.environ.get("REG_MONITOR_PAGES_PER_USER", "1")))
    caller_id = os.environ.get("SC_CALLER_ID", "job:reg-monitor")

    priority_filter = os.environ.get("REG_MONITOR_PRIORITY_HANDLES", "").strip()
    priority_set = set()
    if priority_filter:
        priority_set = {h.strip() for h in priority_filter.split(",") if h.strip()}

    accounts_cfg = read_json(ACCOUNTS_PATH, {"groups": {}})
    handles, handle_group = flatten_accounts(accounts_cfg)
    total_accounts = len(handles)

    if priority_set:
        handles = [h for h in handles if h in priority_set]

    if not handles:
        print("No accounts to crawl")
        return

    progress = read_json(PROGRESS_PATH, {"next_index": 0, "cooldown_until": 0})
    cooldown_until = progress.get("cooldown_until", 0)

    if now_ts < cooldown_until:
        remaining = cooldown_until - now_ts
        print(f"Rate limit cooldown active, {remaining}s remaining")
        write_json(
            LAST_RUN_OUT,
            {
                "ran_at": now.isoformat(),
                "new_tweets_this_run": 0,
                "site_recent_rows": 0,
                "accounts_total": total_accounts,
                "attempted": 0,
                "success_accounts": 0,
                "errors": 0,
                "rate_limited": True,
            },
        )
        return

    store = read_json(STORE_PATH, [])
    seen_ids = {t["id"] for t in store if isinstance(t, dict) and "id" in t}

    new_tweets_this_run = []
    errors = []
    rate_limit_info = {"active": False}

    start_idx = progress.get("next_index", 0) % len(handles)
    idx = start_idx
    attempted = 0
    success_count = 0

    rejected_log_file = open(REJECTED_TWEETS_LOG, "a", encoding="utf-8")

    try:
        for _ in range(min(max_accounts_per_run, len(handles))):
            h = handles[idx]
            group = handle_group.get(h, "Other")

            try:
                tweets = fetch_user_tweets(h, api_key, caller_id, pages_per_user)
                success_count += 1
                attempted += 1

                for tw in tweets:
                    row = build_row(tw, h, group, rejected_log_file)
                    if not row:
                        continue

                    tid = row["id"]
                    if tid in seen_ids:
                        continue

                    created_at = parse_created_at(row["created_at"])
                    store.append(row)
                    seen_ids.add(tid)

                    if created_at >= cutoff_new:
                        new_tweets_this_run.append(row)

                idx = (idx + 1) % len(handles)
                progress["next_index"] = idx
                time.sleep(2)

            except RateLimitError as e:
                reset_at = e.reset_at or (now_ts + 180)
                progress["cooldown_until"] = int(reset_at)
                progress["last_rate_limit"] = {
                    "at": now.isoformat(),
                    "username": h,
                    "reset_at": int(reset_at),
                    "error": str(e),
                }
                rate_limit_info = {
                    "active": True,
                    "until_unix": int(reset_at),
                    "seconds_left": max(0, int(reset_at) - now_ts),
                    "message": str(e),
                }
                progress["next_index"] = idx
                break
            except Exception as e:
                errors.append({"username": h, "error": str(e)})
                idx = (idx + 1) % len(handles)
                progress["next_index"] = idx
                continue

    finally:
        rejected_log_file.close()

    progress["last_run_at"] = now.isoformat()
    write_json(PROGRESS_PATH, progress)
    write_json(STORE_PATH, store)

    site_rows = [t for t in store if parse_created_at(t.get("created_at", "")) >= cutoff_site]
    site_rows_sorted = sorted(site_rows, key=lambda x: x.get("created_at", ""), reverse=True)

    site_payload = {
        "generated_at": now.isoformat(),
        "generated_at_unix": now_ts,
        "time_window_hours": int(site_window_hours),
        "window_mode": window_mode,
        "window_start": cutoff_site.isoformat(),
        "window_end": now.isoformat(),
        "new_this_run": len(new_tweets_this_run),
        "total_recent": len(site_rows_sorted),
        "errors": errors,
        "crawl": {
            "total_accounts": total_accounts,
            "attempted_this_run": attempted,
            "successful_this_run": success_count,
            "next_index": progress.get("next_index", 0),
            "max_accounts_per_run": max_accounts_per_run,
            "cooldown_until": progress.get("cooldown_until", 0),
        },
        "rate_limit": rate_limit_info,
        "tweets": site_rows_sorted,
    }
    write_json(TWEETS_OUT, site_payload)

    write_json(
        LAST_RUN_OUT,
        {
            "ran_at": now.isoformat(),
            "new_tweets_this_run": len(new_tweets_this_run),
            "site_recent_rows": len(site_rows_sorted),
            "accounts_total": total_accounts,
            "attempted": attempted,
            "success_accounts": success_count,
            "errors": len(errors),
            "rate_limited": rate_limit_info.get("active", False),
        },
    )

    print(
        f"Recent rows: {len(site_rows_sorted)} | new this run: {len(new_tweets_this_run)} "
        f"| attempted: {attempted}/{total_accounts}"
    )
    if rate_limit_info.get("active"):
        print(f"Rate limit cooldown active, {rate_limit_info['seconds_left']}s remaining")


if __name__ == "__main__":
    main()
