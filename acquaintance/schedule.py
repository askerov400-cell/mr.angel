"""Ten persisted random slots in the owner's local working window."""
from datetime import datetime, time, timedelta, timezone
from random import SystemRandom
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('Asia/Qyzylorda')
RANDOM = SystemRandom()

def local_now():
    return datetime.now(timezone.utc).astimezone(ZONE)

def in_window(now):
    local = now.astimezone(ZONE)
    return time(10) <= local.time().replace(tzinfo=None) < time(23)

def slots(day, rng=RANDOM):
    start = datetime.combine(day, time(10), ZONE)
    return [{'slot': i, 'at': (start + timedelta(minutes=i*78 + rng.randrange(10,68))).isoformat()}
            for i in range(10)]
