"""Validate model output before any database write."""

import math
import re


TYPES = {"FACT", "GOAL", "EVENT", "OBSERVATION", "STATE"}
CATEGORIES = {"personal", "family", "business", "finance", "health", "work", "learning", "other"}


def validate(raw):
    if not isinstance(raw, dict) or raw.get("type") not in TYPES:
        return None
    confidence = raw.get("confidence")
    if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence) or not 0.8 <= confidence <= 1):
        return None
    item = dict(raw)
    if item.get("category") not in CATEGORIES:
        item["category"] = "other"
    if item["type"] == "STATE":
        key, value, unit = item.get("state_key"), item.get("state_value"), item.get("state_unit")
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key):
            return None
        if not isinstance(value, (str, bool, int, float)):
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if isinstance(value, str) and not 1 <= len(value.strip()) <= 2000:
            return None
        if unit is not None and (not isinstance(unit, str) or len(unit) > 64):
            return None
    else:
        text = item.get("memory_text")
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 2000:
            return None
        item["memory_text"] = text.strip()
    return item
