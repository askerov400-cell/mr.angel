"""Bounded live daily summary; never describes turnover as profit."""
import asyncio
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from kaspi.client import orders, STATES, STATUS, KaspiError

ZONE=ZoneInfo("Asia/Qyzylorda")

async def summary(day=None):
    now=datetime.now(ZONE)
    if day is None:
        start=now.replace(hour=0,minute=0,second=0,microsecond=0)
        end=None
        label=f"созданные сегодня ({now:%d.%m.%Y}, UTC+5)"
        tail="Заказы, созданные ранее и завершённые сегодня, сюда не входят."
    else:
        start=datetime(day.year,day.month,day.day,tzinfo=ZONE)
        end=start+timedelta(days=1)
        label=f"созданные {day:%d.%m.%Y} (UTC+5)"
        tail="Заказы, созданные в другие дни, сюда не входят."
    gate=asyncio.Semaphore(2)
    async def fetch(state):
        async with gate:
            return await asyncio.to_thread(orders,state,0,100,start,until=end)
    try:
        async with asyncio.timeout(65):
            groups=await asyncio.gather(*(fetch(state) for state in STATES))
    except TimeoutError:
        raise KaspiError("Сводка не готова: Kaspi отвечал слишком долго. Попробуй позже.") from None
    rows={row["id"]:row for group in groups for row in group}.values()
    counts=Counter(row["status"] for row in rows)
    total=Decimal(0)
    try:
        for row in rows:
            if row["status"]=="COMPLETED":
                value=Decimal(str(row["totalPrice"]))
                if not value.is_finite() or value<0:raise InvalidOperation()
                total+=value
    except (InvalidOperation,ValueError,TypeError):
        raise KaspiError("Kaspi вернул некорректную сумму; сводка не подтверждена.") from None
    lines=[f"Kaspi — заказы, {label}.",
           f"Всего в выборке: {sum(counts.values())}."]
    lines.extend(f"{STATUS.get(status,'Другой статус')}: {count}" for status,count in counts.items())
    lines.append(f"Сумма завершённых заказов из выборки: {total:,.2f} ₸. Это не прибыль.")
    lines.append(tail)
    if any(len(group)>=100 for group in groups):
        lines.append("Выборка неполная: достигнут лимит 100 заказов в одном из разделов.")
    return "\n".join(lines)
