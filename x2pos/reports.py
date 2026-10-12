"""Sequential, owner-branch sales totals. Never retain raw orders or payments."""
import threading
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from x2pos import client

class Busy(client.X2Error):
    pass


GATE = threading.Lock()
PAGE_SIZE = 500
TIME_LIMIT = 180

def amount(value):
    parsed = client.number(value)
    if parsed == 'нет данных':
        raise client.X2Error('В продаже отсутствует итоговая сумма. Полный отчёт не рассчитан.')
    return Decimal(parsed)

def local_day(value):
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(ZoneInfo('Asia/Qyzylorda')).date()
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise client.X2Error('Не удалось проверить дату продажи. Полный отчёт не рассчитан.') from None

def empty_day():
    return {'total': Decimal(0), 'sales_total': Decimal(0), 'returns_total': Decimal(0),
            'sales_count': 0, 'returns_count': 0, 'canceled_count': 0,
            'cost_fifo': Decimal(0), 'cost_average': Decimal(0),
            'hours': [Decimal(0) for _ in range(24)]}


def costs(row, flag):
    items = row.get('order_items')
    if isinstance(items, dict):
        items = list(items.values())
    values = {}
    for name, field in (('cost_fifo', 'buy_total_fifo'), ('cost_average', 'buy_total_average')):
        try:
            if not isinstance(items, list) or not items:
                raise ValueError()
            parts = [amount(item.get(field)) for item in items if isinstance(item, dict)]
            if len(parts) != len(items) or any((v > 0 if flag == '1' else v < 0) for v in parts):
                raise ValueError()
            values[name] = sum(parts, Decimal(0))
        except (client.X2Error, ValueError):
            values[name] = None
    return values


def sales(start, end, daily=False, sparse=False):
    if end < start:
        raise ValueError('End before start')
    if not GATE.acquire(blocking=False):
        raise Busy('Отчёт продаж уже загружается. Дождись его завершения.')
    try:
        deadline = time.monotonic() + TIME_LIMIT
        access = client.employee()
        by_day = { (start+timedelta(days=i)).isoformat(): empty_day()
                  for i in range((end-start).days+1) } if daily and not sparse else {}
        total = sales_total = returns_total = Decimal(0)
        sales_count = returns_count = canceled_count = 0
        seen = set()
        page = 1
        while True:
            if time.monotonic() >= deadline:
                raise client.X2Error('X2POS не успел передать все страницы. Полный отчёт не рассчитан; попробуй позже.')
            data = client.request('/orders', {
                'branch_id': access['branch'], 'date_start': start.isoformat(),
                'date_end': end.isoformat(), 'per_page': PAGE_SIZE, 'page': page})
            if not isinstance(data, dict) or data.get('status') != 'success':
                raise client.X2Error('X2POS не подтвердил получение продаж. Полный отчёт не рассчитан.')
            rows = data.get('orders')
            if not isinstance(rows, list) or len(rows) > 1000:
                raise client.X2Error('Неизвестный формат списка продаж. Полный отчёт не рассчитан.')
            if not rows:
                break
            for row in rows:
                if not isinstance(row, dict):
                    raise client.X2Error('Некорректная продажа X2POS. Полный отчёт не рассчитан.')
                oid = client.identifier(row.get('id'))
                if oid in seen:
                    raise client.X2Error('X2POS повторил документы при чтении страниц. Полный отчёт не рассчитан.')
                seen.add(oid)
                if client.identifier(row.get('branch_id')) != access['branch']:
                    raise client.X2Error('В ответе продажи другого филиала. Полный отчёт не рассчитан.')
                day = local_day(row.get('order_date'))
                if not start <= day <= end:
                    raise client.X2Error('X2POS вернул продажи вне выбранного периода. Полный отчёт не рассчитан.')
                status = row.get('status')
                if not isinstance(status, str) or not status:
                    raise client.X2Error('В продаже отсутствует статус. Полный отчёт не рассчитан.')
                if status == 'canceled':
                    canceled_count += 1
                    if daily:
                        by_day.setdefault(day.isoformat(),empty_day())['canceled_count'] += 1
                    continue
                if str(row.get('is_deleted', '0')) != '0':
                    raise client.X2Error('В ответе удалённый документ; правила его учёта не подтверждены.')
                flag = str(row.get('is_return'))
                if flag not in ('0', '1'):
                    raise client.X2Error('Не удалось определить возврат. Полный отчёт не рассчитан.')
                value = amount(row.get('total'))
                if (flag == '1' and value > 0) or (flag == '0' and value < 0):
                    raise client.X2Error('Знак суммы не соответствует типу продажи. Полный отчёт не рассчитан.')
                if daily:
                    bucket = by_day.setdefault(day.isoformat(),empty_day())
                    bucket['total'] += value
                    prefix = 'returns' if flag == '1' else 'sales'
                    bucket[prefix+'_total'] += value
                    bucket[prefix+'_count'] += 1
                    stamp = datetime.fromisoformat(row['order_date'].replace('Z', '+00:00'))
                    if stamp.tzinfo is None:
                        stamp = stamp.replace(tzinfo=timezone.utc)
                    bucket['hours'][stamp.astimezone(ZoneInfo('Asia/Qyzylorda')).hour] += value
                    for name, cost in costs(row, flag).items():
                        bucket[name] = None if cost is None or bucket[name] is None else bucket[name]+cost
                total += value
                if flag == '1':
                    returns_count += 1
                    returns_total += value
                else:
                    sales_count += 1
                    sales_total += value
            page += 1
        result = {'total': total, 'sales_total': sales_total, 'returns_total': returns_total,
                'sales_count': sales_count, 'returns_count': returns_count,
                'canceled_count': canceled_count}
        if daily:
            result['daily'] = by_day
        return result
    finally:
        GATE.release()

def money(value):
    return f'{value:,.2f}'.replace(',', ' ').replace('.', ',')

def format_report(start, end, result):
    future = '\nБудущие даты не являются прогнозом продаж.' if end > datetime.now(ZoneInfo('Asia/Qyzylorda')).date() else ''
    financial = ''
    if 'expenses_total' in result:
        from x2pos.analytics import finance_text
        financial = '\n\n' + finance_text(result)
    return (f'Статистика продаж\nПериод: {start:%d.%m.%Y} — {end:%d.%m.%Y}\n'
            f'Дней: {(end-start).days+1} (обе даты включены)\n\n'
            f'Продажи: {money(result["sales_total"])} ₸ · чеков: {result["sales_count"]}\n'
            f'Возвраты: {money(result["returns_total"])} ₸ · документов: {result["returns_count"]}\n'
            f'Итого с возвратами: {money(result["total"])} ₸\n'
            f'Отменённые исключены: {result["canceled_count"]}\n\n'
            'Источник: X2POS, выбранный филиал. Скидки уже учтены в итогах чеков.' + financial + future)
