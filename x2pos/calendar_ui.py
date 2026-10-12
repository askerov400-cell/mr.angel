"""Local-day calendar for business reports; no API or stored business data."""
import calendar
from datetime import date, datetime
from zoneinfo import ZoneInfo
from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M

MONTHS = ('Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
          'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь')

def today():
    return datetime.now(ZoneInfo('Asia/Qyzylorda')).date()

def keyboard(year, month, now=None):
    now = now or today()
    first = date(year, month, 1)
    if year < 2000 or first > now.replace(day=1):
        raise ValueError('Unavailable month')
    rows = [[B(f'{MONTHS[month-1]} {year}', callback_data='x2pos:noop')],
            [B(d, callback_data='x2pos:noop') for d in ('Пн','Вт','Ср','Чт','Пт','Сб','Вс')]]
    for week in calendar.monthcalendar(year, month):
        rows.append([B(str(day) if day else '·', callback_data=(
            f'x2pos:day:{year:04d}-{month:02d}-{day:02d}'
            if day and date(year, month, day) <= now else 'x2pos:noop')) for day in week])
    previous = (year-1, 12) if month == 1 else (year, month-1)
    following = (year+1, 1) if month == 12 else (year, month+1)
    nav = []
    if previous[0] >= 2000:
        nav.append(B('‹', callback_data=f'x2pos:month:{previous[0]}:{previous[1]}'))
    if date(*following, 1) <= now.replace(day=1):
        nav.append(B('›', callback_data=f'x2pos:month:{following[0]}:{following[1]}'))
    if nav:
        rows.append(nav)
    rows.append([B('Назад', callback_data='x2pos:home')])
    return M(rows)

def selected(value, now=None):
    day = date.fromisoformat(value)
    if value != day.isoformat() or day.year < 2000 or day > (now or today()):
        raise ValueError('Unavailable day')
    return day
