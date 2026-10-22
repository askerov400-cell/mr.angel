"""Панель мотивации и кнопки под толчками."""
import asyncio
import os
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M

from motivation import store, texts
from memory.journal import send_reply


def owner_allowed(update):
    return (getattr(update, 'effective_chat', None) is not None
            and update.effective_chat.type == 'private'
            and str(update.effective_user.id) == (os.getenv('MOTIVATION_OWNER') or os.getenv('X2POS_OWNER_ID') or ''))


def controls(enabled):
    return M([[B('Пауза' if enabled else 'Включить', callback_data='mot:pause' if enabled else 'mot:enable')],
              [B('Прислать пример сейчас', callback_data='mot:test')]])


def summary(data, moment):
    plan = data.get('plan') or []
    left = [item for item in plan if not item.get('sent')]
    done = data.get('done') or {}
    lines = ['Мотивация\n', 'Сейчас ' + ('включена' if data.get('enabled', True) else 'на паузе') + '.',
             'Сообщений в день: 6 — спорт дважды, бизнес дважды, Хранитель и семья по разу.']
    if left:
        nxt = min(left, key=lambda item: item.get('at', ''))
        try:
            moment_local = datetime.fromisoformat(nxt['at']).astimezone(store.ZONE)
            lines.append('Следующее: ' + store.AREAS.get(nxt.get('area'), '') + ' в ' + moment_local.strftime('%H:%M') + '.')
        except (KeyError, ValueError):
            pass
    else:
        lines.append('На сегодня всё отправлено.')
    if done:
        lines.append('Отмечено сегодня: ' + ', '.join(store.AREAS.get(area, area) + ' — ' + str(count)
                                                     for area, count in done.items() if count))
    return '\n'.join(lines)


async def panel(update, context):
    if not owner_allowed(update):
        await update.message.reply_text('Команда доступна только владельцу.')
        return
    moment = store.local_now()
    data = await asyncio.to_thread(store.load, update.effective_user.id) or store.fresh(moment)
    if data.get('day') != moment.date().isoformat():
        data = store.fresh(moment, data)
    await update.message.reply_text(summary(data, moment), reply_markup=controls(data.get('enabled', True)))


async def callback(update, context):
    query = update.callback_query
    await query.answer()
    if not owner_allowed(update):
        return
    owner = update.effective_user.id
    _, operation, *tail = query.data.split(':')
    area = tail[0] if tail else ''
    moment = store.local_now()
    data = await asyncio.to_thread(store.load, owner) or store.fresh(moment)
    if data.get('day') != moment.date().isoformat():
        data = store.fresh(moment, data)
    if operation in ('pause', 'enable'):
        data['enabled'] = operation == 'enable'
        await asyncio.to_thread(store.save, owner, data)
        await send_reply(update, summary(data, moment), reply_markup=controls(data['enabled']))
        return
    if operation == 'test':
        await send_reply(update, texts.build('sport', 0))
        return
    if operation == 'done' and area in store.AREAS:
        done = data.setdefault('done', {})
        done[area] = int(done.get(area) or 0) + 1
        await asyncio.to_thread(store.save, owner, data)
        await asyncio.to_thread(store.remember, owner, area, moment)
        await send_reply(update, store.AREAS[area] + ': отмечено, всего сегодня ' + str(done[area]) + '.')
        return
    if operation == 'later' and area in store.AREAS:
        data['later'] = {'area': area, 'at': (moment + timedelta(hours=2)).isoformat(), 'sent': False}
        await asyncio.to_thread(store.save, owner, data)
        await send_reply(update, 'Вернусь к этому через два часа.')
        return
    if operation == 'skip' and area in store.AREAS:
        await send_reply(update, 'Пропущено. Без упрёков.')
        return
