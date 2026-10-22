"""Текст расписания и время напоминаний."""
from datetime import datetime, timedelta

from kids import store


def pickup_points(data, day):
    """Первый и последний уроки дня."""
    rows = store.lessons(data, day)
    if not rows:
        return None, None
    return rows[0], max(rows, key=lambda row: row['end'])


def reminder_moments(data, day, moment):
    """Когда напомнить: за LEAD минут до конца и в момент конца."""
    _, last = pickup_points(data, day)
    if not last:
        return None
    end = datetime.combine(moment.date(), datetime.strptime(last['end'], '%H:%M').time(), store.ZONE)
    return end - timedelta(minutes=store.LEAD), end, last


def day_text(data, day, moment=None):
    rows = store.lessons(data, day)
    if not rows:
        return store.DAY_NAMES.get(day, day) + ': занятий нет.'
    labels = sorted({row['name'] + (' · ' + row['grade'] if row['grade'] else '') for row in rows})
    lines = [store.DAY_NAMES.get(day, day) + ' — расписание детей', ' · '.join(labels), '']
    for row in rows:
        lines.append(row['start'] + '–' + row['end'] + '  ' + row['subject'] + ' · ' + row['name'])
    _, last = pickup_points(data, day)
    lines.append('')
    lines.append('Последний урок: ' + last['subject'] + ' до ' + last['end'] + '.')
    lines.append('Напомню за ' + str(store.LEAD) + ' минут до конца и в момент окончания.')
    return '\n'.join(lines)
