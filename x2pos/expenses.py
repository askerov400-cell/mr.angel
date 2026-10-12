"""Complete credit-payment aggregates; no notes or counterparties retained."""
import os
import time
from datetime import timedelta
from decimal import Decimal
from x2pos import client, reports

def empty_day():
    return dict(expenses_total=Decimal(0),expenses_count=0,
                excluded_total=Decimal(0),excluded_count=0,
                unknown_total=Decimal(0),unknown_count=0,expense_categories={})

def category_ids():
    value=os.getenv('X2POS_EXPENSE_CATEGORY_IDS','').strip()
    return {client.identifier(v.strip()) for v in value.split(',')} if value else set()

def excluded_ids():
    value=os.getenv('X2POS_EXCLUDED_PAYMENT_CATEGORY_IDS','').strip()
    return {client.identifier(v.strip()) for v in value.split(',')} if value else set()

def fetch(start,end,sparse=False):
    if end<start: raise ValueError('End before start')
    if not reports.GATE.acquire(blocking=False):
        raise reports.Busy('Отчёт X2POS уже загружается. Дождись завершения.')
    try:
        access=client.employee()
        known=category_ids()
        excluded=excluded_ids()
        if known & excluded:raise client.X2Error('Категория X2POS одновременно в расходах и исключениях. Проверь настройки.')
        days={} if sparse else {(start+timedelta(days=i)).isoformat():empty_day() for i in range((end-start).days+1)}
        seen=set(); page=1; deadline=time.monotonic()+reports.TIME_LIMIT
        while True:
            if time.monotonic()>=deadline:
                raise client.X2Error('Расходы X2POS получены не полностью. Итог не рассчитан.')
            data=client.request('/payments',dict(operation='credit',branch_id=access['branch'],
                date_start=start.isoformat(),date_end=end.isoformat(),per_page=500,page=page))
            if not isinstance(data,dict) or data.get('status')!='success':
                raise client.X2Error('X2POS не подтвердил получение расходов.')
            rows=data.get('payments')
            if not isinstance(rows,list) or len(rows)>1000:
                raise client.X2Error('Неизвестный формат расходов X2POS.')
            if not rows:break
            for row in rows:
                if not isinstance(row,dict):raise client.X2Error('Некорректная выплата X2POS.')
                pid=client.identifier(row.get('id'))
                if pid in seen:raise client.X2Error('X2POS повторил выплаты между страницами.')
                seen.add(pid)
                if client.identifier(row.get('branch_id'))!=access['branch'] or row.get('operation')!='credit':
                    raise client.X2Error('Выплата другого филиала или типа операции.')
                day=reports.local_day(row.get('date_of_payment'))
                if not start<=day<=end:raise client.X2Error('Выплата вне выбранного периода.')
                deleted=str(row.get('is_deleted'))
                if deleted not in ('0','1'):raise client.X2Error('Неизвестный признак удаления выплаты.')
                if deleted=='1':continue
                value=-reports.amount(row.get('amount'))
                if value<0:raise client.X2Error('Неожиданный знак расхода X2POS.')
                bucket=days.setdefault(day.isoformat(),empty_day())
                # Refunds already reduce revenue; purchases are accounted in COGS.
                # A source account marks a money transfer, not an operating expense.
                linked=any(row.get(k) not in (None,'','0',0) for k in ('order_id','procurement_id','source_account_id'))
                uncertain=(str(row.get('is_returned'))!='0'
                    or row.get('return_of_payment_id') not in (None,'','0',0)
                    or row.get('is_debt_payment') not in (None,'','0',0)
                    or row.get('supplier_id') not in (None,'','0',0))
                cid=client.identifier(row['operation_type_id']) if row.get('operation_type_id') else None
                reversed_payment=(str(row.get('is_returned'))!='0' or row.get('return_of_payment_id') not in (None,'','0',0))
                explicit_exclusion=cid in excluded and not reversed_payment
                kind='excluded' if explicit_exclusion or (linked and not uncertain) else 'expenses' if cid in known and not uncertain else 'unknown'
                bucket[kind+'_total']+=value;bucket[kind+'_count']+=1
                if kind=='expenses':
                    bucket['expense_categories'][cid]=bucket['expense_categories'].get(cid,Decimal(0))+value
            page+=1
        return days
    finally:reports.GATE.release()

def report(start,end,sparse=False):
    # Each list is completed sequentially. No persistence until both succeed.
    result=reports.sales(start,end,daily=True,sparse=True) if sparse else reports.sales(start,end,daily=True)
    payments=fetch(start,end,sparse=True) if sparse else fetch(start,end)
    for day in set(result['daily']) | set(payments):
        row=result['daily'].setdefault(day,reports.empty_day())
        row.update(payments.get(day,empty_day()))
    from x2pos.analytics import aggregate
    result.update(aggregate(list(result['daily'].values())))
    return result
