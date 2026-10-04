"""Bounded audio download and transcription; no audio persistence."""
import asyncio
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from openai import AsyncOpenAI, RateLimitError
from memory.journal import record, redact, send_reply

logger = logging.getLogger("guardian")
MAX_BYTES = 10 * 1024 * 1024
MAX_SECONDS = 300
FORMATS = {"flac", "mp3", "mp4", "mpeg", "mpga", "m4a", "ogg", "wav", "webm"}


async def transcribe(path, key):
    async with AsyncOpenAI(api_key=key, base_url="https://api.groq.com/openai/v1",
                          timeout=45, max_retries=0) as client:
        with path.open("rb") as audio:
            result = await client.audio.transcriptions.create(
                model="whisper-large-v3-turbo", file=audio,
                response_format="json", temperature=0,
            )
    return result.text.strip()


async def handle_audio(update, context, respond):
    message = update.message
    if not message or not update.effective_user or not update.effective_chat:
        return
    if update.effective_chat.type != "private":
        await send_reply(update, "Отправь голосовое в личный чат со мной.")
        return
    audio = message.voice or message.audio
    if not audio:
        return
    duration = audio.duration
    if hasattr(duration, "total_seconds"):
        duration = duration.total_seconds()
    if duration is None or duration > MAX_SECONDS or not audio.file_size or audio.file_size > MAX_BYTES:
        await send_reply(update, "Отправь аудио до 5 минут и 10 МБ.")
        return
    extension = "ogg" if message.voice else Path(audio.file_name or "").suffix.lower().lstrip(".")
    if extension not in FORMATS:
        await send_reply(update, "Этот формат не поддерживается. Отправь голосовое или MP3.")
        return
    key = os.getenv("GROQ_API_KEY")
    if not key:
        await send_reply(update, "Распознавание ещё не подключено. Пока напиши текстом.")
        return
    try:
        async with asyncio.timeout(60):
            with TemporaryDirectory(prefix="guardian-audio-") as directory:
                path = Path(directory) / f"message.{extension}"
                remote = await audio.get_file()
                if remote.file_size and remote.file_size > MAX_BYTES:
                    await send_reply(update, "Отправь аудио до 5 минут и 10 МБ.")
                    return
                await remote.download_to_drive(custom_path=path)
                if path.stat().st_size > MAX_BYTES:
                    await send_reply(update, "Отправь аудио до 5 минут и 10 МБ.")
                    return
                text = redact(await transcribe(path, key))
    except RateLimitError:
        await send_reply(update, "Бесплатный лимит распознавания исчерпан. Попробуй позже или напиши текстом.")
        return
    except Exception as error:
        logger.warning("Распознавание аудио не выполнено (%s)", type(error).__name__)
        await send_reply(update, "Не удалось распознать аудио. Попробуй ещё раз или напиши текстом.")
        return
    if not text or len(text) > 16000:
        await send_reply(update, "Не удалось разобрать речь. Отправь более короткое голосовое.")
        return
    await record(update, "user", message, text=text)
    logger.info("Аудио распознано")
    await respond(update, context, text)
