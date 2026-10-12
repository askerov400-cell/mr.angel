"""Five-minute background sync and deduplicated owner notifications."""
import asyncio
import logging
import time
from datetime import datetime,timedelta
from x2pos import reports, expenses, business_store as store, analytics

logger=logging.getLogger('guardian')

class Monitor:
    def __init__(self,bot):
        self.bot=bot
        self.failures=0

    async def notify(self,kind,day,text):
        owner,_=store.identity()
        if not await asyncio.to_thread(store.claim,kind,day): return False
        # Claim before delivery: unknown send result never triggers duplicate sends.
        try:
            await asyncio.wait_for(self.bot.send_message(chat_id=owner,text=text),30)
            logger.info('X2POS: уведомление %s отправлено',kind)
        except Exception as error:
            logger.warning('X2POS: исход отправки %s неизвестен (%s)',kind,type(error).__name__)
        return True

    async def tick(self,now=None):
        now=now or datetime.now(analytics.ZONE)
        first=now.date()-timedelta(days=89)
        try:
            result=await asyncio.to_thread(expenses.report,first,now.date())
            await asyncio.to_thread(store.save,result['daily'])
        except reports.Busy:
            return
        except Exception as error:
            self.failures+=1
            logger.warning('X2POS: обновление аналитики не завершено (%s)',type(error).__name__)
            await asyncio.to_thread(store.error)
            if self.failures>=3:
                await self.notify('failure',now.date(),
                    'Аналитика бизнеса: X2POS не обновился 3 раза подряд. '
                    'Последние сохранённые данные остаются доступны, но могут быть устаревшими.')
            return
        self.failures=0
        logger.info('X2POS: 90 дневных агрегатов обновлены')
        days=result['daily']
        if 9<=now.hour<22:
            summary=analytics.daily_summary(days,now)
            if summary: await self.notify('daily',now.date(),summary)
        warning=analytics.drop_alert(days,now)
        if warning: await self.notify('drop',now.date(),warning)

    async def run(self):
        logger.info('X2POS: мониторинг каждые 5 минут запущен')
        while True:
            started=time.monotonic()
            try: await self.tick()
            except Exception as error:
                logger.warning('X2POS: цикл мониторинга не завершён (%s)',type(error).__name__)
            await asyncio.sleep(max(5,300-(time.monotonic()-started)))

async def start(app):
    store.identity()
    app.bot_data['business_monitor']=Monitor(app.bot)
    app.bot_data['business_task']=asyncio.create_task(app.bot_data['business_monitor'].run())

async def stop(app):
    task=app.bot_data.pop('business_task',None)
    if task:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
