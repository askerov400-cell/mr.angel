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
PENDING_PHOTO = "archive_photo_pending"
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

    С подписью в caption — сохраняет сразу и возвращает True. Без подписи —
    запоминает file_id, просит подпись и возвращает False, чтобы вызывающий
    код не сбрасывал ожидание подписи.
    """
    from memory.journal import redact, send_reply
    photo = update.message.photo[-1]
    caption = redact(update.message.caption or "").strip()
    if caption:
        add(update.effective_user.id, section, photo.file_id, caption)
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
    """Если ждёт подпись к фото — сохраняет фото с этой подписью; True."""
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
    add(update.effective_user.id, pending["section"], pending["file_id"], text)
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
            await update.message.reply_photo(
                photo["file_id"], caption=(photo.get("caption") or "")
            )
        return True
    if explicit:
        await send_reply(
            update,
            "Архив: фото по запросу не найдено. Загрузи фото с подписью, "
            "затем спрашивай по словам из подписи.",
        )
        return True
    return False
