"""Напоминания о конце занятий детей."""
import asyncio
import logging
import os
from datetime import timedelta

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M

from kids import report, store

logger = logging.getLogger('guardian')
INTERVAL = 30


def buttons(child=''):
    return M([[B('Забрал', callback_data='kids:done:' + child),
               B('Расписание', callback_data='kids:day:today')]])


class Worker:
    def __init__(self, app, owner):
        self.app = app
        self.bot = app.bot
        self.owner = owner

    async def tick(self, moment=None):
        moment = moment or store.local_now()
        day = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')[moment.weekday()]
        data = await asyncio.to_thread(store.ensure, self.owner)
        if not data.get('enabled', True):
            return
        today = moment.date().isoformat()
        marks = data.setdefault('sent', {}).setdefault(today, {})
        for point in report.reminder_points(data, day, moment):
            child = point['child']
            state = marks.setdefault(child, {})
            last = point['last']
            stage = None
            if not state.get('before') and point['before'] <= moment <= point['before'] + timedelta(minutes=20):
                stage = 'before'
            elif not state.get('end') and point['end'] <= moment <= point['end'] + timedelta(minutes=20):
                stage = 'end'
            if not stage:
                continue
            if stage == 'before':
                text = ('У ' + last['name'] + ' заканчивается ' + last['subject'] + ' в ' + last['end'] + '. '
                        'Выезжай, чтобы забрать вовремя.')
            else:
                text = last['name'] + ': занятия закончились в ' + last['end'] + '. Пора забирать.'
            try:
                await self.bot.send_message(self.owner, text, reply_markup=buttons(child))
            except Exception as error:
                logger.warning('Дети: напоминание не отправлено (%s)', type(error).__name__)
                continue
            state[stage] = True
            await asyncio.to_thread(store.save, self.owner, data)

    async def run(self):
        logger.info('Дети: напоминания запущены')
        while True:
            try:
                await self.tick()
            except Exception as error:
                logger.warning('Дети: цикл не выполнен (%s)', type(error).__name__)
            await asyncio.sleep(INTERVAL)


def owners():
    value = os.getenv('KIDS_OWNER') or os.getenv('X2POS_OWNER_ID') or ''
    return [int(value)] if value.isdigit() and int(value) > 0 else []


async def start(app):
    workers = [Worker(app, owner) for owner in owners()]
    app.bot_data['kids_workers'] = workers
    app.bot_data['kids_tasks'] = [asyncio.create_task(worker.run()) for worker in workers]


async def stop(app):
    for task in app.bot_data.pop('kids_tasks', []):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
