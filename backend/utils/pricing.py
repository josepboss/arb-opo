"""
Unit pricing engine — parses quantities from listing titles
and computes a standardized unit price.
"""

import re
from typing import Optional


# Regex patterns to extract quantity + unit from listing titles
# Examples: "10k Gold", "100k", "1m", "1 million", "5000", "10000 Gold"
QUANTITY_PATTERNS = [
    # "1.5k", "10k", "100k" (k = thousands)
    re.compile(r"(\d+(?:\.\d+)?)\s*k\b", re.IGNORECASE),
    # "1m", "10m" (m = millions)
    re.compile(r"(\d+(?:\.\d+)?)\s*m\b", re.IGNORECASE),
    # "1 million", "10 million"
    re.compile(r"(\d+(?:\.\d+)?)\s*million", re.IGNORECASE),
    # "1 thousand", "10 thousand"
    re.compile(r"(\d+(?:\.\d+)?)\s*thousand", re.IGNORECASE),
    # Plain number at start or after common prefixes
    re.compile(r"(?:x|quantity|qty|amount)[:\s]*(\d{2,})", re.IGNORECASE),
    # Bare number at the start of the title (only if >= 10)
    re.compile(r"^(\d{2,})\b"),
]


def parse_quantity(title: str) -> Optional[float]:
    """
    Extract numeric quantity from a listing title.

    Returns the quantity as a float, or None if no quantity detected.
    """
    for pattern in QUANTITY_PATTERNS:
        match = pattern.search(title)
        if match:
            num = float(match.group(1))
            # Determine multiplier from which pattern matched
            pattern_str = pattern.pattern
            if r"\\s*m\\b" in pattern_str or "million" in pattern_str.lower():
                num *= 1_000_000
            elif r"\\s*k\\b" in pattern_str:
                num *= 1_000
            elif "thousand" in pattern_str.lower():
                num *= 1_000
            return num if num > 0 else None
    return None


def compute_unit_price(total_price_usd: float, title: str) -> tuple[float, Optional[float]]:
    """
    Compute the unit price from total price and listing title.

    Returns (total_price_usd, unit_price_usd).
    If quantity can't be parsed, unit_price equals total_price (1 unit assumed).
    """
    quantity = parse_quantity(title)
    if quantity and quantity > 0:
        return total_price_usd / quantity, quantity
    return total_price_usd, 1.0


def extract_item_type(title: str) -> str:
    """
    Extract the base item type from a listing title by
    stripping quantity/number prefixes and common filler words.

    Example:
        "10k Gold"          -> "gold"
        "100k WoW Gold"     -> "wow gold"
        "1m ESO Gold"       -> "eso gold"
        "5000 V-Bucks"      -> "v-bucks"
    """
    # Remove leading numbers and multipliers
    cleaned = re.sub(r"^\d+(?:\.\d+)?\s*[km]?\s+", "", title, flags=re.IGNORECASE)
    # Remove "x" quantity prefixes
    cleaned = re.sub(r"^(?:x|quantity|qty|amount)[:\s]*\d+\s+", "", cleaned, flags=re.IGNORECASE)
    # Clean up
    cleaned = cleaned.strip().lower()
    return cleaned if cleaned else title.lower()