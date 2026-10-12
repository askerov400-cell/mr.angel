"""Owner-only X2POS views outside conversational memory and LLM."""
import asyncio
import os
from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M
from x2pos import calendar_ui, reports, expenses, client

def allowed(update):
    return bool(update.effective_user and update.effective_chat
        and update.effective_chat.type == "private"
        and str(update.effective_user.id) == os.getenv("X2POS_OWNER_ID","")
        and update.effective_user.id == update.effective_chat.id)

def keyboard():
    return M([[B("Остаток на складе",callback_data="x2pos:warehouse")],
              [B("Статистика продаж",callback_data="x2pos:sales")]])

async def panel(update, context):
    if not allowed(update):
        await update.message.reply_text("X2POS доступен только владельцу магазина.")
        return
    context.user_data.pop("interface_input",None)
    await update.message.reply_text("Аналитика бизнеса\nОстаток на складе и статистика продаж X2POS.",
                                    reply_markup=keyboard())

async def callback(update, context):
    q = update.callback_query
    await q.answer()
    if not allowed(update):
        return
    if q.data == "x2pos:warehouse":
        await q.message.reply_text(
            "Остаток на складе\nОбщая стоимость, ₸\n\n"
            "<pre>Закупочная | Оптовая | Розничная\n"
            "     —     |    —    |     —</pre>\n\n"
            "X2POS подтвердил: готового метода закупочной стоимости склада нет. "
            "Для оптового и розничного итогов ещё требуется проверка полноты остатков. Прочерки означают отсутствие "
            "подтверждённого расчёта.",
            parse_mode="HTML", reply_markup=keyboard())
        return
    parts = q.data.split(":")
    if q.data == "x2pos:noop":
        return
    if q.data == "x2pos:home":
        await q.edit_message_text("Аналитика бизнеса", reply_markup=keyboard())
        return
    try:
        if q.data == "x2pos:sales":
            now = calendar_ui.today()
            await q.message.reply_text(calendar_ui.prompt(),
                reply_markup=calendar_ui.keyboard(now.year, now.month))
        elif len(parts) in (4, 5) and parts[1] == "month":
            start = calendar_ui.selected(parts[4]) if len(parts) == 5 else None
            markup = calendar_ui.keyboard(int(parts[2]), int(parts[3]), start=start)
            await q.edit_message_text(calendar_ui.prompt(start), reply_markup=markup)
        elif len(parts) in (3, 4) and parts[1] == "day":
            day = calendar_ui.selected(parts[2])
            if len(parts) == 3:
                await q.edit_message_text(calendar_ui.prompt(day),
                    reply_markup=calendar_ui.keyboard(day.year, day.month, start=day))
                return
            start = calendar_ui.selected(parts[3])
            if day < start:
                await q.edit_message_text(
                    calendar_ui.prompt(start) + "\nКонец не может быть раньше начала.",
                    reply_markup=calendar_ui.keyboard(day.year, day.month, start=start))
                return
            await q.edit_message_text(
                f"Статистика продаж\nПериод: {start:%d.%m.%Y} — {day:%d.%m.%Y}\n"
                "Загружаю все страницы X2POS…")
            result = await asyncio.to_thread(expenses.report, start, day)
            await q.message.reply_text(reports.format_report(start, day, result),
                reply_markup=M([[B("Выбрать другой период", callback_data="x2pos:sales")],
                                [B("Назад", callback_data="x2pos:home")]]))
        else:
            await q.message.reply_text("Меню обновлено. Выбери нужный отчёт.", reply_markup=keyboard())
    except client.X2Error as error:
        await q.message.reply_text(str(error), reply_markup=keyboard())
    except (ValueError, OverflowError):
        await q.message.reply_text("Эта дата недоступна. Открой календарь заново.",
            reply_markup=keyboard())
