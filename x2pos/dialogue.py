"""Private-owner analytics context, separate from automatic personal memory."""
import asyncio
import time
from datetime import datetime
from x2pos import business_store as store, analytics
from x2pos.handlers import allowed

WORDS=('продаж','выруч','оборот','чек','возврат','бизнес','прибыл','марж',
       'x2pos','х2пос','расход','реклам','просел','просад','динамик','аналити')

def active(update,context,text):
    if not allowed(update) or getattr(context,'user_data',None) is None: return False
    if any(word in text.casefold() for word in WORDS):
        context.user_data['business_until']=time.monotonic()+1800
    return context.user_data.get('business_until',0)>time.monotonic()

async def context(owner):
    try:
        state,days,history=await asyncio.to_thread(store.read,owner)
        return analytics.context_text(state,days,history,datetime.now(analytics.ZONE))
    except Exception:
        return 'X2POS: хранилище аналитики сейчас недоступно. Не выдумывай данные и не считай старые ответы текущими.'
