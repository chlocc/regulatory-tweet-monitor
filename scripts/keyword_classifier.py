"""
Keyword-based tweet classification — no API calls, no credits.
Used by default instead of Anthropic LLM classification.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

BASE = Path(__file__).resolve().parents[1]
TAXONOMY_PATH = BASE / "config" / "taxonomy.json"

# Maps taxonomy.json keys → dashboard category labels
TAXONOMY_TO_CATEGORY = {
    "stablecoin_genius": "stablecoins",
    "market_structure_fit21": "legislation",
    "defi_regs": "defi",
    "prediction_markets": "prediction_markets",
    "crypto_exchanges": "exchanges",
    "other": "other",
}

# Extra keyword rules not covered by taxonomy.json
EXTRA_RULES: Tuple[Tuple[str, str], ...] = (
    ("enforcement", "enforcement"),
    ("wells notice", "enforcement"),
    ("cease and desist", "enforcement"),
    ("enforcement action", "enforcement"),
    ("unregistered securities", "enforcement"),
    ("subpoena", "enforcement"),
    ("lawsuit", "enforcement"),
    ("settlement", "enforcement"),
    ("sec v ", "enforcement"),
    ("cftc", "enforcement"),
    ("congress", "legislation"),
    ("legislation", "legislation"),
    ("clarity act", "legislation"),
    ("genius act", "legislation"),
    ("fit21", "legislation"),
    ("market structure", "legislation"),
    ("mica", "legislation"),
)


def _load_taxonomy() -> Dict[str, list]:
    if not TAXONOMY_PATH.exists():
        return {}
    return json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))


def _make_summary(text: str, max_len: int = 150) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_len:
        return text
    cut = text[:max_len].rsplit(" ", 1)[0]
    return cut + "…" if cut else text[:max_len] + "…"


def classify_by_keywords(text: str) -> Dict[str, str]:
    """
    Classify a tweet using taxonomy + keyword rules.
    Always returns a result (caller already ran keyword pre-filter).
    """
    lower = text.lower()
    taxonomy = _load_taxonomy()

    # Score each taxonomy bucket by keyword hits
    best_category = "other"
    best_score = 0

    for tax_key, keywords in taxonomy.items():
        if tax_key == "other" or not keywords:
            continue
        score = sum(1 for kw in keywords if kw.lower() in lower)
        if score > best_score:
            best_score = score
            best_category = TAXONOMY_TO_CATEGORY.get(tax_key, "other")

    # Check extra rules (first match wins if no taxonomy hit)
    if best_score == 0:
        for keyword, category in EXTRA_RULES:
            if keyword in lower:
                best_category = category
                break

    return {
        "category": best_category,
        "summary": _make_summary(text),
    }
