"""Recognize standalone utility commands without Telegram formatting metadata."""
import re


PATTERN = r"^\s*/(?:memory|clear)(?:@[A-Za-z0-9_]+)?\s*$"


def parse(text, username):
    match = re.fullmatch(r"\s*/(memory|clear)(?:@([A-Za-z0-9_]+))?\s*", text)
    if not match:
        return None
    if match.group(2) and match.group(2).lower() != (username or "").lower():
        return None
    return match.group(1)
