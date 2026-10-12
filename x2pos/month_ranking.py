"""Deterministic month ranking over complete sequential API lists."""
import calendar
import re
from datetime import date,timedelta
from x2pos import analytics,expenses,reports

def requested(text):
    text=text.casefold().replace('ё','е')
    return ('месяц' in text and any(w in text for w in
        ('самый','самым','самого','наиболее','лучший','лучшим','максималь','больше всего','большей','лидер','доходней','прибыльней')))

def next_month(day):
    return day.replace(year=day.year+1,month=1,day=1) if day.month==12 else day.replace(month=day.month+1,day=1)

def bounds(text,now):
    normalized=text.casefold().replace('ё','е')
    if any(w in normalized for w in ('все время','всю историю','все годы','всю доступную')):
        return date.min,now.date()
    if re.search(r'\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4}',text):
        from x2pos.dialogue import period
        return period(text,now)
    year=re.search(r'\b(\d{4})\b',text)
    if year:
        y=int(year.group(1))
        return date(y,1,1),min(date(y,12,31),now.date())
    return date.min,now.date()

def months(days,start,end,now):
    if not days:return {}
    first=date.fromisoformat(min(days)).replace(day=1)
    first=max(first,start.replace(day=1) if start.day==1 else next_month(start))
    last_limit=min(end,now.date())
    last=last_limit.replace(day=1)
    if last_limit.day!=calendar.monthrange(last_limit.year,last_limit.month)[1] or last==now.date().replace(day=1):
        last=last-timedelta(days=1)
    grouped={}
    for day,row in days.items():grouped.setdefault(day[:7],[]).append(row)
    result={}
    while first<=last:
        key=f'{first.year:04d}-{first.month:02d}'
        rows=grouped.get(key)
        if not rows:
            row=reports.empty_day();row.update(expenses.empty_day());rows=[row]
        result[key]=analytics.aggregate(rows)
        first=next_month(first)
    return result

def format_ranking(rows,days,text,now):
    if not rows:return 'В доступной истории X2POS нет завершённых месяцев для сравнения. Текущий месяц не ранжируется до его завершения.'
    text_lower=text.casefold()
    revenue=any(w in text_lower for w in ('выруч','продаж','оборот')) and not any(w in text_lower for w in ('прибыл','доходн'))
    out=(f'Самый доходный месяц — сравнение X2POS\n'
        f'Доступные документы: {min(days)} — {max(days)}.\n'
        f'Сравнены полные месяцы: {min(rows)} — {max(rows)} ({len(rows)}).\n'
        'Текущий незавершённый месяц исключён.\n')
    criteria=[('Выручка с возвратами',lambda r:analytics.num(r['total']))] if revenue else [
        ('Чистая прибыль FIFO',lambda r:analytics.profit(r,'cost_fifo')),
        ('Чистая прибыль по средней',lambda r:analytics.profit(r,'cost_average'))]
    for label,metric in criteria:
        values={m:metric(row) for m,row in rows.items()}
        valid={m:v for m,v in values.items() if v is not None}
        missing=len(values)-len(valid)
        if not valid:
            out+=f'\n{label}: нет полных данных ни за один месяц.';continue
        best=max(valid.values());winners=sorted(m for m,v in valid.items() if v==best)
        name=', '.join(winners[:5])+ (f' и ещё {len(winners)-5}' if len(winners)>5 else '')
        out+=f'\n{label}: {name} — {reports.money(best)} ₸.'
        if len(winners)>1:out+=' Одинаковый результат.'
        if missing:out+=f' Лучший среди рассчитанных; {missing} месяцев с неполными данными. Абсолютный лидер за всё время не подтверждён.'
        elif best<0:out+=' Все сравниваемые месяцы убыточны; это наименьший убыток.'
    return out+f'\n\nПолучено из X2POS: {now:%d.%m.%Y %H:%M:%S} UTC+5. Расходы по дате выплаты. Сравнение по всей доступной API истории выбранного филиала в указанном диапазоне.'

def answer(text,now):
    start,end=bounds(text,now)
    if end<start:raise ValueError('End before start')
    result=expenses.report(start,end,sparse=True)
    days=result['daily']
    return format_ranking(months(days,start,end,now),days,text,now)
