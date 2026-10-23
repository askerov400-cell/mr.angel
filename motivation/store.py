"""План мотивации владельца в существующей таблице состояний."""
import json
from datetime import datetime, time as clock, timedelta
from random import SystemRandom
from zoneinfo import ZoneInfo

from storage.supabase_store import _request, _user_id

ZONE = ZoneInfo('Asia/Qyzylorda')
KEY = 'motivation'
RANDOM = SystemRandom()

AREAS = {'sport': 'Спорт', 'business': 'Бизнес', 'guardian': 'Хранитель', 'family': 'Семья и дети'}
DISABLED_AREAS = {'sport'}
LAYOUT = (('sport', '09:20'), ('business', '11:50'), ('guardian', '14:10'),
          ('sport', '16:40'), ('business', '19:00'), ('family', '20:40'))
START = clock(9)
END = clock(22)


def local_now():
    return datetime.now(ZONE)


def load(owner):
    rows = _request('user_states', params={'select': 'state_value', 'telegram_user_id': f'eq.{_user_id(owner)}',
                                           'state_key': f'eq.{KEY}'})
    if not rows:
        return {}
    value = rows[0].get('state_value')
    if isinstance(value, dict):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return {}


def save(owner, data):
    _request('rpc/save_user_state', record={
        'p_user_id': _user_id(owner), 'p_key': KEY,
        'p_value': json.dumps(data, ensure_ascii=False),
        'p_category': 'motivation', 'p_unit': None, 'p_confidence': 0.9,
    })


def plan(day, rng=RANDOM):
    rows = []
    for area, moment in LAYOUT:
        if area in DISABLED_AREAS:
            continue
        hour, minute = (int(part) for part in moment.split(':'))
        jitter = rng.randrange(-10, 11)
        at = datetime.combine(day, clock(hour, minute), ZONE) + timedelta(minutes=jitter)
        rows.append({'area': area, 'at': at.isoformat(), 'sent': False})
    return rows


def fresh(day, previous=None, rng=RANDOM):
    previous = previous or {}
    return {'enabled': bool(previous.get('enabled', True)), 'day': day.isoformat(),
            'plan': plan(day, rng), 'done': previous.get('done') or {},
            'later': previous.get('later')}


def due(data, moment):
    rows = []
    later = data.get('later')
    if isinstance(later, dict) and not later.get('sent') and later.get('area') not in DISABLED_AREAS:
        try:
            if datetime.fromisoformat(later['at']) <= moment:
                rows.append(('later', later))
        except (KeyError, ValueError):
            pass
    for item in data.get('plan') or []:
        if item.get('sent') or item.get('area') in DISABLED_AREAS:
            continue
        try:
            if datetime.fromisoformat(item['at']) <= moment:
                rows.append(('plan', item))
        except (KeyError, ValueError):
            continue
    return rows


def in_window(moment):
    local = moment.astimezone(ZONE).time().replace(tzinfo=None)
    return START <= local < END


def remember(owner, area, moment):
    """Отметка «сделал» попадает в память как событие."""
    label = AREAS.get(area, area)
    _request('memory_entries', record={
        'telegram_user_id': _user_id(owner), 'memory_type': 'EVENT', 'category': 'motivation',
        'memory_text': label + ': выполнено ' + moment.date().isoformat(), 'confidence': 1.0,
    }, prefer='resolution=ignore-duplicates,return=representation')
