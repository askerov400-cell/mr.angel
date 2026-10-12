"""Deterministic sales analysis; inputs contain only computed aggregates."""
import json
import os
import calendar
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from x2pos.reports import money

ZONE = ZoneInfo('Asia/Qyzylorda')

def num(value): return Decimal(str(value))

def profit(row,cost):
    if (row.get('expenses_total') is None or row.get(cost) is None
            or row.get('unknown_count') is None or int(row['unknown_count'])>0):return None
    return num(row['total'])-num(row[cost])-num(row['expenses_total'])

def aggregate(rows):
    result={k:sum((num(r[k]) for r in rows),Decimal(0)) for k in
        ('total','sales_total','returns_total','sales_count','returns_count','canceled_count')}
    for key in ('cost_fifo','cost_average','expenses_total','expenses_count',
                'excluded_total','excluded_count','unknown_total','unknown_count'):
        result[key]=None if any(r.get(key) is None for r in rows) else sum((num(r[key]) for r in rows),Decimal(0))
    categories={}
    for r in rows:
        for key,value in r.get('expense_categories',{}).items():
            categories[key]=categories.get(key,Decimal(0))+num(value)
    result['expense_categories']=categories
    return result

def finance_text(row):
    if row.get('expenses_total') is None:return 'Расходы и чистая прибыль: нет полной выборки.'
    text=f'Расходы: {money(num(row["expenses_total"]))} ₸ ({int(row["expenses_count"])} выплат).'
    if row.get('expense_categories'):
        text+=' Категории: '+', '.join(f'{k}: {money(num(v))} ₸' for k,v in sorted(row['expense_categories'].items()))+'.'
    if row.get('excluded_count'):
        text+=f' Выплаты по чекам, закупкам и переводам исключены: {money(num(row["excluded_total"]))} ₸.'
    if row.get('unknown_count'):
        text+=f' Неопределённые выплаты: {money(num(row["unknown_total"]))} ₸ ({int(row["unknown_count"])}). Требуется классификация.'
    label='Чистая прибыль по данным X2POS' if os.getenv('X2POS_EXPENSES_COMPLETE')=='1' else 'Расчётная прибыль по данным X2POS'
    for key,method in (('cost_fifo','FIFO'),('cost_average','средняя')):
        value=profit(row,key)
        text+=f' {label} ({method}): {money(value)} ₸.' if value is not None else f' Прибыль ({method}): нет полных данных.'
    return text

def comparison(days, target, hour=None):
    prior = [days.get((target-timedelta(days=7*i)).isoformat()) for i in range(1,5)]
    current = days.get(target.isoformat())
    if not current or any(v is None for v in prior): return None
    def total(row):
        return sum((num(v) for v in row['hours'][:hour]),Decimal(0)) if hour is not None else num(row['total'])
    baseline = sum((total(v) for v in prior),Decimal(0))/4
    actual = total(current)
    percent = (actual-baseline)/baseline*100 if baseline>0 else None
    return {'actual':actual,'baseline':baseline,'percent':percent,
        'baseline_sales':sum(num(v['sales_count']) for v in prior)/4}

def day_text(day, metrics):
    count = int(metrics['sales_count'])
    avg = num(metrics['sales_total'])/count if count else Decimal(0)
    label=day.strftime('%d.%m.%Y') if day else 'Итоги периода'
    text = (f'{label}: итог с возвратами {money(num(metrics["total"]))} ₸; '
            f'продажи {money(num(metrics["sales_total"]))} ₸; чеков {count}; '
            f'средний чек {money(avg)} ₸; возвраты {money(num(metrics["returns_total"]))} ₸ '
            f'({metrics["returns_count"]} документов).')
    for key,label in (('cost_fifo','FIFO'),('cost_average','средняя')):
        cost = metrics.get(key)
        text += f' Себестоимость {label}: {money(num(cost))} ₸.' if cost is not None else f' Себестоимость {label}: нет полных данных.'
    return text + ' ' + finance_text(metrics)

def daily_summary(days, now):
    target=now.date()-timedelta(days=1)
    row=days.get(target.isoformat())
    if row is None: return None
    text='Аналитика бизнеса — сводка за вчера\n\n'+day_text(target,row)
    compare=comparison(days,target)
    if compare and compare['percent'] is not None:
        text+=f'\nИзменение к среднему за 4 предыдущих таких дня недели: {compare["percent"]:+.1f}%.'
    text+='\nИсточник: X2POS. Расходы — по дате выплаты; прибыль по данным учёта X2POS.'
    return text

def drop_alert(days, now):
    if not 12<=now.hour<=22: return None
    result=comparison(days,now.date(),hour=now.hour)
    if (not result or result['baseline']<10000 or result['baseline_sales']<3
            or result['percent'] is None or result['percent']>-30): return None
    return (f'Аналитика бизнеса — снижение продаж\n\nЗа {now:%d.%m.%Y} до {now.hour:02d}:00 '
            f'итог с возвратами {money(result["actual"])} ₸. '
            f'Снижение {abs(result["percent"]):.1f}% относительно среднего '
            f'{money(result["baseline"])} ₸ за те же часы 4 предыдущих таких дней недели.\n'
            'Это сигнал проверить ситуацию; причина по этим данным неизвестна.')

def context_text(state,days,history,now):
    stamp=state.get('last_success')
    if not stamp: return 'X2POS: успешного фонового обновления ещё нет. Не выдумывай показатели.'
    updated=datetime.fromisoformat(stamp.replace('Z','+00:00')).astimezone(ZONE)
    stale=(now-updated).total_seconds()>600
    text=(f'X2POS: последнее успешное обновление {updated:%d.%m.%Y %H:%M:%S} UTC+5. '
          + ('Данные устарели; это не текущие показатели. ' if stale else 'Обновление раз в 5 минут. ')
          + ('Последняя попытка обновления завершилась ошибкой. ' if state.get('last_error') else '')
          + 'Только выбранный филиал; источником являются полные выборки. '
          'История началась с последних 90 дней, старые дни сохраняются. '
          'Расходы и прибыль включены только при полной загрузке. Причины изменений неизвестны. '
          'Используй только рассчитанные profit_fifo/profit_average; null означает неизвестно. '
          'FIFO и средняя — разные оценки. Не вычитай закупки повторно. '
          'Реклама не выделена без подтверждённой категории.\n')
    text+=f'Покрытие снимка: {min(days) if days else "нет"} — {max(days) if days else "нет"}, {len(days)} дневных строк.\n'
    months=sorted({day[:7] for day in days})
    for month in months:
        year,number=map(int,month.split('-'))
        expected=calendar.monthrange(year,number)[1]
        keys=[f'{month}-{day:02d}' for day in range(1,expected+1)]
        available=[days[k] for k in keys if k in days]
        complete=len(available)==expected
        text+=f'Месяц {month}: {len(available)}/{expected} дней; '+('ПОЛНЫЙ МЕСЯЦ. ' if complete else 'НЕПОЛНЫЙ МЕСЯЦ, только доступные дни. ')
        text+=day_text(None,aggregate(available))+'\n'
    for target in (now.date(),now.date()-timedelta(days=1)):
        row=days.get(target.isoformat())
        if row: text+=day_text(target,row)+'\n'
    compact={d:{**{k:v for k,v in m.items() if k!='hours'},
        'profit_fifo':profit(m,'cost_fifo'),'profit_average':profit(m,'cost_average')} for d,m in sorted(days.items())}
    text+='Дневные агрегаты (даты без строки неизвестны, не нули):\n'+json.dumps(compact,ensure_ascii=False,default=str)+'\n'
    text+='Последние версии показателей: '+json.dumps([{k:v for k,v in r.items() if k in ('day','recorded_at')} for r in history],ensure_ascii=False)
    return text
