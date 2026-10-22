"""Панель «Расписание детей» и кнопки напоминаний."""
import asyncio
import os

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M

from kids import report, store
from memory.journal import send_reply

DAYS = ('mon', 'tue', 'wed', 'thu', 'fri')


def owner_allowed(update):
    return (getattr(update, 'effective_chat', None) is not None
            and update.effective_chat.type == 'private'
            and str(update.effective_user.id) == (os.getenv('KIDS_OWNER') or os.getenv('X2POS_OWNER_ID') or ''))


def keyboard(day, enabled=True):
    return M([[B(('· ' if key != day else '✅ ') + store.DAY_NAMES[key][:2], callback_data='kids:day:' + key)
               for key in DAYS],
              [B('Забрал', callback_data='kids:done:' + day)],
              [B('Пауза напоминаний' if enabled else 'Включить напоминания',
                 callback_data='kids:pause' if enabled else 'kids:enable')]])


async def panel(update, context):
    if not owner_allowed(update):
        await update.message.reply_text('Расписание детей доступно только владельцу.')
        return
    moment = store.local_now()
    data = await asyncio.to_thread(store.ensure, update.effective_user.id)
    day = DAYS[moment.weekday()] if moment.weekday() < 5 else 'mon'
    text = report.day_text(data, day, moment)
    if not data.get('enabled', True):
        text += '\n\nНапоминания на паузе.'
    await update.message.reply_text(text, reply_markup=keyboard(day, data.get('enabled', True)))


async def callback(update, context):
    query = update.callback_query
    await query.answer()
    if not owner_allowed(update):
        return
    owner = update.effective_user.id
    _, operation, *tail = query.data.split(':')
    moment = store.local_now()
    data = await asyncio.to_thread(store.ensure, owner)
    if operation == 'day' and tail:
        day = tail[0] if tail[0] in store.DAY_NAMES else 'mon'
        await send_reply(update, report.day_text(data, day, moment),
                         reply_markup=keyboard(day, data.get('enabled', True)))
        return
    if operation in ('pause', 'enable'):
        data['enabled'] = operation == 'enable'
        await asyncio.to_thread(store.save, owner, data)
        await send_reply(update, 'Напоминания детей: ' + ('включены' if data['enabled'] else 'на паузе') + '.',
                         reply_markup=keyboard('mon', data['enabled']))
        return
    if operation == 'done':
        today = moment.date().isoformat()
        data.setdefault('sent', {}).setdefault(today, {}).update({'before': True, 'end': True})
        await asyncio.to_thread(store.save, owner, data)
        await send_reply(update, 'Отмечено: забрал. Напоминания на сегодня закрыты.')
