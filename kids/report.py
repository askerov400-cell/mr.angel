"""Текст расписания и напоминания по каждому ребёнку отдельно."""
from datetime import datetime, time as clock, timedelta

from kids import store


def child_last(data, day):
    last = {}
    for row in store.lessons(data, day):
        current = last.get(row['child'])
        if not current or row['end'] > current['end']:
            last[row['child']] = row
    return last


def reminder_points(data, day, moment):
    points = []
    for slug, row in child_last(data, day).items():
        end = datetime.combine(moment.date(), clock.fromisoformat(row['end']), store.ZONE)
        points.append({'child': slug, 'last': row,
                       'before': end - timedelta(minutes=store.LEAD), 'end': end})
    return points


def day_text(data, day, moment=None):
    rows = store.lessons(data, day)
    if not rows:
        note = store.DAY_NAMES.get(day, day) + ': занятий нет.'
        missing = [child.get('name') for child in (data.get('children') or {}).values()
                   if child.get('name') and not child.get('week')]
        if missing:
            note += ' Расписание ' + ', '.join(missing) + ' ещё не добавлено.'
        return note
    lines = [store.DAY_NAMES.get(day, day) + ' — расписание детей']
    grouped = {}
    for row in rows:
        grouped.setdefault((row['child'], row['name'], row['grade']), []).append(row)
    for (slug, name, grade), items in grouped.items():
        lines.append('')
        lines.append(name + (' · ' + grade if grade else ''))
        for row in items:
            lines.append('  ' + row['start'] + '–' + row['end'] + '  ' + row['subject'])
        last = max(items, key=lambda row: row['end'])
        lines.append('  конец в ' + last['end'] + ', напомню за ' + str(store.LEAD) + ' минут')
    return '\n'.join(lines)
