"""Private-owner analytics context, separate from automatic personal memory."""
import asyncio
import time
import os
import re
import calendar
from datetime import datetime, date, timedelta
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


def llm_enabled():
    return os.getenv('X2POS_LLM_ENABLED','0') == '1'


def report_requested(text):
    text=text.casefold()
    if any(w in text for w in ('почему','причин','сравн','проанализ','объясн','совет','прогноз')):
        return False
    metrics=any(w in text for w in ('продаж','выруч','оборот','расход','прибыл','чек','возврат','себестоим'))
    request=any(w in text for w in ('покаж','скольк','дай','итог','отчёт','отчет','статистик','посчитай','рассчитай'))
    dated=any(w in text for w in (' за ','сегодня','вчера','месяц','недел')) or bool(re.search(r'\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4}',text))
    return metrics and (request or dated)


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
    months=('январ','феврал','март','апрел','мая','июн','июл','август','сентябр','октябр','ноябр','декабр')
    chosen=[i+1 for i,m in enumerate(months) if m in text]
    year_match=re.search(r'\b(\d{4})\b',text)
    year=int(year_match.group(1)) if year_match else end.year
    if chosen:
        first,last=chosen[0],chosen[-1]
        return date(year,first,1),date(year,last,calendar.monthrange(year,last)[1])
    if 'год' in text or 'года' in text:
        return date(year,1,1),end if year==end.year else date(year,12,31)
    if 'месяц' in text: return end.replace(day=1),end
    return end,end


async def direct_answer(owner,text):
    try:
        state,days,history=await asyncio.to_thread(store.read,owner)
        now=datetime.now(analytics.ZONE)
        if not state.get('last_success'):
            return 'X2POS: успешного фонового обновления ещё нет. Попробуй позже.'
        start,end=period(text,now)
        if end<start: return 'Конец периода не может быть раньше начала.'
        # Check bounds before iterating: no arbitrary length cap or giant allocations.
        if not days or start.isoformat()<min(days) or end.isoformat()>max(days):
            return 'В сохранённой истории нет полной выборки за этот период. Выбери его в «Статистика продаж» для чтения API.'
        chosen=[days.get((start+timedelta(days=i)).isoformat()) for i in range((end-start).days+1)]
        if any(r is None for r in chosen):
            return 'За этот период сохранённые данные неполные. Итог не рассчитан.'
        row=analytics.aggregate(chosen)
        updated=datetime.fromisoformat(state['last_success'].replace('Z','+00:00')).astimezone(analytics.ZONE)
        answer=(f'Аналитика бизнеса\nПериод: {start:%d.%m.%Y} — {end:%d.%m.%Y}\n'
            +analytics.day_text(end if start==end else None,row)+f'\nОбновлено: {updated:%d.%m.%Y %H:%M:%S} UTC+5.')
        if (now-updated).total_seconds()>600 or state.get('last_error'):
            answer+='\nДанные могут быть устаревшими: последнее обновление не подтверждено.'
        if start==end:
            result=analytics.comparison(days,end,hour=now.hour if end==now.date() else None)
            if result and result['percent'] is not None:
                answer+=f'\nК среднему за 4 предыдущих таких дня недели: {result["percent"]:+.1f}%.'
                if end==now.date(): answer+=f' Сравнены часы до {now.hour:02d}:00.'
        return answer+'\nИсточник: учёт X2POS. Расходы по дате выплаты. Причина изменений по этим данным неизвестна.'
    except ValueError:
        return 'Укажи существующие даты в формате ДД.ММ.ГГГГ или выбери период в календаре.'
    except Exception:
        return 'Хранилище аналитики сейчас недоступно. Попробуй позже.'
