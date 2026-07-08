"""
Tweet classification for regulatory monitor.
Defaults to free keyword classification; Anthropic LLM is opt-in only.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Dict, Optional

from keyword_classifier import classify_by_keywords


CRYPTO_KEYWORDS = [
    "crypto", "bitcoin", "btc", "ethereum", "ether", "eth", "blockchain",
    "defi", "stablecoin", "usdt", "usdc", "tether", "dai",
    "token", "coinbase", "binance", "kraken", "ripple", "xrp",
    "polymarket", "kalshi", "prediction market",
    "nft", "web3", "dao", "smart contract",
    "mining", "staking", "lend", "borrow",
    "sec crypto", "cftc crypto", "crypto enforcement",
    "digital asset", "virtual asset", "virtual currency",
    "crypto exchange", "crypto regulation", "crypto bill",
    "sab 121", "sab121", "form s-1", "spot bitcoin", "bitcoin etf",
    "crypto custody", "crypto trading",
]


def use_llm_classification() -> bool:
    """LLM is off by default to avoid API credit usage."""
    return os.environ.get("REG_MONITOR_USE_LLM", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def get_anthropic_api_key() -> str:
    """Support Starchild BYOK name and standard ANTHROPIC_API_KEY."""
    return (
        os.environ.get("CUSTOM_KEY_CLAUDE_SONNET_4_5_20250929_9724", "").strip()
        or os.environ.get("ANTHROPIC_API_KEY", "").strip()
    )


def classify_tweet(text: str, url: str) -> Optional[Dict]:
    """
    Classify a tweet. Uses keyword rules by default; LLM only if explicitly enabled.
    """
    if use_llm_classification() and get_anthropic_api_key():
        return call_anthropic_classify(text, url)
    return classify_by_keywords(text)


def has_crypto_signal(text: str) -> bool:
    """Quick keyword pre-filter. Returns True if text likely relates to crypto."""
    lower = text.lower()
    return any(kw in lower for kw in CRYPTO_KEYWORDS)


def extract_json(content: str) -> Optional[Dict]:
    """
    Robustly extract a JSON object from LLM response text.
    Handles: pure JSON, JSON with surrounding prose, code blocks, multi-line.
    """
    if not content:
        return None
    content = content.strip()

    if content.startswith("```"):
        lines = content.split("\n")
        inner = []
        in_block = False
        for line in lines:
            if line.strip().startswith("```"):
                if in_block:
                    break
                in_block = True
                continue
            if in_block:
                inner.append(line)
            elif not in_block and not line.strip().startswith("```"):
                inner.append(line)
        content = "\n".join(inner).strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    first_brace = content.find("{")
    last_brace = content.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidate = content[first_brace : last_brace + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            for line in candidate.split("\n"):
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    try:
                        return json.loads(line)
                    except json.JSONDecodeError:
                        continue

    return None


def call_anthropic_classify(text: str, url: str) -> Optional[Dict]:
    """
    Call Anthropic API to filter and classify tweets.
    Returns None if tweet is not crypto-regulatory, else dict with category and summary.
    """
    if not has_crypto_signal(text):
        return None

    api_key = get_anthropic_api_key()
    if not api_key:
        return None

    prompt = f"""You are filtering regulatory tweets for a crypto compliance monitor.

Tweet text:
{text}

Task:
1. Determine if this tweet is about cryptocurrency/blockchain regulation (exchanges, DeFi, stablecoins, prediction markets, enforcement actions, legislation).
2. If YES: classify into ONE category and write a 1-sentence summary (max 150 chars).
3. If NO (general politics, non-crypto regulation, personal commentary, unrelated topics): respond with "REJECT".

Categories:
- exchanges: Crypto exchange regulation, licenses, enforcement
- defi: DeFi protocol regulation, smart contracts, decentralized finance
- stablecoins: Stablecoin regulation, USDT/USDC/DAI policy, reserve requirements
- prediction_markets: Polymarket, Kalshi, prediction market regulation, betting markets
- enforcement: SEC/CFTC enforcement actions against crypto entities
- legislation: Congressional bills, regulatory frameworks for crypto
- other: Crypto-regulatory topics that don't fit above categories

CRITICAL: Your entire response must be ONLY valid JSON on a single line. No explanations before or after. No code blocks. No extra text.

Return exactly:
{{"action": "ACCEPT", "category": "...", "summary": "..."}}
OR
{{"action": "REJECT"}}

If REJECT, omit category and summary fields."""

    body = json.dumps({
        "model": "claude-sonnet-4-5-20250929",
        "max_tokens": 200,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content_text = ""
            if isinstance(data.get("content"), list) and data["content"]:
                content_text = data["content"][0].get("text", "")

            if not content_text:
                print("LLM returned empty content for tweet", file=sys.stderr)
                return None

            result = extract_json(content_text)
            if result is None:
                print(f"LLM JSON parse failed, content: {content_text[:200]}", file=sys.stderr)
                return None

            if result.get("action") == "REJECT":
                return None

            category = result.get("category", "other")
            summary = result.get("summary", text[:150])

            return {"category": category, "summary": summary}
    except Exception as e:
        print(f"LLM classification failed for tweet: {e}", file=sys.stderr)
        return None
