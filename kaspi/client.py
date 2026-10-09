"""Bounded Kaspi API client. Credentials and response bodies must never be logged."""
import json
import os
import re
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
class KaspiError(Exception):
    pass
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def request(params=None, payload=None):
    token = os.getenv("KASPI_API_TOKEN","").strip()
    if not token or any(c.isspace() for c in token):
        raise KaspiError("Проверь API-токен в настройках Railway.")
    url="https://kaspi.kz/shop/api/v2/orders"
    if params:url+="?"+urlencode(params)
    req=Request(url, data=json.dumps(payload).encode() if payload is not None else None,
                headers={"X-Auth-Token":token,"Content-Type":"application/vnd.api+json"})
    try:
        with build_opener(NoRedirect()).open(req,timeout=20) as response:
            raw=response.read(2*1024*1024+1)
        if len(raw)>2*1024*1024:raise ValueError()
        result=json.loads(raw)
        if not isinstance(result,dict) or "data" not in result:raise ValueError()
        return result["data"]
    except HTTPError as error:
        code=error.code
        error.close()
        if payload is not None:
            raise KaspiError("Изменение не подтверждено. Проверь заказ в кабинете Kaspi перед повторной попыткой.") from None
        if code in (401,403):
            raise KaspiError("Kaspi отклонил доступ. Проверь API-токен.") from None
        raise KaspiError("Kaspi сейчас не ответил успешно. Попробуй позже.") from None
    except (URLError,TimeoutError,OSError,ValueError,TypeError):
        message=("Результат изменения неизвестен. Проверь заказ в кабинете Kaspi; автоматического повтора нет."
                 if payload is not None else "Не удалось получить корректный ответ Kaspi. Попробуй позже.")
        raise KaspiError(message) from None

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
