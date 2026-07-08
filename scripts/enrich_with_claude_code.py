#!/usr/bin/env python3
"""
Batch-enrich tweets using Claude Code CLI (subscription billing, not API key).

Run after a crawl when you want Starchild-quality summaries:
    ./scripts/enrich_with_claude_code.sh

Or auto-run after each crawl:
    REG_MONITOR_ENRICH_AFTER_CRAWL=true ./run_crawl.sh 0
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE = Path(__file__).resolve().parents[1]
TWEETS_PATH = BASE / "site" / "data" / "tweets.json"
STORE_PATH = BASE / "state" / "tweet_store.json"
REJECTED_LOG = BASE / "state" / "rejected_tweets.jsonl"

CATEGORIES = [
    "exchanges",
    "defi",
    "stablecoins",
    "prediction_markets",
    "enforcement",
    "legislation",
    "other",
]

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "tweets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "action": {"type": "string", "enum": ["ACCEPT", "REJECT"]},
                    "category": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": ["id", "action"],
            },
        }
    },
    "required": ["tweets"],
}


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def needs_enrichment(tweet: Dict, force: bool) -> bool:
    if force:
        return True
    return tweet.get("enriched_by") != "claude_code"


def build_prompt(batch: List[Dict]) -> str:
    items = [
        {
            "id": t["id"],
            "username": t.get("username", ""),
            "group": t.get("group", ""),
            "text": t.get("text", ""),
        }
        for t in batch
    ]
    return f"""You are enriching tweets for a crypto regulatory compliance monitor.

For EACH tweet below:
1. ACCEPT if it is about cryptocurrency/blockchain regulation, enforcement, legislation, exchanges, DeFi, stablecoins, or prediction markets.
2. On ACCEPT: assign exactly ONE category and write a 1-sentence regulatory summary (max 150 chars).
3. REJECT general politics, personal commentary, promos, or non-crypto topics.

Categories: {", ".join(CATEGORIES)}

Input tweets:
{json.dumps(items, ensure_ascii=False, indent=2)}

Return ONLY JSON with one result per input tweet (same ids, same order):
{{"tweets": [{{"id": "...", "action": "ACCEPT", "category": "...", "summary": "..."}}, {{"id": "...", "action": "REJECT"}}]}}"""


def call_claude_batch(batch: List[Dict], dry_run: bool) -> List[Dict]:
    if dry_run:
        return [
            {
                "id": t["id"],
                "action": "ACCEPT",
                "category": t.get("categories", ["other"])[0] if t.get("categories") else "other",
                "summary": (t.get("text", "")[:147] + "…") if len(t.get("text", "")) > 150 else t.get("text", ""),
            }
            for t in batch
        ]

    prompt = build_prompt(batch)
    proc = subprocess.run(
        [
            "claude",
            "-p",
            prompt,
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(RESPONSE_SCHEMA),
        ],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(BASE),
        stdin=subprocess.DEVNULL,
    )

    if proc.returncode != 0:
        raise RuntimeError(
            f"claude CLI failed (exit {proc.returncode}):\n{proc.stderr[-800:]}"
        )

    outer = json.loads(proc.stdout)
    if outer.get("is_error"):
        raise RuntimeError(f"claude CLI error: {outer}")

    result_text = outer.get("result", "")
    if not result_text:
        raise RuntimeError(f"claude CLI returned empty result: {outer}")

    inner = json.loads(result_text)
    return inner.get("tweets", [])


def apply_results(
    tweets_by_id: Dict[str, Dict],
    results: List[Dict],
    rejected_ids: List[str],
) -> int:
    updated = 0
    for item in results:
        tid = str(item.get("id", "")).strip()
        if not tid or tid not in tweets_by_id:
            continue

        if item.get("action") == "REJECT":
            rejected_ids.append(tid)
            continue

        tweet = tweets_by_id[tid]
        category = item.get("category") or "other"
        summary = item.get("summary") or tweet.get("text", "")[:150]

        tweet["categories"] = [category]
        tweet["summary"] = summary
        tweet["enriched_by"] = "claude_code"
        updated += 1

    return updated


def log_rejected(tweets_by_id: Dict[str, Dict], rejected_ids: List[str]) -> None:
    if not rejected_ids:
        return

    REJECTED_LOG.parent.mkdir(parents=True, exist_ok=True)
    with REJECTED_LOG.open("a", encoding="utf-8") as f:
        for tid in rejected_ids:
            t = tweets_by_id.get(tid, {})
            entry = {
                "id": tid,
                "username": t.get("username"),
                "text": t.get("text"),
                "url": t.get("url"),
                "reject_reason": "claude_code_reject",
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Enrich tweets via Claude Code CLI")
    parser.add_argument("--batch-size", type=int, default=5, help="Tweets per Claude call")
    parser.add_argument("--force", action="store_true", help="Re-enrich already enriched tweets")
    parser.add_argument("--dry-run", action="store_true", help="Skip Claude calls; simulate updates")
    parser.add_argument("--limit", type=int, default=0, help="Max tweets to enrich (0 = all pending)")
    args = parser.parse_args()

    payload = read_json(TWEETS_PATH, {})
    tweets: List[Dict] = payload.get("tweets", [])
    if not tweets:
        print("No tweets in site/data/tweets.json")
        return 0

    pending = [t for t in tweets if needs_enrichment(t, args.force)]
    if args.limit > 0:
        pending = pending[: args.limit]

    if not pending:
        print("All tweets already enriched by Claude Code (use --force to redo)")
        return 0

    print(f"Enriching {len(pending)} tweet(s) in batches of {args.batch_size}...")
    if args.dry_run:
        print("(dry-run mode — no Claude calls)")

    tweets_by_id = {t["id"]: t for t in tweets if t.get("id")}
    store = read_json(STORE_PATH, [])
    store_by_id = {t["id"]: t for t in store if isinstance(t, dict) and t.get("id")}

    rejected_ids: List[str] = []
    total_updated = 0

    for i in range(0, len(pending), args.batch_size):
        batch = pending[i : i + args.batch_size]
        batch_num = i // args.batch_size + 1
        total_batches = (len(pending) + args.batch_size - 1) // args.batch_size
        print(f"  Batch {batch_num}/{total_batches} ({len(batch)} tweets)...")

        try:
            results = call_claude_batch(batch, args.dry_run)
        except Exception as exc:
            print(f"  Failed: {exc}", file=sys.stderr)
            return 1

        total_updated += apply_results(tweets_by_id, results, rejected_ids)

    if rejected_ids:
        payload["tweets"] = [t for t in tweets if t.get("id") not in rejected_ids]
        for tid in rejected_ids:
            store_by_id.pop(tid, None)
        log_rejected(tweets_by_id, rejected_ids)
        print(f"  Rejected {len(rejected_ids)} non-regulatory tweet(s)")

    write_json(TWEETS_PATH, payload)
    write_json(STORE_PATH, list(store_by_id.values()))

    print(f"Done — enriched {total_updated} tweet(s).")
    print(f"  Dashboard data: {TWEETS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
