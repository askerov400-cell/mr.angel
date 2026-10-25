"""Расписание детей владельца в таблице состояний, без новых таблиц."""
import json
from zoneinfo import ZoneInfo

from storage.supabase_store import _request, _user_id

KEY = 'kids_schedule'
ZONE = ZoneInfo('Asia/Qyzylorda')


def local_now():
    from datetime import datetime
    return datetime.now(ZONE)
DAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
DAY_NAMES = {'mon': 'Понедельник', 'tue': 'Вторник', 'wed': 'Среда', 'thu': 'Четверг', 'fri': 'Пятница',
             'sat': 'Суббота', 'sun': 'Воскресенье'}
LEAD = 20

SEED = {'children': {
    'middle': {'name': 'Мария', 'birthday': '2016-02-21', 'grade': '5 А', 'week': {
        'mon': [('13:15', '13:55', 'прик мат (факультатив)'), ('14:05', '14:45', 'Кл час'),
                ('14:50', '15:30', 'Англ яз'), ('15:35', '16:15', 'естеств'), ('16:25', '17:05', 'Худ труд'),
                ('17:15', '17:55', 'матем'), ('18:00', '18:40', 'Каз яз'), ('18:45', '19:25', 'Русский')],
        'tue': [('14:00', '14:45', 'естествозн'), ('14:50', '15:35', 'физра'), ('15:45', '16:30', 'Каз язык'),
                ('16:40', '17:25', 'русский'), ('17:30', '18:15', 'музыка'), ('18:20', '19:05', 'математика')],
        'wed': [('14:00', '14:45', 'Каз яз'), ('14:50', '15:35', 'информ'), ('15:45', '16:30', 'Худ труд'),
                ('16:40', '17:25', 'физра'), ('17:30', '18:15', 'Рус язык'), ('18:20', '19:05', 'матем')],
        'thu': [('14:00', '14:45', 'русский'), ('14:50', '15:35', 'Худ труд'), ('15:45', '16:30', 'матем'),
                ('16:40', '17:25', 'Англ яз')],
        'fri': [('14:00', '14:45', 'русский'), ('14:50', '15:35', 'история'), ('15:45', '16:30', 'матем'),
                ('16:40', '17:25', 'Англ яз'), ('17:30', '18:15', 'физра'), ('18:20', '19:05', 'Всемирная ист')]}},
    'elder': {'name': 'Ксения', 'birthday': '2011-07-18', 'grade': 'юридический колледж', 'week': {
        'mon': [('08:00', '12:30', 'колледж')], 'tue': [('08:00', '12:30', 'колледж')],
        'wed': [('08:00', '12:30', 'колледж')], 'thu': [('08:00', '12:30', 'колледж')],
        'fri': [('08:00', '12:30', 'колледж')]}},
}, 'enabled': True, 'sent': {}}


def load(owner):
    rows = _request('user_states', params={'select': 'state_value', 'telegram_user_id': f'eq.{_user_id(owner)}',
                                           'state_key': f'eq.{KEY}'})
    if not rows:
        return {}
    value = rows[0].get('state_value')
    if isinstance(value, dict):
        return value
    try:
        return _normalize(json.loads(str(value)))
    except (TypeError, ValueError):
        return {}


RENAMED_SUBJECTS = {'физика': 'физра'}


def _normalize(data):
    """Физика в этой таблице — это физкультура; правим старые сохранённые записи."""
    for child in (data.get('children') or {}).values():
        week = child.get('week') or {}
        for day, lessons in list(week.items()):
            fixed = []
            for row in lessons or []:
                try:
                    start, end, subject = row
                except (TypeError, ValueError):
                    fixed.append(row); continue
                fixed.append((start, end, RENAMED_SUBJECTS.get(str(subject).strip().lower(), subject)))
            week[day] = fixed
    return data


def save(owner, data):
    _request('rpc/save_user_state', record={
        'p_user_id': _user_id(owner), 'p_key': KEY,
        'p_value': json.dumps(data, ensure_ascii=False),
        'p_category': 'kids', 'p_unit': None, 'p_confidence': 0.9,
    })


def ensure(owner):
    data = load(owner)
    if not data.get('children'):
        data = json.loads(json.dumps(SEED))
        save(owner, data)
        return data
    children = data.setdefault('children', {})
    changed = False
    if 'elder' not in children:
        children['elder'] = json.loads(json.dumps(SEED['children']['elder']))
        changed = True
    else:
        elder = children['elder']
        if not elder.get('week'):
            elder['week'] = json.loads(json.dumps(SEED['children']['elder']['week']))
            changed = True
    child = children.get('middle') or {}
    children['middle'] = child
    if child.get('name') == 'Средняя дочь':
        child['name'] = 'Мария'
        changed = True
    if not child.get('birthday'):
        child['birthday'] = '2016-02-21'
        changed = True
    if changed:
        save(owner, data)
    return data


def lessons(data, day):
    rows = []
    for slug, child in (data.get('children') or {}).items():
        for start, end, subject in (child.get('week') or {}).get(day, []):
            rows.append({'child': slug, 'name': child.get('name', slug), 'grade': child.get('grade', ''),
                         'birthday': child.get('birthday', ''), 'start': start, 'end': end, 'subject': subject})
    rows.sort(key=lambda row: (row['start'], row['name']))
    return rows
