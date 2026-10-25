"""Личный график владельца: хранение, команда и контекст для ответов."""
import asyncio
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M

from storage.supabase_store import _request, _user_id

KEY = 'owner_schedule'
ZONE = ZoneInfo('Asia/Qyzylorda')
LIMIT = 4000
WEEKDAYS = ('понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье')


def _owner_allowed(update):
    owner = os.getenv('X2POS_OWNER_ID') or os.getenv('KIDS_OWNER') or ''
    user = getattr(update, 'effective_user', None)
    chat = getattr(update, 'effective_chat', None)
    return bool(owner and user and chat and chat.type == 'private' and str(user.id) == owner)


def load(owner):
    rows = _request('user_states', params={'select': 'state_value', 'telegram_user_id': f'eq.{_user_id(owner)}',
                                           'state_key': f'eq.{KEY}'})
    if not rows:
        return ''
    value = rows[0].get('state_value')
    if isinstance(value, dict):
        return str(value.get('text') or '')
    try:
        data = json.loads(str(value))
    except (TypeError, ValueError):
        return ''
    return str(data.get('text') or '') if isinstance(data, dict) else ''


def save(owner, text):
    text = str(text or '').strip()[:LIMIT]
    _request('rpc/save_user_state', record={
        'p_user_id': _user_id(owner), 'p_key': KEY,
        'p_value': json.dumps({'text': text, 'updated': datetime.now(ZONE).isoformat()}, ensure_ascii=False),
        'p_category': 'schedule', 'p_unit': None, 'p_confidence': 0.9,
    })
    return text


def context_text(owner, moment=None):
    moment = moment or datetime.now(ZONE)
    try:
        text = load(owner)
    except Exception:
        return ''
    if not text:
        return ''
    return ('Сегодня ' + WEEKDAYS[moment.weekday()] + '.\n' + text)[:1800]


def panel_text(text):
    if not text:
        return ('Личный график не задан. Пришли расписание одним сообщением, я сохраню и буду '
                'учитывать его в ответах. Можно описывать каждый день отдельными строками.')
    return 'Твой график:\n\n' + text[:LIMIT]


async def panel(update, context):
    if not _owner_allowed(update):
        await update.message.reply_text('График доступен только владельцу.')
        return
    try:
        text = await asyncio.to_thread(load, update.effective_user.id)
    except Exception:
        await update.message.reply_text('Не удалось прочитать график: хранилище недоступно.')
        return
    rows = [[B('Изменить', callback_data='sched:edit'), B('Очистить', callback_data='sched:clear')]]
    await update.message.reply_text(panel_text(text), reply_markup=M(rows))


async def callback(update, context):
    query = update.callback_query
    await query.answer()
    if not _owner_allowed(update):
        return
    action = (query.data or '').partition(':')[2]
    if action == 'edit':
        context.user_data['schedule_edit'] = True
        await query.message.reply_text('Пришли график одним сообщением. Он заменит прежний.')
        return
    if action == 'clear':
        try:
            await asyncio.to_thread(save, update.effective_user.id, '')
        except Exception:
            await query.message.reply_text('Не удалось очистить график: хранилище недоступно.')
            return
        await query.message.reply_text('График очищен.')


async def accept(update, context, text):
    data = getattr(context, 'user_data', None)
    if not data or not data.get('schedule_edit'):
        return False
    data.pop('schedule_edit', None)
    text = str(text or '').strip()
    if len(text) < 5:
        await update.message.reply_text('Слишком коротко. Пришли график текстом, хотя бы пару строк.')
        return True
    try:
        await asyncio.to_thread(save, update.effective_user.id, text)
    except Exception:
        await update.message.reply_text('Не удалось сохранить график: хранилище недоступно. Повтори позже.')
        return True
    await update.message.reply_text('График сохранён. Дальше учитываю его в ответах.')
    return True
