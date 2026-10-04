"""Server-only Supabase memory access. Never log request headers or records."""

import json
import math
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


class StorageError(RuntimeError):
    """Safe storage failure without credentials or response bodies."""


def _user_id(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("Telegram user ID must be a positive integer")
    return value


def _request(table, params=None, record=None):
    base = os.getenv("SUPABASE_URL", "").rstrip("/")
    parsed = urlparse(base)
    key = os.getenv("SUPABASE_SECRET_KEY", "")
    if (parsed.scheme != "https" or not parsed.hostname
            or not parsed.hostname.endswith(".supabase.co")
            or parsed.username or parsed.password or parsed.query
            or parsed.fragment or parsed.path or parsed.port):
        raise StorageError("Invalid SUPABASE_URL")
    if not key:
        raise StorageError("SUPABASE_SECRET_KEY is missing")
    headers = {"apikey": key, "Content-Type": "application/json"}
    # Legacy service_role keys are JWTs; modern secret keys use apikey only.
    if not key.startswith("sb_secret_"):
        headers["Authorization"] = "Bearer " + key
    url = base + "/rest/v1/" + table
    if params:
        url += "?" + urlencode(params)
    data = None
    if record is not None:
        headers["Prefer"] = "return=representation"
        data = json.dumps(record, allow_nan=False).encode("utf-8")
    request = Request(url, data=data, headers=headers)
    try:
        with urlopen(request, timeout=20) as response:
            result = json.load(response)
    except HTTPError as error:
        raise StorageError(f"Supabase request failed (HTTP {error.code})") from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise StorageError("Supabase unavailable or invalid response") from None
    if not isinstance(result, list):
        raise StorageError("Unexpected Supabase response")
    return result


def init_database():
    # Schema is applied separately, never silently created by the bot.
    _request("facts", {"select": "id", "limit": "0"})


def _insert(table, telegram_user_id, **values):
    for field in ("fact_text", "observation_text", "goal_text", "event_text"):
        if field in values and (not isinstance(values[field], str) or not values[field].strip()):
            raise ValueError("Memory text must not be empty")
    if "confidence" in values:
        confidence = values["confidence"]
        if not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("Confidence must be between 0 and 1")
    rows = _request(table, record={"telegram_user_id": _user_id(telegram_user_id), **values})
    if len(rows) != 1 or "id" not in rows[0]:
        raise StorageError("Supabase did not confirm the saved record")
    return rows[0]["id"]


def _read(table, user_id, active=False, order="id.asc"):
    params = {"select": "*", "telegram_user_id": f"eq.{_user_id(user_id)}", "order": order}
    if active:
        params["status"] = "eq.active"
    rows = []
    offset = 0
    while True:
        page = _request(table, {**params, "limit": "1000", "offset": str(offset)})
        if any(row.get("telegram_user_id") != user_id for row in page):
            raise StorageError("Supabase returned records for another user")
        rows.extend(page)
        if not page:
            return rows
        offset += len(page)


def add_fact(telegram_user_id, category, fact_text, source="user", confidence=1.0):
    return _insert("facts", telegram_user_id, category=category, fact_text=fact_text, source=source, confidence=confidence)


def get_facts(telegram_user_id):
    return _read("facts", telegram_user_id)


def add_observation(telegram_user_id, category, observation_text, evidence="", confidence=0.5):
    return _insert("observations", telegram_user_id, category=category, observation_text=observation_text, evidence=evidence, confidence=confidence)


def get_observations(telegram_user_id):
    return _read("observations", telegram_user_id, active=True)


def add_goal(telegram_user_id, category, goal_text, priority=5, source="user"):
    return _insert("goals", telegram_user_id, category=category, goal_text=goal_text, priority=priority, source=source)


def get_goals(telegram_user_id):
    return _read("goals", telegram_user_id, active=True, order="priority.desc,id.asc")


def add_event(telegram_user_id, category, event_text, event_date=None, source="user"):
    return _insert("events", telegram_user_id, category=category, event_text=event_text, event_date=event_date, source=source)


def get_events(telegram_user_id):
    return _read("events", telegram_user_id)
