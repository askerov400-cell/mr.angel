"""Планировщик мотивации: шесть сообщений в день в окне 09:00-22:00."""
import asyncio
import logging
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M

from motivation import store, texts

logger = logging.getLogger('guardian')
INTERVAL = 45
IDLE = 30 * 60


def buttons(area):
    return M([[B('Сделал', callback_data='mot:done:' + area),
               B('Через 2 часа', callback_data='mot:later:' + area)],
              [B('Пропустить', callback_data='mot:skip:' + area)]])


class Worker:
    def __init__(self, app, owner):
        self.app = app
        self.bot = app.bot
        self.owner = owner

    def idle(self, moment):
        last = self.app.bot_data.get('last_activity', {}).get(self.owner, 0)
        return moment.timestamp() - last >= IDLE

    async def tick(self, moment=None):
        moment = moment or store.local_now()
        data = await asyncio.to_thread(store.load, self.owner) or store.fresh(moment)
        if data.get('day') != moment.date().isoformat():
            data = store.fresh(moment, data)
        if not data.get('enabled') or not store.in_window(moment):
            await asyncio.to_thread(store.save, self.owner, data)
            return
        rows = store.due(data, moment)
        if not rows:
            await asyncio.to_thread(store.save, self.owner, data)
            return
        overdue = 0.0
        try:
            overdue = (moment - datetime.fromisoformat(rows[0][1]['at'])).total_seconds()
        except (KeyError, ValueError):
            overdue = 0.0
        if not self.idle(moment) and overdue < 120 * 60:
            return
        kind, item = rows[0]
        area = item.get('area')
        if area not in store.AREAS:
            return
        try:
            await self.bot.send_message(self.owner, texts.build(area, (data.get('done') or {}).get(area, 0)),
                                        reply_markup=buttons(area))
        except Exception as error:
            logger.warning('Мотивация: отправка не выполнена (%s)', type(error).__name__)
            return
        item['sent'] = True
        if kind == 'later':
            data['later'] = None
        await asyncio.to_thread(store.save, self.owner, data)

    async def run(self):
        logger.info('Мотивация: планировщик запущен')
        while True:
            try:
                await self.tick()
            except Exception as error:
                logger.warning('Мотивация: цикл не выполнен (%s)', type(error).__name__)
            await asyncio.sleep(INTERVAL)


def owners():
    import os
    value = os.getenv('MOTIVATION_OWNER') or os.getenv('X2POS_OWNER_ID') or ''
    return [int(value)] if value.isdigit() and int(value) > 0 else []


async def start(app):
    made = [Worker(app, owner) for owner in owners()]
    app.bot_data['motivation_workers'] = made
    app.bot_data['motivation_tasks'] = [asyncio.create_task(worker.run()) for worker in made]


async def stop(app):
    for task in app.bot_data.pop('motivation_tasks', []):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
