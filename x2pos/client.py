"""Read-only X2POS API; never retain or log raw business responses."""
import json
import os
import re
from decimal import Decimal, InvalidOperation
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError

LIMIT = 4 * 1024 * 1024
ACTIONS = {"acceptance":"Приёмки", "move":"Перемещения",
           "writeoff":"Списания", "revision":"Ревизии"}

class X2Error(Exception):
    pass

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def identifier(value):
    value = str(value or "")
    if not re.fullmatch(r"[0-9]{1,20}", value):
        raise X2Error("Проверь идентификаторы X2POS в настройках.")
    return value

def text(value, limit=100):
    return " ".join(str(value or "").split())[:limit]

def number(value):
    if value is None:
        return "нет данных"
    try:
        n = Decimal(str(value))
        if not n.is_finite() or abs(n) > Decimal("1e15"):
            raise ValueError()
        return format(n.normalize(), "f")
    except (InvalidOperation, ValueError, TypeError):
        raise X2Error("X2POS вернул некорректные числовые данные.") from None

def request(path, params=None, extra=None):
    if path not in ("/employee", "/products", "/stock", "/procurements"):
        raise ValueError("Unsupported endpoint")
    key = os.getenv("X2POS_API_KEY", "").strip()
    if not key or not key.isascii() or any(c.isspace() for c in key):
        raise X2Error("Добавь X2POS_API_KEY в переменные Railway.")
    headers = {"API-KEY":key, "Accept":"application/json"}
    headers.update(extra or {})
    url = "https://x2pos.com/api" + path
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers=headers, method="GET")
    try:
        with build_opener(NoRedirect()).open(req, timeout=10) as response:
            raw = response.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise X2Error("Ответ X2POS слишком большой.")
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("status") == "error":
            raise X2Error("X2POS отклонил запрос. Проверь доступ в кабинете.")
        return data
    except HTTPError as error:
        code = error.code
        message = ("X2POS отклонил ключ или права доступа." if code in (401,403)
                   else f"X2POS вернул HTTP {code}.")
        raise X2Error(message) from None
    except (URLError, OSError):
        raise X2Error("X2POS не ответил за время проверки или соединение недоступно.") from None
    except (ValueError, UnicodeError):
        raise X2Error("X2POS вернул некорректный ответ.") from None

def employee():
    data = request("/employee")
    if not isinstance(data, dict):
        raise X2Error("Не удалось проверить доступ X2POS.")
    branch = identifier(os.getenv("X2POS_BRANCH_ID"))
    branches = data.get("branches")
    if not isinstance(branches, list) or branch not in [str(b) for b in branches]:
        raise X2Error("Выбранный филиал недоступен этому ключу.")
    return {"branch":branch, "user":identifier(data.get("user_id"))}

def products(page=1):
    if not isinstance(page, int) or not 1 <= page <= 10000:
        raise ValueError("Invalid page")
    data = request("/products", {"page":page})
    if not isinstance(data, list) or len(data) > 50:
        raise X2Error("Некорректный список товаров X2POS.")
    rows = []
    for product in data:
        if not isinstance(product, dict):
            raise X2Error("Некорректный товар X2POS.")
        variations = product.get("variations")
        if isinstance(variations, dict):
            variations = list(variations.values())
        if not isinstance(variations, list):
            raise X2Error("Неизвестный формат разновидностей X2POS.")
        for variation in variations:
            if not isinstance(variation, dict):
                raise X2Error("Некорректная разновидность X2POS.")
            rows.append({"id":identifier(variation.get("id")),
                         "name":text(product.get("product_name")),
                         "variation":text(variation.get("name")),
                         "retail":number(variation.get("retail_price")),
                         "wholesale":number(variation.get("wholesale_price")),
                         "unit":text(variation.get("measurement_unit"),30)})
    if len(rows) > 50:
        raise X2Error("Размер страницы X2POS отличается от документации.")
    return rows

def stock(branch):
    data = request("/stock", {"branch_id":identifier(branch)})
    if not isinstance(data, dict) or len(data) > 50000:
        raise X2Error("Некорректные остатки X2POS.")
    result = {}
    for key, row in data.items():
        if not isinstance(row, dict) or identifier(row.get("branch_id")) != branch:
            raise X2Error("Ответ содержит остатки другого филиала.")
        vid = identifier(row.get("variation_id"))
        if vid != str(key) or vid in result:
            raise X2Error("Некорректная связь остатков с товарами.")
        result[vid] = number(row.get("quantity"))
    return result

def catalog(page):
    access = employee()
    rows = products(page)
    quantities = stock(access["branch"])
    for row in rows:
        row["quantity"] = quantities.get(row["id"], "нет данных")
    return rows

def movements(action, page):
    if action not in ACTIONS or not isinstance(page,int) or not 1 <= page <= 10000:
        raise ValueError("Invalid query")
    access = employee()
    if identifier(os.getenv("X2POS_USER_ID")) != access["user"]:
        raise X2Error("X2POS_USER_ID не совпадает с пользователем ключа.")
    data = request("/procurements", {"action":action,"page":page,"per_page":10},
                   {"User-Id":access["user"],"Branch-Id":access["branch"]})
    if not isinstance(data,dict) or data.get("status") != "success":
        raise X2Error("X2POS не подтвердил получение движений.")
    rows = data.get("procurements")
    if not isinstance(rows,list) or len(rows)>10:
        raise X2Error("Некорректный список движений X2POS.")
    result = []
    for row in rows:
        if not isinstance(row,dict) or row.get("action") != action:
            raise X2Error("Ответ движений не соответствует выбранному разделу.")
        branch = identifier(row.get("branch_id"))
        if branch != access["branch"]:
            continue
        result.append({"id":identifier(row.get("id")), "status":text(row.get("status"),40),
                       "date":text(row.get("procurement_date"),30),
                       "quantity":number(row.get("total_quantity")),
                       "amount":number(row.get("total_amount"))})
    return {"rows":result, "has_next":len(rows)==10}
