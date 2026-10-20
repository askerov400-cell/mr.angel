"""Bounded Kaspi API client. Credentials and response bodies must never be logged."""
import json
import os
import re
import logging
import ssl
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

STATES = {"NEW":"Новые", "SIGN_REQUIRED":"На подписании", "PICKUP":"Самовывоз",
          "DELIVERY":"Моя доставка", "KASPI_DELIVERY":"Kaspi Доставка", "ARCHIVE":"Архив"}
REASONS = {"BUYER_CANCELLATION_BY_MERCHANT":"Покупатель отменил заказ",
           "BUYER_NOT_REACHABLE":"Не удалось связаться с покупателем",
           "MERCHANT_OUT_OF_STOCK":"Товара нет в наличии"}
STATUS = {"APPROVED_BY_BANK":"Ожидает приёма", "ACCEPTED_BY_MERCHANT":"Принят",
          "COMPLETED":"Завершён","CANCELLED":"Отменён","CANCELLING":"Отменяется",
          "KASPI_DELIVERY_RETURN_REQUESTED":"Запрошен возврат","RETURNED":"Возвращён"}
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36")
MIN_INTERVAL = 1.0
RETRY_CODES = {"http_429", "http_500", "http_502", "http_503", "http_504", "timeout", "connection_reset"}
_pace_lock = threading.Lock()
_last_call = [0.0]


class KaspiError(Exception):
    def __init__(self, message, code="request_failed"):
        super().__init__(message)
        self.code=code

def failure(code, message, changing):
    logging.getLogger("guardian").warning("Kaspi: %s",code)
    if changing:
        message="Результат изменения не подтверждён. Проверь заказ в кабинете Kaspi; автоматического повтора нет."
    return KaspiError(message,code)

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def wait_turn():
    """Не долбить Kaspi: минимум секунда между запросами."""
    with _pace_lock:
        now = time.monotonic()
        pause = _last_call[0] + MIN_INTERVAL - now
        if pause > 0:
            time.sleep(pause)
        _last_call[0] = time.monotonic()


def _send(token, params, payload, changing):
    url="https://kaspi.kz/shop/api/v2/orders"
    if params:url+="?"+urlencode(params)
    req=Request(url, data=json.dumps(payload).encode() if payload is not None else None,
                headers={"X-Auth-Token":token,
                         "Content-Type":"application/vnd.api+json",
                         "Accept":"application/vnd.api+json",
                         "Accept-Language":"ru-RU,ru;q=0.9,en;q=0.8",
                         "User-Agent":USER_AGENT})
    try:
        with build_opener(NoRedirect()).open(req,timeout=20) as response:
            raw=response.read(2*1024*1024+1)
    except HTTPError as error:
        code=error.code
        error.close()
        message=("Kaspi отклонил доступ. Проверь API-токен." if code in (401,403)
                 else f"Kaspi вернул HTTP {code}. Попробуй позже.")
        raise failure(f"http_{code}",message,changing) from None
    except (TimeoutError,socket.timeout):
        raise failure("timeout","Kaspi не ответил за 20 секунд. Попробуй позже.",changing) from None
    except URLError as error:
        if isinstance(error.reason,(TimeoutError,socket.timeout)):
            code,message="timeout","Kaspi не ответил за 20 секунд. Попробуй позже."
        elif isinstance(error.reason,ssl.SSLError):
            code,message="tls","Не удалось установить защищённое соединение с Kaspi."
        elif isinstance(error.reason,socket.gaierror):
            code,message="dns","Railway не смог определить адрес сервера Kaspi."
        elif isinstance(error.reason,ConnectionRefusedError):
            code,message="connection_refused","Сервер Kaspi отклонил сетевое соединение с Railway."
        elif isinstance(error.reason,ConnectionResetError):
            code,message="connection_reset","Соединение с Kaspi было прервано сервером."
        else:
            code,message="network","Railway не смог соединиться с Kaspi. Проверяем доступ к серверу."
        raise failure(code,message,changing) from None
    except (OSError,ValueError,TypeError):
        raise failure("transport","Не удалось отправить запрос Kaspi. Проверь значение API-токена.",changing) from None
    if len(raw)>2*1024*1024:
        raise failure("response_too_large","Ответ Kaspi превышает допустимый размер.",changing)
    try:
        result=json.loads(raw)
    except (ValueError,UnicodeError):
        raise failure("invalid_json","Kaspi вернул ответ в неподдерживаемом формате.",changing) from None
    if not isinstance(result,dict) or "data" not in result:
        raise failure("invalid_schema","Kaspi вернул ответ без данных заказов.",changing)
    return result["data"]


def request(params=None, payload=None):
    token = os.getenv("KASPI_API_TOKEN","").strip()
    if not token or any(c.isspace() for c in token):
        raise KaspiError("Проверь API-токен в настройках Railway.")
    changing = payload is not None
    delays = (0,) if changing else (0, 1.5, 3.0)
    last = None
    for delay in delays:
        if delay:
            time.sleep(delay)
        wait_turn()
        try:
            return _send(token, params, payload, changing)
        except KaspiError as error:
            if changing or error.code not in RETRY_CODES:
                raise
            last = error
    raise last


def clean(item):
    try:
        if item.get("type")!="orders":raise ValueError()
        a=item["attributes"]
        code=str(a["code"])
        ident=item["id"]
        if not re.fullmatch(r"[0-9]{1,30}",code) or not isinstance(ident,str) or not 1<=len(ident)<=200:raise ValueError()
        return {"id":ident,"code":code,"totalPrice":a.get("totalPrice"),"status":a.get("status")}
    except (KeyError,TypeError,AttributeError,ValueError):
        raise KaspiError("Kaspi вернул некорректную карточку заказа.") from None

def orders(state,page=0, size=10, since=None):
    if state not in STATES or isinstance(page,bool) or not isinstance(page,int) or not 0<=page<=999:raise ValueError("Invalid query")
    if size not in (10,100):raise ValueError("Invalid size")
    now=datetime.now(timezone.utc)
    start=since or (now-timedelta(days=7))
    rows=request({"page[number]":page,"page[size]":size,"filter[orders][state]":state,
                  "filter[orders][creationDate][$ge]":int(start.timestamp()*1000),
                  "filter[orders][creationDate][$le]":int(now.timestamp()*1000)})
    if not isinstance(rows,list):raise KaspiError("Kaspi вернул неверный список заказов.")
    return [clean(r) for r in rows[:size]]

def detail(code):
    if not re.fullmatch(r"[0-9]{1,30}",str(code)):raise ValueError("Invalid code")
    rows=request({"filter[orders][code]":code})
    if not isinstance(rows,list) or len(rows)!=1:raise KaspiError("Заказ не найден однозначно.")
    row=clean(rows[0])
    if row["code"]!=code:raise KaspiError("Kaspi вернул другой заказ.")
    return row

def change(expected,action,reason=None):
    if action not in ("accept","cancel") or (action=="cancel" and reason not in REASONS):raise ValueError("Invalid action")
    current=detail(expected["code"])
    if current!=expected:
        raise KaspiError("Заказ изменился. Открой карточку заново и проверь её.")
    permitted=("APPROVED_BY_BANK",) if action=="accept" else ("APPROVED_BY_BANK","ACCEPTED_BY_MERCHANT")
    if current["status"] not in permitted:raise KaspiError("Этот заказ нельзя изменить в текущем статусе.")
    target="ACCEPTED_BY_MERCHANT" if action=="accept" else "CANCELLED"
    attributes={"code":current["code"],"status":target}
    if reason:attributes["cancellationReason"]=reason
    returned=request(payload={"data":{"type":"orders","id":current["id"],"attributes":attributes}})
    try:
        confirmed=clean(returned)
        if any(confirmed[k]!=v for k,v in {"id":current["id"],"code":current["code"],"status":target}.items()):raise ValueError()
    except (KaspiError,ValueError):
        raise KaspiError("Kaspi не подтвердил итоговый статус. Проверь заказ в кабинете, не повторяй действие автоматически.") from None
    return confirmed
