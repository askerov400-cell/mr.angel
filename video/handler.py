"""Private video messages, bounded downloads and temporary media only."""
import asyncio
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from openai import RateLimitError
from memory.journal import record, redact, send_reply
from speech.handler import transcribe
from .extract import extract, InvalidVideo, MAX_SECONDS
from .analysis import describe

logger = logging.getLogger('guardian')
MAX_BYTES = 18 * 1024 * 1024
FORMATS = {'.mp4','.mov','.webm'}
PROCESSING = asyncio.Semaphore(2)

def media(message):
    clip = getattr(message,'video',None) or getattr(message,'video_note',None)
    if clip:
        return clip,'.mp4'
    document = getattr(message,'document',None)
    if document:
        extension = Path(document.file_name or '').suffix.lower()
        if extension in FORMATS:
            return document,extension
    return None,None

async def handle_video(update,context,history):
    message = update.message
    if not message or not update.effective_user or not update.effective_chat:
        return
    if update.effective_chat.type != 'private' or update.effective_chat.id != update.effective_user.id:
        await send_reply(update,'Отправь видео в личный чат со мной.')
        return
    clip,extension = media(message)
    if not clip:
        await send_reply(update,'Отправь ролик в MP4, MOV или WEBM.')
        return
    duration = getattr(clip,'duration',None)
    if hasattr(duration,'total_seconds'):
        duration = duration.total_seconds()
    if not clip.file_size or clip.file_size > MAX_BYTES or (duration is not None and not 0 < duration <= MAX_SECONDS):
        await send_reply(update,'Отправь видео до 2 минут и 18 МБ.')
        return
    key = os.getenv('GROQ_API_KEY')
    if not key:
        await send_reply(update,'Разбор видео ещё не подключён.')
        return
    caption = redact(getattr(message,'caption',None) or '')
    try:
        async with asyncio.timeout(120), PROCESSING:
            with TemporaryDirectory(prefix='guardian-video-') as directory:
                path = Path(directory)/('clip'+extension)
                remote = await clip.get_file()
                if remote.file_size and remote.file_size > MAX_BYTES:
                    raise InvalidVideo('Remote size outside limit')
                await remote.download_to_drive(custom_path=path)
                if not 0 < path.stat().st_size <= MAX_BYTES:
                    raise InvalidVideo('Downloaded size outside limit')
                duration,frames,audio = await extract(path,directory)
                transcript = ''
                speech_status = 'no_audio'
                if audio:
                    try:
                        transcript = redact(await transcribe(audio,key))
                        if len(transcript)>16000:
                            transcript = ''
                        speech_status = 'recognized' if transcript else 'unintelligible'
                    except Exception as error:
                        speech_status = 'unavailable'
                        logger.warning('Видео: речь не разобрана (%s)',type(error).__name__)
                answer = redact(await describe(frames,caption,transcript,speech_status,duration,key))
    except InvalidVideo:
        await send_reply(update,'Не удалось прочитать ролик. Отправь обычный MP4 до 2 минут и 18 МБ.')
        return
    except RateLimitError:
        await send_reply(update,'Бесплатный лимит разбора видео исчерпан. Попробуй позже.')
        return
    except Exception as error:
        logger.warning('Видео не обработано (%s)',type(error).__name__)
        await send_reply(update,'Не удалось разобрать видео. Попробуй более короткий ролик.')
        return
    if not answer:
        await send_reply(update,'Не удалось разобрать видео. Попробуй более чёткий ролик.')
        return
    answer = 'Разбор по трём кадрам; события между ними могут быть пропущены.\n\n'+answer
    if speech_status=='unavailable':
        answer += '\n\nРечь не удалось распознать — выводы только по кадрам.'
    elif speech_status=='unintelligible':
        answer += '\n\nРазборчивой речи не распознал.'
    elif speech_status=='no_audio':
        answer += '\n\nВ ролике нет звуковой дорожки.'
    await record(update,'user',message,text='[Видео] '+caption)
    for offset in range(0,len(answer),3500):
        await send_reply(update,answer[offset:offset+3500])
    dialogue = history.setdefault((update.effective_user.id,update.effective_chat.id),[])
    dialogue.extend([{'role':'user','content':'[Видео] '+caption}, {'role':'assistant','content':answer}])
    dialogue[:] = dialogue[-20:]
    logger.info('Видео обработано')
