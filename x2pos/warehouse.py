"""Точные остатки склада X2POS: количества и стоимость по подтверждённым данным."""
from decimal import Decimal, InvalidOperation

from x2pos import client
from x2pos.reports import money

PAGE = 8
MAX_PAGES = 40


def _dec(value):
    try:
        number = Decimal(str(value))
        return number if number.is_finite() and abs(number) <= Decimal("1e15") else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def collect():
    """Каталог всех страниц и остатки филиала; отсутствие записи не считается нулём."""
    access = client.employee()
    rows, seen, page = [], set(), 1
    while page <= MAX_PAGES:
        batch = client.products(page)
        if not batch:
            break
        for row in batch:
            if row["id"] not in seen:
                seen.add(row["id"])
                rows.append(row)
        if len(batch) < 50:
            break
        page += 1
    quantities = client.stock(access["branch"])
    known = missing = unpriced = 0
    units = retail = wholesale = Decimal(0)
    for row in rows:
        quantity = _dec(quantities[row["id"]]) if row["id"] in quantities else None
        row["quantity"] = quantity
        if quantity is None:
            missing += 1
            continue
        known += 1
        units += quantity
        cost_retail, cost_wholesale = _dec(row.get("retail")), _dec(row.get("wholesale"))
        if cost_retail is None and cost_wholesale is None:
            unpriced += 1
        if cost_retail is not None:
            retail += quantity * cost_retail
        if cost_wholesale is not None:
            wholesale += quantity * cost_wholesale
    stray = len([key for key in quantities if key not in seen])
    return {"branch": access["branch"], "rows": rows, "known": known, "missing": missing,
            "unpriced": unpriced, "units": units, "retail": retail, "wholesale": wholesale,
            "stray": stray}


def summary_text(data):
    lines = ["Остаток на складе",
             "Позиций в каталоге: " + str(len(data["rows"])) +
             " · с остатком: " + str(data["known"]) +
             " · без данных: " + str(data["missing"])]
    if data["known"] == 0:
        lines.append("Известных остатков нет: X2POS не вернул количества по этому филиалу.")
    else:
        lines.append("Всего единиц: " + money(data["units"]).replace(",00", ""))
        lines.append("Стоимость по известным остаткам:")
        lines.append("Розничная: " + money(data["retail"]) + " ₸")
        lines.append("Оптовая: " + money(data["wholesale"]) + " ₸")
    lines.append("Закупочная: нет данных — X2POS не отдаёт себестоимость склада.")
    if data["missing"]:
        lines.append("Позиции без записи остатка не считаются нулём и в сумму не входят.")
    if data.get("unpriced"):
        lines.append("Без цены в каталоге: " + str(data["unpriced"]) + " — в стоимость не вошли.")
    if data.get("stray"):
        lines.append("В остатках есть " + str(data["stray"]) + " позиций вне каталога — не учтены.")
    return "\n".join(lines)


def list_text(data, page=0):
    rows = data["rows"]
    pages = max(1, (len(rows) + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    lines = ["Остаток на складе · товары",
             "Страница " + str(page + 1) + " из " + str(pages)]
    chunk = rows[page * PAGE:(page + 1) * PAGE]
    if not chunk:
        lines.append("Позиций нет.")
    for row in chunk:
        title = row["name"] + (" · " + row["variation"] if row["variation"] else "")
        quantity = "нет данных" if row["quantity"] is None else money(row["quantity"]).replace(",00", "")
        unit = (" " + row["unit"]) if row["unit"] else ""
        lines.append("• " + title[:60] + " — " + quantity + unit)
    return "\n".join(lines), pages
