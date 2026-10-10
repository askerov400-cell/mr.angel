"""Owner-only X2POS views outside conversational memory and LLM."""
import asyncio
import os
from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M
from x2pos import client

def allowed(update):
    return bool(update.effective_user and update.effective_chat
        and update.effective_chat.type == "private"
        and str(update.effective_user.id) == os.getenv("X2POS_OWNER_ID","")
        and update.effective_user.id == update.effective_chat.id)

def keyboard():
    return M([[B("Проверить подключение",callback_data="x2pos:check")],
              [B("Товары и остатки",callback_data="x2pos:catalog:1:0")]]
             + [[B(title,callback_data=f"x2pos:move:{action}:1")]
                for action,title in client.ACTIONS.items()])

async def panel(update, context):
    if not allowed(update):
        await update.message.reply_text("X2POS доступен только владельцу магазина.")
        return
    context.user_data.pop("interface_input",None)
    await update.message.reply_text("X2POS\nТовары, цены, остатки и движения выбранного филиала.",
                                    reply_markup=keyboard())

async def callback(update, context):
    q = update.callback_query
    await q.answer()
    if not allowed(update):
        return
    parts = q.data.split(":")
    await q.message.reply_text("Проверяю X2POS…")
    try:
        if q.data == "x2pos:check":
            await asyncio.wait_for(asyncio.to_thread(client.employee),12)
            await q.message.reply_text("X2POS подтвердил ключ и доступ к выбранному филиалу.",
                                       reply_markup=keyboard())
        elif len(parts)==4 and parts[1]=="catalog":
            page, offset = int(parts[2]), int(parts[3])
            if not 1<=page<=10000 or offset not in (0,10,20,30,40):
                return
            rows = await asyncio.wait_for(asyncio.to_thread(client.catalog,page),32)
            selected = rows[offset:offset+10]
            lines = [f"X2POS — товары и остатки\nСтраница API {page}"]
            for row in selected:
                lines.append(f"{row['name']} {row['variation']}\n"
                             f"ID разновидности: {row['id']}\n"
                             f"Остаток: {row['quantity']} ({row['unit']})\n"
                             f"Розница: {row['retail']} ₸ · Опт: {row['wholesale']} ₸")
            if not selected:
                lines.append("Товаров на этой странице нет.")
            nav = []
            if offset>0:
                nav.append(B("Назад",callback_data=f"x2pos:catalog:{page}:{offset-10}"))
            elif page>1:
                nav.append(B("Предыдущая страница",callback_data=f"x2pos:catalog:{page-1}:0"))
            if offset+10<len(rows):
                nav.append(B("Далее",callback_data=f"x2pos:catalog:{page}:{offset+10}"))
            elif len(rows)==50 and page<10000:
                nav.append(B("Следующая страница",callback_data=f"x2pos:catalog:{page+1}:0"))
            await q.message.reply_text("\n\n".join(lines),reply_markup=M(
                ([nav] if nav else [])+list(keyboard().inline_keyboard)))
        elif len(parts)==4 and parts[1]=="move":
            action,page = parts[2],int(parts[3])
            rows = await asyncio.wait_for(asyncio.to_thread(client.movements,action,page),22)
            labels={"draft":"Черновик","completed":"Завершён","canceled":"Отменён",
                    "waiting_to_confirm":"Ожидает подтверждения"}
            lines=[f"X2POS — {client.ACTIONS[action]}\nПоследние 7 дней · страница {page}\nДаты документов: UTC."]
            for row in rows:
                lines.append(f"Документ № {row['id']} · {row['date']}\n"
                             f"{labels.get(row['status'],'Неизвестный статус')}\n"
                             f"Количество: {row['quantity']} · Сумма: {row['amount']} ₸")
            if not rows:
                lines.append("Документов на этой странице нет.")
            nav=[]
            if page>1:
                nav.append(B("Назад",callback_data=f"x2pos:move:{action}:{page-1}"))
            if len(rows)==10 and page<10000:
                nav.append(B("Далее",callback_data=f"x2pos:move:{action}:{page+1}"))
            await q.message.reply_text("\n\n".join(lines),reply_markup=M(
                ([nav] if nav else [])+list(keyboard().inline_keyboard)))
    except client.X2Error as error:
        await q.message.reply_text(str(error),reply_markup=keyboard())
    except TimeoutError:
        await q.message.reply_text("Проверка X2POS заняла слишком много времени. Результат не подтверждён.",
                                   reply_markup=keyboard())
    except (ValueError,KeyError):
        await q.message.reply_text("Открой раздел X2POS заново.",reply_markup=keyboard())
