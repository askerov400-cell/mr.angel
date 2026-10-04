"""Private chat journal; credentials are masked before persistence."""
import asyncio
import logging
import os
import re

from storage.supabase_store import _request

logger = logging.getLogger("guardian")


def redact(text):
    for name, value in os.environ.items():
        if re.search(r"TOKEN|KEY|PASSWORD|SECRET|DATABASE_URL", name) and len(value) >= 8:
            text = text.replace(value, "[секрет скрыт]")
    return re.sub(
        r"\b(?:sb_secret_[A-Za-z0-9_-]+|sk-[A-Za-z0-9_-]{16,}|\d{7,12}:[A-Za-z0-9_-]{30,})\b",
        "[секрет скрыт]", text,
    )


async def record(update, role, message, text=None):
    content = text if text is not None else getattr(message, "text", None)
    if (os.getenv("MEMORY_BACKEND", "sqlite") != "supabase"
            or not update.effective_chat or update.effective_chat.type != "private"
            or not update.effective_user or not message or not content):
        return
    try:
        if (not isinstance(message.message_id, int) or message.message_id <= 0
                or update.effective_chat.id != update.effective_user.id):
            return
        await asyncio.to_thread(_request, "chat_messages", params={
            "on_conflict": "chat_id,telegram_message_id",
        }, record={
            "telegram_user_id": update.effective_user.id,
            "chat_id": update.effective_chat.id,
            "telegram_message_id": message.message_id,
            "role": role, "content": redact(content),
        }, prefer="resolution=ignore-duplicates,return=representation")
    except Exception as error:
        logger.warning("История переписки: запись не выполнена (%s)", type(error).__name__)


async def capture_incoming(update, context):
    await record(update, "user", update.message)


async def send_reply(update, text):
    sent = await update.message.reply_text(text)
    await record(update, "assistant", sent)
    return sent


def dialogue_from_rows(rows, current_message_id, limit=20):
    result = []
    skip_service_replies = False
    for row in reversed(rows):
        if row["telegram_message_id"] == current_message_id:
            continue
        role, text = row["role"], row["content"]
        if role == "assistant" and text == "Память текущего диалога очищена.\nДолговременная память сохранена.":
            result = []
            continue
        if role == "user":
            is_command = text.strip().startswith("/")
            skip_service_replies = is_command
            if is_command:
                continue
        if role == "assistant" and skip_service_replies:
            continue
        if role in ("user", "assistant"):
            result.append({"role": role, "content": text})
    return result[-limit:]


async def restore_dialogue(update):
    message_id = getattr(update.message, "message_id", None)
    if not isinstance(message_id, int) or update.effective_chat.type != "private":
        return []
    owner, chat_id = update.effective_user.id, update.effective_chat.id
    try:
        rows = await asyncio.to_thread(_request, "chat_messages", params={
            "select": "telegram_user_id,chat_id,telegram_message_id,role,content",
            "telegram_user_id": f"eq.{owner}", "chat_id": f"eq.{chat_id}",
            "order": "id.desc", "limit": "60",
        })
        if any(row["telegram_user_id"] != owner or row["chat_id"] != chat_id for row in rows):
            raise ValueError("Unexpected owner in journal")
        return dialogue_from_rows(rows, message_id)
    except Exception as error:
        logger.warning("Диалог: восстановление недоступно (%s)", type(error).__name__)
        return []
