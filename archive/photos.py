"""Архив фото: ссылки на снимки по разделам и поиск по подписи.

Файлы живут на серверах Telegram по file_id; в user_states хранится только
JSON-строка со списком записей (раздел, file_id, подпись, дата). Значение
остаётся примитивом-строкой, как требуют ограничения user_states.
"""
import json
import re
import time

from storage.supabase_store import _request, _user_id

KEY = "archive_photos"
MAX_PHOTOS = 1000
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


def add(owner, section, file_id, caption):
    photos = _load(owner)
    photos.append({
        "section": section, "file_id": file_id,
        "caption": caption.strip(), "added_at": int(time.time()),
    })
    _save(owner, photos[-MAX_PHOTOS:])


def find(owner, query, limit=10):
    """Возвращает фото, где все значимые слова запроса покрыты подписью."""
    photos = _load(owner)
    words = _words(query)
    if not words:
        return photos[-limit:]
    matches = []
    for photo in photos:
        caption = (photo.get("caption") or "").lower()
        if all(_covers(word, caption) for word in words):
            matches.append(photo)
    return matches[-limit:]


def is_request(text):
    lowered = (text or "").lower()
    return "фото" in lowered or "снимок" in lowered


async def save_from_message(update, context, section):
    """Сохраняет фото-сообщение в раздел архива; True, если сохранено."""
    from memory.journal import redact, send_reply
    photo = update.message.photo[-1]
    caption = redact(update.message.caption or "").strip()
    if not caption:
        await send_reply(
            update,
            "Архив · " + section + "\n\nК фото нужна подпись. Напиши её в поле «Описание» "
            "и отправь фото ещё раз.",
        )
        return False
    add(update.effective_user.id, section, photo.file_id, caption)
    await send_reply(update, "Сохранено фото в раздел «" + section + "»: " + caption)
    return True


async def send_matches(update, context, query, limit=10):
    """Отправляет найденные фото; True, если обработал запрос."""
    from memory.journal import send_reply
    photos = find(update.effective_user.id, query, limit)
    if not photos:
        await send_reply(
            update,
            "Архив: фото по запросу не найдено. Загрузи фото с подписью, "
            "затем спрашивай по словам из подписи.",
        )
        return True
    for photo in photos:
        await update.message.reply_photo(
            photo["file_id"], caption=(photo.get("caption") or "")
        )
    return True
