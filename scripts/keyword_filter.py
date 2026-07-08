#!/usr/bin/env python3
"""
Keyword pre-filter for crypto regulatory tweets.
Runs BEFORE expensive LLM classification to eliminate obvious non-crypto content.
"""
import re
from typing import Optional

# Tier A + B: Accounts that bypass keyword filter entirely (always sent to LLM)
BYPASS_ACCOUNTS = {
    # Tier A — Dedicated crypto officials
    "ChairmanSelig",    # CFTC Chair
    "HesterPeirce",     # SEC Crypto Mom
    "BoHines",          # Digital-assets policy council
    "SenLummis",        # Crypto legislator

    # Tier B — High-value crypto-focused
    "davidsacks47",     # WH AI & Crypto Czar
    "RepFrenchHill",    # House crypto market-structure
    "EleanorTerrett",   # Crypto-dedicated reporter
}

# Core crypto keywords (case-insensitive substring matching)
CRYPTO_KEYWORDS = [
    # Core terms
    "bitcoin", "btc", "ethereum", "eth", "crypto", "cryptocurrency", "cryptocurrencies",
    "blockchain", "digital asset", "digital assets", "virtual currency", "virtual currencies",
    "digital currency", "web3", "token", "tokens", "tokenization", "tokenize",

    # Exchanges & platforms
    "coinbase", "binance", "kraken", "gemini", "bitstamp", "bitfinex", "ftx", "poloniex",
    "crypto.com", "kucoin", "bybit", "okx", "bittrex", "huobi", "gate.io",
    "exchange", "trading platform", "crypto exchange", "digital asset exchange",
    "dex", "cex",

    # DeFi
    "defi", "decentralized finance", "uniswap", "aave", "compound", "curve", "makerdao",
    "sushiswap", "pancakeswap", "balancer", "yearn", "convex", "lido", "rocket pool",
    "liquidity pool", "amm", "automated market maker", "yield farming", "liquidity mining",
    "smart contract", "smart contracts", "restaking", "eigenlayer",

    # Stablecoins
    "stablecoin", "stablecoins", "stable coin", "usdt", "usdc", "dai", "busd", "tusd",
    "tether", "circle", "paxos", "frax", "algorithmic stablecoin", "reserve requirement",
    "dollar-backed",

    # Prediction markets
    "polymarket", "kalshi", "augur", "gnosis", "prediction market", "prediction markets",
    "forecast market", "betting market", "event contract", "event contracts",
    "information market", "futarchy",

    # Enforcement & regulators
    "sec", "cftc", "finra", "occ", "treasury", "fincen", "doj", "justice department",
    "enforcement", "enforcement action", "wells notice", "cease and desist",
    "unregistered securities", "unregistered exchange", "securities violation",
    "howey test", "investment contract", "digital asset lawsuit", "crypto settlement",
    "crypto fraud", "subpoena",

    # Legislation
    "fit21", "dccpa", "genius act", "clarity act", "market structure bill",
    "stablecoin bill", "crypto legislation", "digital asset framework",

    # NFTs & DAOs
    "nft", "nfts", "non-fungible token", "dao", "daos",
    "decentralized autonomous organization", "opensea", "blur", "governance token", "duna",

    # Emerging tech
    "rwa", "real-world asset", "real world asset", "tokenized asset", "tokenized securities",
    "layer 2", "l2", "rollup", "rollups", "account abstraction", "intent", "intents",
    "mev", "maximal extractable value", "lrt",

    # Protocols under scrutiny
    "ripple", "xrp", "solana", "sol", "cardano", "ada", "binance coin", "bnb",
    "tornado cash", "mixer", "privacy coin", "monero",

    # Regulatory jargon
    "kyc", "aml", "bsa", "bank secrecy act", "travel rule", "fatf", "mica", "tfr",

    # Custody & infrastructure
    "custody", "custodian", "qualified custodian", "validator", "staking",
    "staking service", "node operator", "wallet provider", "cold storage", "fireblocks",
]

_KEYWORD_PATTERNS = [re.compile(re.escape(kw), re.IGNORECASE) for kw in CRYPTO_KEYWORDS]


def should_send_to_llm(text: str, username: str) -> tuple[bool, str]:
    """
    Determine if a tweet should be sent to LLM for classification.

    Returns:
        (should_send: bool, reason: str)
    """
    if username in BYPASS_ACCOUNTS:
        return True, f"bypass_account:{username}"

    for pattern in _KEYWORD_PATTERNS:
        if pattern.search(text):
            return True, f"keyword_match:{pattern.pattern}"

    return False, "no_crypto_keywords"


def get_filter_stats() -> dict:
    """Return filter configuration for debugging."""
    return {
        "bypass_accounts": sorted(BYPASS_ACCOUNTS),
        "bypass_count": len(BYPASS_ACCOUNTS),
        "keywords_count": len(CRYPTO_KEYWORDS),
        "keywords": sorted(CRYPTO_KEYWORDS),
    }
