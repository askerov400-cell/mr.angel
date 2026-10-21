"""Private-owner analytics context, separate from automatic personal memory."""
import asyncio
import time
import os
import re
import calendar
from datetime import datetime, date, timedelta
from x2pos import business_store as store, analytics, expenses, client
from x2pos.handlers import allowed

WORDS=('продаж','выруч','оборот','чек','возврат','бизнес','прибыл','марж','доход',
       'x2pos','х2пос','расход','реклам','просел','просад','динамик','аналити')

def is_request(text):
    """Текущее сообщение — бизнес-запрос, а не личная реплика."""
    from x2pos.month_ranking import requested
    value=(text or '').casefold()
    return any(word in value for word in WORDS) or requested(value)

def active(update,context,text):
    if not allowed(update) or getattr(context,'user_data',None) is None: return False
    if context.user_data.get('business_until',0)<=time.monotonic():
        context.user_data.pop('business_period',None)
    if is_request(text):
        context.user_data['business_until']=time.monotonic()+1800
    return context.user_data.get('business_until',0)>time.monotonic()

async def context(owner,text=''):
    try:
        if has_period(text):
            state,days,start,end=await requested_snapshot(owner,text)
            return (f'Запрошенный период {start:%d.%m.%Y} — {end:%d.%m.%Y}: полностью загружен из X2POS.\n'
                +analytics.context_text(state,days,[],datetime.now(analytics.ZONE)))
        state,days,history=await asyncio.to_thread(store.read,owner)
        return analytics.context_text(state,days,history,datetime.now(analytics.ZONE))
    except Exception:
        return 'X2POS: хранилище аналитики сейчас недоступно. Не выдумывай данные и не считай старые ответы текущими.'


def llm_enabled():
    return os.getenv('X2POS_LLM_ENABLED','0') == '1'

def has_period(text):
    text=text.casefold()
    return (any(w in text for w in ('сегодня','вчера','месяц','недел',' за ','январ','феврал','март','апрел','май','мая','мае','июн','июл','август','сентябр','октябр','ноябр','декабр'))
        or bool(re.search(r'\b\d{4}\b|\d{1,2}\.\d{1,2}\.\d{4}',text)))


def report_requested(text):
    text=text.casefold()
    from x2pos.month_ranking import requested
    if requested(text):return True
    if any(w in text for w in ('почему','причин','сравн','проанализ','объясн','совет','прогноз')):
        return False
    metrics=any(w in text for w in ('продаж','выруч','оборот','расход','прибыл','чек','возврат','себестоим'))
    request=any(w in text for w in ('покаж','скольк','дай','итог','отчёт','отчет','статистик','посчитай','рассчитай'))
    dated=any(w in text for w in (' за ','сегодня','вчера','месяц','недел')) or bool(re.search(r'\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4}',text))
    return (metrics and (request or dated)) or has_period(text)


def period(text, now):
    values=re.findall(r'\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4})\b',text)
    dates=[date.fromisoformat(v) if '-' in v else datetime.strptime(v,'%d.%m.%Y').date() for v in values]
    if dates: return dates[0],dates[-1]
    text=text.casefold()
    end=now.date()
    if 'вчера' in text: return end-timedelta(days=1),end-timedelta(days=1)
    amount=re.search(r'за\s+(\d+)\s+дн',text)
    if amount:
        count=int(amount.group(1))
        if count<1: raise ValueError()
        return end-timedelta(days=count-1),end
    if 'недел' in text: return end-timedelta(days=6),end
    if 'прошл' in text and 'месяц' in text:
        last=end.replace(day=1)-timedelta(days=1)
        return last.replace(day=1),last
    months=('январ','феврал','март','апрел','ма','июн','июл','август','сентябр','октябр','ноябр','декабр')
    chosen=[i+1 for i,m in enumerate(months) if (bool(re.search(r'\bма[йяе]\b',text)) if i==4 else m in text)]
    year_match=re.search(r'\b(\d{4})\b',text)
    year=int(year_match.group(1)) if year_match else end.year
    if chosen:
        first,last=chosen[0],chosen[-1]
        return date(year,first,1),date(year,last,calendar.monthrange(year,last)[1])
    if 'год' in text or 'года' in text:
        return date(year,1,1),end if year==end.year else date(year,12,31)
    if 'месяц' in text: return end.replace(day=1),end
    return end,end


async def requested_snapshot(owner,text):
    store.identity(owner)  # Authorize before any external request.
    now=datetime.now(analytics.ZONE)
    start,end=period(text,now)
    if end<start:raise ValueError('End before start')
    result=await asyncio.to_thread(expenses.report,start,end)
    updated=datetime.now(analytics.ZONE)
    return {'last_success':updated.isoformat()},result['daily'],start,end


async def direct_answer(owner,text):
    try:
        from x2pos import month_ranking
        if month_ranking.requested(text):
            store.identity(owner)
            now=datetime.now(analytics.ZONE)
            return await asyncio.to_thread(month_ranking.answer,text,now)
        state,days,start,end=await requested_snapshot(owner,text)
        row=analytics.aggregate(list(days.values()))
        updated=datetime.fromisoformat(state['last_success'])
        answer=(f'Аналитика бизнеса\nПериод: {start:%d.%m.%Y} — {end:%d.%m.%Y}\n'
            +analytics.day_text(end if start==end else None,row)
            +f'\nПолучено из X2POS: {updated:%d.%m.%Y %H:%M:%S} UTC+5.')
        if end>updated.date():answer+='\nБудущие даты не являются прогнозом.'
        return answer+'\nИсточник: учёт X2POS. Расходы по дате выплаты. Причина изменений по этим данным неизвестна.'
    except ValueError:
        return 'Укажи существующий период: например, «за июнь 2025» или «01.06.2025 — 30.06.2025». Конец не может быть раньше начала.'
    except client.X2Error as error:
        return str(error)+' Полный итог не рассчитан; попробуй повторить запрос.'
    except Exception:
        return 'Не удалось получить полный отчёт X2POS. Попробуй позже.'
