"""Ежедневная сводка Kaspi в 09:05 с защитой от повторов через user_states."""
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from storage.supabase_store import _request, _user_id
from kaspi import statistics
from kaspi.client import KaspiError

logger = logging.getLogger("guardian")

ZONE = ZoneInfo("Asia/Qyzylorda")
KEY = "kaspi_morning"
SEND_AFTER = (9, 5)  # час, минута (Asia/Qyzylorda)


def last_sent(owner):
    rows = _request("user_states", params={
        "select": "state_value", "telegram_user_id": f"eq.{_user_id(owner)}",
        "state_key": f"eq.{KEY}", "limit": "1",
    })
    if not rows:
        return None
    value = rows[0].get("state_value")
    return value if isinstance(value, str) else None


def mark_sent(owner, day):
    _request("rpc/save_user_state", record={
        "p_user_id": _user_id(owner), "p_key": KEY,
        "p_value": json.dumps(day.isoformat()),
        "p_category": "kaspi", "p_unit": None, "p_confidence": 1.0,
    })


class Monitor:
    def __init__(self, bot, owner):
        self.bot = bot
        self.owner = _user_id(int(owner))
        self.failures = 0

    async def notify(self, text):
        try:
            await asyncio.wait_for(self.bot.send_message(chat_id=self.owner, text=text), 30)
            logger.info("Kaspi: утренняя сводка отправлена")
        except Exception as error:
            logger.warning("Kaspi: исход отправки неизвестен (%s)", type(error).__name__)

    async def tick(self, now=None):
        now = now or datetime.now(ZONE)
        if (now.hour, now.minute) < SEND_AFTER:
            return
        target = now.date() - timedelta(days=1)
        if last_sent(self.owner) == target.isoformat():
            return
        try:
            text = await statistics.summary(target)
        except KaspiError as error:
            logger.warning("Kaspi: сводка не готова (%s)", type(error).__name__)
            return
        # Записываем до отправки: неизвестный исход не порождает повторную рассылку.
        try:
            mark_sent(self.owner, target)
        except Exception as error:
            logger.warning("Kaspi: отметка сводки не сохранена (%s)", type(error).__name__)
            return
        await self.notify(text)

    async def run(self):
        logger.info("Kaspi: утренняя сводка в 09:05 запущена")
        while True:
            started = time.monotonic()
            try:
                await self.tick()
            except Exception as error:
                logger.warning("Kaspi: цикл сводки не завершён (%s)", type(error).__name__)
            await asyncio.sleep(max(60, 300 - (time.monotonic() - started)))


async def start(app):
    owner = os.getenv("KASPI_OWNER_ID", "").strip()
    if not owner:
        logger.warning("Kaspi: KASPI_OWNER_ID не задан, утренняя сводка не запущена")
        return
    app.bot_data["kaspi_monitor"] = Monitor(app.bot, owner)
    app.bot_data["kaspi_task"] = asyncio.create_task(app.bot_data["kaspi_monitor"].run())


async def stop(app):
    task = app.bot_data.pop("kaspi_task", None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
