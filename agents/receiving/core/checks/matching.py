"""Field-aware equality; never substring identity."""
import re
import unicodedata

def text(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())

def sku(value):
    return text(value)

def variant(value):
    value = text(value)
    # Only normalize number/unit spacing, not arbitrary token boundaries.
    return re.sub(r"(\d)\s+(ml|l|mm|cm|m|g|kg|oz|ft|in)\b", r"\1\2", value)

def colour(value):
    return text(value)
