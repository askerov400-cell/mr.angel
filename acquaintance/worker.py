"""Persistent scheduling with at-most-once automatic delivery."""
import asyncio
import logging
from datetime import timedelta
from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M
from telegram.error import Forbidden
from . import store, questions, schedule

logger = logging.getLogger('guardian')

def question_buttons(question_id):
    return M([[B('Ответить',callback_data='aq:answer:'+question_id),
               B('Пропустить',callback_data='aq:skip:'+question_id)],
              [B('Пауза',callback_data='aq:pause')]])

class Scheduler:
    def __init__(self, bot, client):
        self.bot, self.client = bot, client
        self.locks = {}
        self.planned = set()

    def lock(self, owner):
        return self.locks.setdefault(owner,asyncio.Lock())

    async def ensure_plan(self, owner):
        day = schedule.local_now().date()
        for target in (day,day+timedelta(days=1)):
            key = (owner,target)
            if key not in self.planned:
                rows = await store.action(owner,'plan',day=target.isoformat(),times=schedule.slots(target))
                if rows:
                    self.planned.add(key)
        self.planned = {key for key in self.planned if key[1]>=day}

    async def deliver(self, owner, manual=False):
        async with self.lock(owner):
            if not manual and not schedule.in_window(schedule.local_now()):
                return None
            await self.ensure_plan(owner)
            rows = await store.action(owner,'test' if manual else 'claim')
            if not rows:
                return None
            question = rows[0]
            question_id = question['id']
            try:
                text = await questions.generate(owner,self.client)
                if not text:
                    await store.action(owner,'skip',question_id)
                    return None
                prepared = await store.action(owner,'prepare',question_id,text=text)
                if not prepared:
                    return None
            except Exception as error:
                logger.warning('Знакомство: выбор вопроса не выполнен (%s)',type(error).__name__)
                await store.action(owner,'skip',question_id)
                return None
            try:
                sent = await asyncio.wait_for(self.bot.send_message(
                    chat_id=owner, text='Знакомство\n\n'+text+'\n\nОтветь через «Ответить» или ответом на это сообщение.',
                    reply_markup=question_buttons(question_id),
                ),timeout=30)
                await store.action(owner,'sent',question_id,message_id=sent.message_id)
                logger.info('Знакомство: вопрос отправлен')
                return prepared[0]
            except Forbidden:
                await store.action(owner,'skip',question_id)
                await store.action(owner,'pause')
                logger.warning('Знакомство: отправка выключена, чат недоступен')
                return None
            except Exception as error:
                # Delivery may have succeeded: never automatically send it again.
                logger.warning('Знакомство: исход отправки неизвестен (%s)',type(error).__name__)
                return None

    async def run(self):
        logger.info('Знакомство: планировщик запущен')
        while True:
            try:
                for owner in await store.enabled_owners():
                    try:
                        await self.ensure_plan(owner)
                        await self.deliver(owner)
                    except Exception as error:
                        logger.warning('Знакомство: цикл владельца не выполнен (%s)',type(error).__name__)
            except Exception as error:
                logger.warning('Знакомство: расписание недоступно (%s)',type(error).__name__)
            await asyncio.sleep(60)

async def start(app, client):
    worker = Scheduler(app.bot,client)
    app.bot_data['acquaintance_worker'] = worker
    app.bot_data['acquaintance_task'] = asyncio.create_task(worker.run())

async def stop(app):
    task = app.bot_data.pop('acquaintance_task',None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
