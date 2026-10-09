"""Private Telegram navigation; storage and conversation remain in existing handlers."""
import secrets
from types import SimpleNamespace
from telegram import ReplyKeyboardMarkup, InlineKeyboardButton as B, InlineKeyboardMarkup as M
from memory.journal import send_reply

CHAT='💬 Общение'
MEMORY='🧠 Моя память'
SAVE='➕ Запомнить'
NEW='🔄 Новый диалог'
HELP='❔ Помощь'
QUESTIONS='🤝 Знакомство'
KASPI='🛍 Kaspi'
LABELS={CHAT,MEMORY,SAVE,NEW,HELP,QUESTIONS,KASPI}
SERVICE_PREFIXES=('Знакомство\n','Хранитель\n','Возможности Хранителя\n','Запись в память\n','Новый диалог\n','Общение\n','Действие отменено.','Подтверждение уже не действует.')

def keyboard():
    return ReplyKeyboardMarkup([[CHAT,MEMORY],[SAVE,QUESTIONS],[NEW,HELP],[KASPI]],resize_keyboard=True,is_persistent=True,input_field_placeholder='Напиши сообщение Хранителю')

def private(update):
    return bool(update.effective_user and update.effective_chat and update.effective_chat.type=='private' and update.effective_user.id==update.effective_chat.id)

async def home(update,context):
    if not private(update):
        await send_reply(update,'Открой личный чат со мной, чтобы работать с памятью.');return
    context.user_data.pop('interface_input',None)
    context.user_data.pop('interface_clear',None)
    await send_reply(update,'Хранитель\n\nНапиши сообщение, пришли голосовое, фото или видео.\n\nКнопки внизу помогут посмотреть память, сохранить важное и начать новый диалог.',reply_markup=keyboard())

async def cancel(update,context):
    if not private(update):return
    context.user_data.pop('interface_input',None);context.user_data.pop('interface_clear',None)
    await send_reply(update,'Действие отменено. Можешь продолжить общение.',reply_markup=keyboard())

async def text(update,context,handlers):
    if not private(update):return False
    data=getattr(context,'user_data',None)
    if data is None:return False
    content=update.message.text.strip()
    if content in LABELS:
        data.pop('interface_input',None);data.pop('interface_clear',None)
        if content==KASPI:
            from kaspi.handlers import panel
            await panel(update,context)
        elif content==QUESTIONS:
            from acquaintance.handlers import panel
            await panel(update,context)
        elif content==MEMORY:
            await handlers['memory'](update,context)
        elif content==SAVE:
            data['interface_input']='remember'
            await send_reply(update,'Запись в память\n\nНапиши одним сообщением, что нужно запомнить. Для отмены нажми кнопку ниже или отправь /cancel.',reply_markup=M([[B('Отмена',callback_data='guardian:cancel')]]))
        elif content==NEW:
            token=secrets.token_hex(8);data['interface_clear']=token
            await send_reply(update,'Новый диалог\n\nНачать общение с чистого контекста? Сохранённые факты и история переписки останутся.',reply_markup=M([[B('Начать новый диалог',callback_data='guardian:clear:'+token)],[B('Отмена',callback_data='guardian:cancel')]]))
        elif content==HELP:
            await send_reply(update,'Возможности Хранителя\n\n💬 Общение — текст, голосовые, фотографии и видео до 2 минут/18 МБ.\n🧠 Моя память — сохранённые сведения о тебе.\n➕ Запомнить — явно сохранить важный факт.\n🔄 Новый диалог — начать новую тему, сохранив факты.\n\n🤝 Знакомство — вопросы по расписанию, пауза и ответы в память.\n\nКоманды: /questions, /menu, /memory, /remember текст, /clear, /cancel.\nЗапись фактов из обычного общения зависит от настроенного режима памяти.',reply_markup=keyboard())
        else:
            await send_reply(update,'Общение\n\nНапиши, что хочешь обсудить. Можно отправить голосовое, фото или видео.',reply_markup=keyboard())
        return True
    if data.get('interface_input')=='remember':
        args=getattr(context,'args',None)
        context.args=[content]
        try:await handlers['remember'](update,context)
        finally:context.args=args
        data.pop('interface_input',None)
        return True
    return False

async def callback(update,context,clear):
    query=update.callback_query
    await query.answer()
    if not private(update):return
    proxy=SimpleNamespace(message=query.message,effective_user=update.effective_user,effective_chat=update.effective_chat)
    if query.data=='guardian:cancel':
        await cancel(proxy,context);return
    expected=context.user_data.pop('interface_clear',None)
    token=query.data.removeprefix('guardian:clear:')
    if not expected or not secrets.compare_digest(expected,token):
        await send_reply(proxy,'Подтверждение уже не действует. Нажми «Новый диалог» заново.',reply_markup=keyboard());return
    context.user_data.pop('interface_input',None)
    await clear(proxy,context)
