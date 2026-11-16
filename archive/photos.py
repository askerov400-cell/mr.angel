"""Архив фото: снимки в Supabase Storage, поиск по подписи.

Файл хранится в приватном бакете Storage archive-media; в user_states под
ключом archive_photos лежит JSON-список (раздел, путь в Storage, подпись, дата).
"""
import asyncio
import json
import logging
import os
import re
import time
import uuid
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from storage.supabase_store import _request, _user_id

logger = logging.getLogger("guardian")

KEY = "archive_photos"
PENDING_PHOTO = "archive_photo_pending"
MAX_PHOTOS = 1000
BUCKET = "archive-media"

STOPWORDS = {
    "фото", "фотограф", "снимок", "покажи", "показать", "найди", "найти", "дай",
    "мне", "где", "есть", "ли", "в", "на", "и", "у", "с", "по",
}


def _tokens(text):
    return re.findall(r"[а-яёa-z]+|[0-9]+", (text or "").lower())


def _words(query):
    tokens = _tokens(query)
    result = []
    for token in tokens:
        if token.isdigit():
            result.append(token)
        elif len(token) >= 2 and token not in STOPWORDS:
            result.append(token)
    return result


def _covers(word, caption):
    caption_tokens = _tokens(caption)
    if word.isdigit():
        return word in caption_tokens
    if word in caption_tokens:
        return True
    # Склонение: подстрока слова длиной >= 4 встречается среди токенов подписи.
    for token in caption_tokens:
        if not token.isdigit() and len(token) >= 4 and (token in word or word in token):
            return True
    return False


def _load(owner):
    rows = _request("user_states", params={
        "select": "state_value", "telegram_user_id": f"eq.{_user_id(owner)}",
        "state_key": f"eq.{KEY}", "limit": "1",
    })
    if not rows:
        return []
    value = rows[0].get("state_value")
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(str(value)) if value else []
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _save(owner, photos):
    _request("rpc/save_user_state", record={
        "p_user_id": _user_id(owner), "p_key": KEY,
        "p_value": json.dumps(photos, ensure_ascii=False),
        "p_category": "archive", "p_unit": None, "p_confidence": 1.0,
    })


def _storage_headers():
    base = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SECRET_KEY", "")
    if not base or not key:
        raise RuntimeError("Storage не настроен")
    headers = {"apikey": key}
    if not key.startswith("sb_secret_"):
        headers["Authorization"] = "Bearer " + key
    return base, headers


def storage_put(owner, data, extension="jpg"):
    """Загружает байты в приватный бакет и возвращает путь объекта."""
    base, headers = _storage_headers()
    path = f"{owner}/{uuid.uuid4().hex}.{extension}"
    url = f"{base}/storage/v1/object/{BUCKET}/{path}"
    headers = {**headers, "Content-Type": "image/jpeg"}
    request = Request(url, data=bytes(data), headers=headers, method="POST")
    try:
        with urlopen(request, timeout=30) as response:
            response.read()
    except HTTPError as error:
        raise RuntimeError(f"Storage upload HTTP {error.code}") from None
    return path


def storage_get(path):
    """Скачивает объект из бакета и возвращает байты."""
    base, headers = _storage_headers()
    url = f"{base}/storage/v1/object/{BUCKET}/{path}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            return response.read()
    except HTTPError as error:
        raise RuntimeError(f"Storage download HTTP {error.code}") from None


def storage_delete(path):
    """Удаляет объект из бакета; ошибка удаления не критична."""
    base, headers = _storage_headers()
    url = f"{base}/storage/v1/object/{BUCKET}/{path}"
    request = Request(url, headers=headers, method="DELETE")
    try:
        with urlopen(request, timeout=30) as response:
            response.read()
    except HTTPError:
        return


def add(owner, section, storage_path, caption):
    photos = _load(owner)
    photos.append({
        "section": section, "storage_path": storage_path,
        "caption": caption.strip(), "added_at": int(time.time()),
    })
    _save(owner, photos[-MAX_PHOTOS:])


def find(owner, query, limit=10):
    """Возвращает фото по запросу.

    Сначала фото, где покрыты все значимые слова; если таких нет — фото,
    где покрыто хотя бы одно слово. Без значимых слов — последние фото.
    """
    photos = _load(owner)
    words = _words(query)
    if not words:
        return photos[-limit:]
    exact = []
    partial = []
    for photo in photos:
        caption = (photo.get("caption") or "").lower()
        if all(_covers(word, caption) for word in words):
            exact.append(photo)
        elif any(_covers(word, caption) for word in words):
            partial.append(photo)
    return (exact or partial)[-limit:]


def is_request(text):
    lowered = (text or "").lower()
    return "фото" in lowered or "снимок" in lowered


async def save_from_message(update, context, section):
    """Обрабатывает фото-сообщение в архиве.

    Скачивает байты из Telegram, загружает в Storage. С подписью в caption —
    сохраняет сразу и возвращает True. Без подписи — запоминает file_id,
    просит подпись и возвращает False, чтобы не сбросить ожидание подписи.
    """
    from memory.journal import redact, send_reply
    photo = update.message.photo[-1]
    caption = redact(update.message.caption or "").strip()
    if caption:
        try:
            remote = await photo.get_file()
            data = await remote.download_as_bytearray()
            path = await asyncio.to_thread(storage_put, update.effective_user.id, bytes(data))
        except Exception as error:
            logger.warning("Архив: загрузка фото в Storage не удалась (%s)", type(error).__name__)
            await send_reply(update, "Не удалось сохранить фото. Попробуй ещё раз.")
            return True
        add(update.effective_user.id, section, path, caption)
        await send_reply(update, "Сохранено фото в раздел «" + section + "»: " + caption)
        return True
    context.user_data[PENDING_PHOTO] = {
        "section": section, "file_id": photo.file_id,
    }
    await send_reply(
        update,
        "Архив · " + section + "\n\nФото принял. Напиши подпись следующим сообщением — "
        "по ней потом найдёшь снимок. Например: «стеллаж №3».",
    )
    return False


async def try_save_caption(update, context, text):
    """Если ждёт подпись к фото — загружает фото в Storage с этой подписью; True."""
    from memory.journal import redact, send_reply
    data = getattr(context, "user_data", None)
    pending = data.get(PENDING_PHOTO) if data else None
    if not pending:
        return False
    data.pop(PENDING_PHOTO, None)
    text = redact(text or "").strip()
    if not text:
        await send_reply(update, "Архив: подпись пустая, фото не сохранено.")
        return True
    try:
        remote = await context.bot.get_file(pending["file_id"])
        file_data = await remote.download_as_bytearray()
        path = await asyncio.to_thread(storage_put, update.effective_user.id, bytes(file_data))
    except Exception as error:
        logger.warning("Архив: загрузка фото в Storage не удалась (%s)", type(error).__name__)
        await send_reply(update, "Не удалось сохранить фото. Попробуй ещё раз.")
        return True
    add(update.effective_user.id, pending["section"], path, text)
    from archive.handlers import clear_pending
    clear_pending(context)
    await send_reply(update, "Сохранено фото в раздел «" + pending["section"] + "»: " + text)
    return True


async def try_find(update, context, text, limit=10):
    """Ищет и показывает фото по словам запроса; True, если обработал запрос.

    Возвращает False, когда запрос не про фото и совпадений нет — тогда
    сообщение идёт обычным путём в диалог.
    """
    from memory.journal import send_reply
    explicit = is_request(text)
    photos = find(update.effective_user.id, text, limit)
    if photos:
        for photo in photos:
            path = photo.get("storage_path")
            if path:
                try:
                    data = await asyncio.to_thread(storage_get, path)
                    await update.message.reply_photo(bytes(data), caption=(photo.get("caption") or ""))
                    continue
                except Exception as error:
                    logger.warning("Архив: выдача фото из Storage не удалась (%s)", type(error).__name__)
            # Старые записи без storage_path или сбой Storage — отдаём по file_id.
            if photo.get("file_id"):
                await update.message.reply_photo(photo["file_id"], caption=(photo.get("caption") or ""))
            else:
                await send_reply(update, "Не удалось загрузить фото из хранилища.")
        return True
    if explicit:
        await send_reply(
            update,
            "Архив: фото по запросу не найдено. Загрузи фото с подписью, "
            "затем спрашивай по словам из подписи.",
        )
        return True
    return False
