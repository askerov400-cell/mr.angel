"""Owner-scoped order cards and expiring one-use confirmations."""
import asyncio
import os
import secrets
import time
from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M
from kaspi.client import STATES, STATUS, REASONS, orders, detail, change, KaspiError

def allowed(update):
    return bool(update.effective_user and update.effective_chat
        and update.effective_chat.type=="private"
        and str(update.effective_user.id)==os.getenv("KASPI_OWNER_ID","")
        and update.effective_chat.id==update.effective_user.id)

def keyboard():
    return M([[B("📊 Сводка за сегодня",callback_data="kaspi:stats")]]+[[B(title,callback_data="kaspi:list:"+state+":0")] for state,title in STATES.items()])

def card(row):
    amount=str(row.get("totalPrice") or "—").replace("\n"," ")[:50]
    return f"Заказ № {row['code']}\nСумма: {amount} ₸\nСтатус: {STATUS.get(row['status'],'Неизвестен')}"

def put(context,row):
    cards=context.user_data.setdefault("kaspi_cards",{})
    now=time.monotonic()
    for key in list(cards):
        if now-cards[key]["at"]>600:cards.pop(key)
    while len(cards)>=20:cards.pop(next(iter(cards)))
    nonce=secrets.token_hex(8)
    cards[nonce]={"row":row,"at":now}
    return nonce

async def panel(update,context):
    if not allowed(update):
        if update.message:await update.message.reply_text("Раздел Kaspi доступен только владельцу магазина.")
        return
    context.user_data.pop("interface_input",None)
    context.user_data.pop("kaspi_pending",None)
    await update.message.reply_text("Kaspi\nПросмотр, приём и отмена заказов.\nСписки за последние 7 дней. Выбери раздел:",reply_markup=keyboard())

async def callback(update,context):
    q=update.callback_query
    await q.answer()
    if not allowed(update):return
    parts=q.data.split(":")
    try:
        if q.data=="kaspi:stats":
            from kaspi.statistics import summary
            await q.message.reply_text(await summary(),reply_markup=keyboard())
            return
        if len(parts)==4 and parts[1]=="list":
            state,page=parts[2],int(parts[3])
            if state not in STATES or not 0<=page<=999:return
            rows=await asyncio.to_thread(orders,state,page)
            buttons=[]
            lines=[f"Kaspi — {STATES[state]}\nПоследние 7 дней, страница {page+1}."]
            for row in rows:
                lines.append(card(row))
                token=put(context,row)
                buttons.append([B("Открыть № "+row["code"],callback_data="kaspi:open:"+token)])
            if not rows:lines.append("Заказов на этой странице нет.")
            nav=[]
            if page>0:nav.append(B("Назад",callback_data=f"kaspi:list:{state}:{page-1}"))
            if len(rows)==10 and page<999:nav.append(B("Далее",callback_data=f"kaspi:list:{state}:{page+1}"))
            if nav:buttons.append(nav)
            await q.message.reply_text("\n\n".join(lines),reply_markup=M(buttons+list(keyboard().inline_keyboard)))
            return
        if len(parts)==3 and parts[1]=="confirm":
            pending=context.user_data.get("kaspi_pending")
            if not pending or pending["nonce"]!=parts[2] or time.monotonic()-pending["at"]>600:
                await q.message.reply_text("Подтверждение истекло или уже использовано.");return
            # Consume synchronously before any network operation, including double taps.
            context.user_data.pop("kaspi_pending",None)
            result=await asyncio.to_thread(change,pending["row"],pending["action"],pending["reason"])
            await q.message.reply_text("Kaspi подтвердил изменение.\n"+card(result),reply_markup=keyboard())
            return
        if len(parts)<3:return
        entry=context.user_data.get("kaspi_cards",{}).get(parts[2])
        if not entry or time.monotonic()-entry["at"]>600:
            await q.message.reply_text("Карточка устарела. Открой список заново.",reply_markup=keyboard());return
        action=parts[1]
        if action not in ("open","accept","cancel","reason"):return
        row=await asyncio.to_thread(detail,entry["row"]["code"])
        entry["row"]=row
        if action=="open":
            context.user_data.pop("kaspi_pending",None)
            buttons=[]
            if row["status"]=="APPROVED_BY_BANK":buttons.append([B("Принять заказ",callback_data="kaspi:accept:"+parts[2])])
            if row["status"] in ("APPROVED_BY_BANK","ACCEPTED_BY_MERCHANT"):
                buttons.append([B("Отменить заказ",callback_data="kaspi:cancel:"+parts[2])])
            await q.message.reply_text(card(row),reply_markup=M(buttons+list(keyboard().inline_keyboard)));return
        if action=="cancel":
            await q.message.reply_text(card(row)+"\nВыбери причину отмены:",reply_markup=M([
                [B(label,callback_data=f"kaspi:reason:{parts[2]}:{i}")] for i,label in enumerate(REASONS.values())]));return
        reason=None
        if action=="reason":
            if len(parts)!=4 or parts[3] not in ("0","1","2"):return
            reason=list(REASONS)[int(parts[3])]
            action="cancel"
        permitted=("APPROVED_BY_BANK",) if action=="accept" else ("APPROVED_BY_BANK","ACCEPTED_BY_MERCHANT")
        if row["status"] not in permitted:
            await q.message.reply_text("Действие недоступно в текущем статусе.");return
        nonce=secrets.token_hex(8)
        context.user_data["kaspi_pending"]={"nonce":nonce,"at":time.monotonic(),"row":row.copy(),"action":action,"reason":reason}
        label="Принять" if action=="accept" else "Отменить"
        description=card(row)+"\n"+label+" этот заказ?"
        if reason:description+="\nПричина: "+REASONS[reason]
        await q.message.reply_text(description,reply_markup=M([
            [B("Подтвердить: "+label,callback_data="kaspi:confirm:"+nonce)],
            [B("Вернуться к заказу",callback_data="kaspi:open:"+parts[2])]]))
    except KaspiError as error:
        await q.message.reply_text(str(error),reply_markup=keyboard())
    except ValueError:
        return
