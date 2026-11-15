"""Архив: разделы и сохранение текста/голоса в долговременную память."""

import asyncio
import logging

from types import SimpleNamespace
from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M

from database import add_fact
from interface.menu import private
from memory.journal import send_reply

logger = logging.getLogger("guardian")

# Разделы архива: (callback-ключ, название категории в памяти).
SECTIONS = [
    ("car", "ТОО автомобиля"),
    ("recipes", "Рецепты еды"),
    ("work_photos", "Рабочие фото"),
]

PENDING_KEY = "archive_section"


def clear_pending(context):
    data = getattr(context, "user_data", None)
    if data:
        data.pop(PENDING_KEY, None)


def section_name(key):
    for k, name in SECTIONS:
        if k == key:
            return name
    return None


def keyboard():
    rows = [[B(name, callback_data="archive:" + key) for key, name in SECTIONS]]
    rows.append([B("Отмена", callback_data="archive:cancel")])
    return M(rows)


async def panel(update, context):
    if not private(update):
        await send_reply(update, "Архив доступен только в личном чате.")
        return
    context.user_data.pop(PENDING_KEY, None)
    await send_reply(
        update,
        "Архив\n\nВыбери раздел, затем отправь текстовое или голосовое сообщение — "
        "сохраню его в долговременную память.",
        reply_markup=keyboard(),
    )


async def callback(update, context):
    query = update.callback_query
    await query.answer()
    if not private(update):
        return
    proxy = SimpleNamespace(
        message=query.message,
        effective_user=update.effective_user,
        effective_chat=update.effective_chat,
    )
    data = query.data
    if data == "archive:cancel":
        context.user_data.pop(PENDING_KEY, None)
        await send_reply(proxy, "Архив: выбор отменён.", reply_markup=keyboard())
        return
    if data.startswith("archive:"):
        key = data.removeprefix("archive:")
        name = section_name(key)
        if not name:
            await send_reply(proxy, "Архив: раздел не найден.", reply_markup=keyboard())
            return
        context.user_data[PENDING_KEY] = key
        await send_reply(
            proxy,
            "Архив · " + name + "\n\nОтправь текстовое или голосовое сообщение — "
            "сохраню его в этот раздел. Для отмены нажми «Отмена» или отправь /cancel.",
        )


async def save_pending(update, context, text):
    """Сохраняет сообщение в выбранный раздел; True, если ожидание было активно."""
    data = getattr(context, "user_data", None)
    key = data.get(PENDING_KEY) if data else None
    if not key:
        return False
    name = section_name(key)
    data.pop(PENDING_KEY, None)
    if not name:
        return True
    text = (text or "").strip()
    if not text:
        await send_reply(update, "Архив: сообщение пустое, ничего не сохранено.")
        return True
    await asyncio.to_thread(
        add_fact,
        telegram_user_id=update.effective_user.id,
        category=name,
        fact_text=text,
        source="user_explicit",
        confidence=1.0,
    )
    await send_reply(update, "Сохранено в раздел «" + name + "».")
    return True
