"""Долгосрочный профиль владельца: сборка по записям памяти и обновление раз в сутки."""
import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from openai import AsyncOpenAI

from storage.supabase_store import StorageError, _request, _user_id, recent_memory

logger = logging.getLogger("guardian")
KEY = "owner_profile"
TTL = 24 * 3600
_cache = {"at": 0.0, "owner": None}

SYSTEM = (
    "Ты собираешь устойчивый профиль владельца по его сохранённым записям. "
    "Отвечай по-русски, без приветствий. 10-20 коротких пунктов, разделы: Личность; "
    "Работа и бизнес; Цели; Привычки и предпочтения; Важное. "
    "Используй только записи ниже; не додумывай. Гипотезы помечай словом «предположение». "
    "Противоречия не усредняй: укажи, что данные расходятся. "
    "Не выводи телефоны, адреса, ключи и данные клиентов. До 1800 знаков."
)


def _client():
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise StorageError("DEEPSEEK_API_KEY missing")
    return AsyncOpenAI(api_key=key, base_url="https://api.deepseek.com")


def _lines(groups):
    rows = []
    for row in groups.get("facts", [])[:40]:
        rows.append("FACT: " + str(row.get("fact_text", ""))[:300])
    for row in groups.get("memory_entries", [])[:120]:
        rows.append(str(row.get("memory_type", "")) + ": " + str(row.get("memory_text", ""))[:400])
    for row in groups.get("user_states", [])[:40]:
        if row.get("state_key") == KEY:
            continue
        rows.append("STATE " + str(row.get("state_key")) + ": " + str(row.get("state_value")) +
                    (" " + str(row.get("unit")) if row.get("unit") else ""))
    text = "\n".join(rows)
    return text[:12000]


def saved(owner):
    rows = _request("user_states", params={"select": "state_value,updated_at", "telegram_user_id": f"eq.{_user_id(owner)}",
                                           "state_key": f"eq.{KEY}"})
    if not rows:
        return None, None
    return rows[0].get("state_value"), rows[0].get("updated_at")


def stale(owner, now=None):
    _, updated = saved(owner)
    if not updated:
        return True
    moment = time.time() if now is None else now
    try:
        stamp = datetime.fromisoformat(str(updated).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return True
    return moment - stamp > TTL


async def build(owner):
    groups = await asyncio.to_thread(recent_memory, owner)
    source = _lines(groups)
    if len(source) < 120:
        return None
    response = await asyncio.wait_for(_client().chat.completions.create(
        model="deepseek-chat", temperature=0.2, max_tokens=900,
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": source}],
    ), timeout=40)
    text = (response.choices[0].message.content or "").strip()
    if not 80 <= len(text) <= 1800:
        raise StorageError("profile length")
    await asyncio.to_thread(_request, "rpc/save_user_state", record={
        "p_user_id": _user_id(owner), "p_key": KEY, "p_value": text,
        "p_category": "profile", "p_unit": None, "p_confidence": 0.9,
    })
    _cache.update({"at": time.time(), "owner": owner})
    return text


async def refresh(owner):
    try:
        if not await asyncio.to_thread(stale, owner):
            return None
        return await build(owner)
    except Exception as error:
        logger.warning("Профиль: обновление не выполнено (%s)", type(error).__name__)
        return None


def format_profile(value):
    text = str(value or "").strip()
    return "ПРОФИЛЬ ВЛАДЕЛЬЦА (сводка по памяти):\n" + text if text else ""
