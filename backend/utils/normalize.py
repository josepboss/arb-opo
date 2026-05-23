"""
Text normalization utilities for matching game/service titles across platforms.
"""

import re
import unicodedata


def strip_accents(text: str) -> str:
    """Remove accents/diacritics from text."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_game_title(title: str) -> str:
    """
    Normalize a game/service title for cross-platform matching.

    Steps:
    1. Lowercase
    2. Strip accents
    3. Remove special characters (keep letters, digits, spaces)
    4. Remove parenthetical qualifiers like (Global), (EU), (US)
    5. Collapse whitespace
    6. Strip leading/trailing whitespace

    Examples:
        "World of Warcraft (Global)" -> "world of warcraft"
        "WoW Retail"                 -> "wow retail"
        "World of Warcraft"          -> "world of warcraft"
    """
    text = title.lower()
    text = strip_accents(text)

    # Remove parenthetical qualifiers
    text = re.sub(r"\([^)]*\)", "", text)

    # Remove special characters
    text = re.sub(r"[^a-z0-9\s]", " ", text)

    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# Known title aliases for fuzzy matching when exact normalization isn't enough
GAME_ALIASES: dict[str, list[str]] = {
    "world of warcraft": [
        "world of warcraft",
        "wow",
        "wow retail",
        "world of warcraft retail",
        "wow dragonflight",
        "world of warcraft dragonflight",
        "wow the war within",
        "world of warcraft the war within",
    ],
    "world of warcraft classic": [
        "world of warcraft classic",
        "wow classic",
        "wow classic wrath",
        "wotlk",
        "wrath of the lich king",
        "wow cataclysm",
        "wow cata",
        "world of warcraft cataclysm",
    ],
    "lost ark": [
        "lost ark",
        "lostark",
    ],
    "path of exile": [
        "path of exile",
        "poe",
        "path of exile 2",
        "poe2",
    ],
    "diablo iv": [
        "diablo 4",
        "diablo iv",
        "d4",
    ],
    "diablo iii": [
        "diablo 3",
        "diablo iii",
        "d3",
    ],
    "new world": [
        "new world",
        "new world mmo",
    ],
    "throne and liberty": [
        "throne and liberty",
        "tl",
        "throne & liberty",
    ],
    "euro truck simulator 2": [
        "euro truck simulator 2",
        "ets2",
        "ets 2",
    ],
    "american truck simulator": [
        "american truck simulator",
        "ats",
    ],
    "elden ring": [
        "elden ring",
        "elden ring runes",
        "er runes",
    ],
    "final fantasy xiv": [
        "final fantasy xiv",
        "ffxiv",
        "ff14",
        "final fantasy 14",
    ],
    "fortnite": [
        "fortnite",
        "fn",
        "fortnite vbucks",
    ],
}


def resolve_alias(normalized: str) -> str:
    """
    Resolve a normalized title to its canonical alias group key.

    Returns the canonical name if found, or the original string if unknown.
    """
    for canonical, aliases in GAME_ALIASES.items():
        for alias in aliases:
            if normalized == normalize_game_title(alias):
                return canonical
    return normalized