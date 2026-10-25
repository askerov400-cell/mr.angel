"""Панель «Расписание детей» и кнопки напоминаний."""
import asyncio
import os

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M

from kids import report, store
from memory.journal import send_reply

DAYS = store.DAYS


def owner_allowed(update):
    return (getattr(update, 'effective_chat', None) is not None
            and update.effective_chat.type == 'private'
            and str(update.effective_user.id) == (os.getenv('KIDS_OWNER') or os.getenv('X2POS_OWNER_ID') or ''))


def keyboard(data, day, enabled=True):
    rows = [[B(('· ' if key != day else '✅ ') + store.DAY_SHORT[key], callback_data='kids:day:' + key)
             for key in DAYS[:4]],
            [B(('· ' if key != day else '✅ ') + store.DAY_SHORT[key], callback_data='kids:day:' + key)
             for key in DAYS[4:]]]
    for slug, child in (data.get('children') or {}).items():
        if child.get('week'):
            rows.append([B('Забрал: ' + child.get('name', slug), callback_data='kids:done:' + slug)])
    rows.append([B('Пауза напоминаний' if enabled else 'Включить напоминания',
                   callback_data='kids:pause' if enabled else 'kids:enable')])
    return M(rows)


async def panel(update, context):
    if not owner_allowed(update):
        await update.message.reply_text('Расписание детей доступно только владельцу.')
        return
    moment = store.local_now()
    data = await asyncio.to_thread(store.ensure, update.effective_user.id)
    day = DAYS[moment.weekday()]
    text = report.day_text(data, day, moment)
    if not data.get('enabled', True):
        text += '\n\nНапоминания на паузе.'
    await update.message.reply_text(text, reply_markup=keyboard(data, day, data.get('enabled', True)))


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
                         reply_markup=keyboard(data, day, data.get('enabled', True)))
        return
    if operation in ('pause', 'enable'):
        data['enabled'] = operation == 'enable'
        await asyncio.to_thread(store.save, owner, data)
        await send_reply(update, 'Напоминания детей: ' + ('включены' if data['enabled'] else 'на паузе') + '.',
                         reply_markup=keyboard(data, 'mon', data['enabled']))
        return
    if operation == 'done':
        child = tail[0] if tail else ''
        name = ((data.get('children') or {}).get(child) or {}).get('name', 'ребёнок')
        today = moment.date().isoformat()
        data.setdefault('sent', {}).setdefault(today, {}).setdefault(child, {}).update({'before': True, 'end': True})
        await asyncio.to_thread(store.save, owner, data)
        await send_reply(update, 'Отмечено: забрал ' + name + '. Напоминания по нему на сегодня закрыты.')
