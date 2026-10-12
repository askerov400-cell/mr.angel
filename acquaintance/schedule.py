"""Twenty to thirty persisted random slots in the owner's local window."""
from datetime import datetime, time, timedelta, timezone
from random import SystemRandom
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('Asia/Qyzylorda')
RANDOM = SystemRandom()

def local_now():
    return datetime.now(timezone.utc).astimezone(ZONE)

def in_window(now):
    local = now.astimezone(ZONE)
    return time(9) <= local.time().replace(tzinfo=None) < time(23)

def slots(day, rng=RANDOM):
    count = rng.randrange(20, 31)
    start = datetime.combine(day, time(9), ZONE)
    minutes = 14 * 60
    # One slot per segment, with five-minute margins: >= ten minutes apart.
    result = []
    for i in range(count):
        lower = i * minutes // count + 5
        upper = (i + 1) * minutes // count - 5
        result.append({'slot': i, 'at': (start + timedelta(
            minutes=rng.randrange(lower, upper + 1))).isoformat()})
    return result
