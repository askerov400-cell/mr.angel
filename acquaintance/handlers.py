"""Private UI and explicitly linked answers; ordinary chat is never hijacked."""
import logging
import os
from types import SimpleNamespace
from uuid import UUID
from telegram import ForceReply, InlineKeyboardButton as B, InlineKeyboardMarkup as M
from interface.menu import private
from memory.journal import send_reply, redact
from . import store

logger = logging.getLogger('guardian')

def available():
    return os.getenv('MEMORY_BACKEND','sqlite') == 'supabase'

def controls(enabled, pending=None):
    rows = [[B('Пауза' if enabled else 'Включить вопросы',callback_data='aq:pause' if enabled else 'aq:enable')]]
    if enabled:
        rows.append([B('Проверочный вопрос',callback_data='aq:test')])
    if pending:
        rows.append([B('Ответить',callback_data='aq:answer:'+pending['id']),
                     B('Пропустить',callback_data='aq:skip:'+pending['id'])])
    return M(rows)

async def panel(update, context):
    if not private(update):
        await send_reply(update,'Знакомство доступно только в личном чате.')
        return
    if not available():
        await send_reply(update,'Знакомство пока недоступно: требуется подключённая долговременная память.')
        return
    try:
        rows = await store.action(update.effective_user.id,'status')
        state = rows[0] if rows else {'enabled':False,'pending':None}
        text = ('Знакомство\n\nДо 10 вопросов в день в случайное время с 10:00 до 23:00 (Казахстан, UTC+5). '
                'Если вопрос остался без ответа, следующий подождёт. '
                'Ответы сохраняются в память. Можно пропустить вопрос или включить паузу.\n\n'
                + ('Сейчас включено.' if state['enabled'] else 'Сейчас выключено.'))
        pending = state.get('pending')
        if pending:
            text += '\n\nОжидает ответа: '+(pending.get('question_text') or 'Отправка вопроса не подтверждена; можно пропустить.')
        await send_reply(update,text,reply_markup=controls(state['enabled'],pending))
    except Exception as error:
        logger.warning('Знакомство: настройки недоступны (%s)',type(error).__name__)
        await send_reply(update,'Знакомство сейчас недоступно. Настройки не изменены; попробуй позже.')

async def callback(update, context):
    query = update.callback_query
    await query.answer()
    if not private(update) or not available():
        return
    proxy = SimpleNamespace(message=query.message,effective_user=update.effective_user,effective_chat=update.effective_chat)
    owner = update.effective_user.id
    try:
        _, operation, *tail = query.data.split(':')
        worker = context.application.bot_data['acquaintance_worker']
        if operation in ('enable','pause'):
            async with worker.lock(owner):
                await store.action(owner,operation)
                if operation=='enable':
                    await worker.ensure_plan(owner)
            await panel(proxy,context)
        elif operation=='test':
            await worker.deliver(owner,manual=True)
            await panel(proxy,context)
        elif operation in ('answer','skip') and len(tail)==1:
            question_id = str(UUID(tail[0]))
            async with worker.lock(owner):
                rows = await store.action(owner,'get',question_id)
                if not rows or rows[0]['status'] not in ('sending','sent'):
                    await send_reply(proxy,'Знакомство\nЭтот вопрос уже закрыт или недоступен.')
                    return
                if operation=='skip':
                    await store.action(owner,'skip',question_id)
                    await send_reply(proxy,'Знакомство\nВопрос пропущен. Ответ не записан.')
                elif rows[0].get('question_text'):
                    sent = await send_reply(proxy,'Знакомство\n\n'+rows[0]['question_text']+'\n\nНапиши ответ в поле ниже. До 1400 символов.',
                                            reply_markup=ForceReply(selective=True,input_field_placeholder='Твой ответ на вопрос'))
                    await store.action(owner,'prompt',question_id,message_id=sent.message_id)
                else:
                    await send_reply(proxy,'Знакомство\nВопрос не был подготовлен. Нажми «Пропустить», затем попробуй проверку ещё раз.')
    except Exception as error:
        logger.warning('Знакомство: действие не выполнено (%s)',type(error).__name__)
        await send_reply(proxy,'Знакомство\nНе удалось подтвердить действие. Ответ ещё не подтверждён; попробуй позже.')

async def answer(update, context, text=None):
    if not private(update) or not available():
        return False
    reply = getattr(update.message,'reply_to_message',None)
    if not reply or getattr(getattr(reply,'from_user',None),'id',None) != getattr(context.bot,'id',None):
        return False
    try:
        rows = await store.action(update.effective_user.id,'by_message',message_id=reply.message_id)
        if not rows:
            return False
        question = rows[0]
        if question['status']=='answered':
            await send_reply(update,'Знакомство\nОтвет на этот вопрос уже сохранён.')
            return True
        if question['status'] not in ('sending','sent'):
            await send_reply(update,'Знакомство\nЭтот вопрос пропущен. Ответ не записан.')
            return True
        voice_answer = text is not None
        text = redact((text if text is not None else update.message.text).strip())
        if not 1 <= len(text) <= 1400:
            await send_reply(update,'Знакомство\nНапиши ответ длиной до 1400 символов, ответом на тот же вопрос.')
            return True
        saved = await store.action(update.effective_user.id,'answer',question['id'],text=text)
        if not saved or not saved[0].get('saved'):
            raise RuntimeError('Answer was not confirmed')
        await send_reply(update,'Знакомство\n'+('Распознал: «'+text+'»\n' if voice_answer else '')+'Ответ сохранён в долговременной памяти.')
        return True
    except Exception as error:
        logger.warning('Знакомство: ответ не подтверждён (%s)',type(error).__name__)
        await send_reply(update,'Знакомство\nНе удалось подтвердить сохранение ответа. Повтори ответ на то же сообщение позже.')
        return True
