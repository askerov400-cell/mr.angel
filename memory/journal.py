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


async def record(update, role, message):
    if (os.getenv("MEMORY_BACKEND", "sqlite") != "supabase"
            or not update.effective_chat or update.effective_chat.type != "private"
            or not update.effective_user or not message or not message.text):
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
            "role": role, "content": redact(message.text),
        }, prefer="resolution=ignore-duplicates,return=representation")
    except Exception as error:
        logger.warning("История переписки: запись не выполнена (%s)", type(error).__name__)


async def capture_incoming(update, context):
    await record(update, "user", update.message)


async def send_reply(update, text):
    sent = await update.message.reply_text(text)
    await record(update, "assistant", sent)
    return sent
