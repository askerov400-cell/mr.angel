"""Owner-scoped business aggregates. Server-only; no raw X2POS documents."""
import os
from datetime import datetime, timezone
from decimal import Decimal
from storage.supabase_store import _request, _user_id, StorageError
from x2pos.client import identifier

def identity(owner=None):
    configured = _user_id(int(os.getenv('X2POS_OWNER_ID', '0')))
    if owner is not None and owner != configured:
        raise StorageError('Business owner mismatch')
    return configured, identifier(os.getenv('X2POS_BRANCH_ID'))

def checked(rows, owner, branch):
    if any(row.get('owner') != owner or row.get('branch') != branch for row in rows):
        raise StorageError('Business ownership mismatch')
    return rows

def serial(value):
    if isinstance(value, Decimal): return str(value)
    if isinstance(value, dict): return {k:serial(v) for k,v in value.items()}
    if isinstance(value, list): return [serial(v) for v in value]
    return value

def save(daily):
    owner, branch = identity()
    rows = _request('rpc/business_save', record={'p_owner':owner,'p_branch':branch,
        'p_rows':[{'day':day,'metrics':serial(metrics)} for day,metrics in sorted(daily.items())]})
    if len(checked(rows,owner,branch)) != 1:
        raise StorageError('Business save not confirmed')

def read(owner):
    owner, branch = identity(owner)
    filters = {'owner':f'eq.{owner}', 'branch':f'eq.{branch}'}
    state = checked(_request('business_sync',params={**filters,'select':'*','limit':'1'}),owner,branch)
    days = checked(_request('business_daily',params={**filters,'select':'*','order':'day.desc','limit':'90'}),owner,branch)
    history = checked(_request('business_history',params={**filters,'select':'day,recorded_at,owner,branch','order':'id.desc','limit':'5'}),owner,branch)
    return (state[0] if state else {}), {r['day']:r['metrics'] for r in days}, history

def error():
    owner, branch = identity()
    _request('business_sync',params={'on_conflict':'owner,branch'},record={
        'owner':owner,'branch':branch,'last_error':datetime.now(timezone.utc).isoformat()},
        prefer='resolution=merge-duplicates,return=representation')

def claim(kind, day):
    owner,branch = identity()
    rows = _request('rpc/business_claim',record={'p_owner':owner,'p_branch':branch,
        'p_kind':kind,'p_day':day.isoformat()})
    return bool(checked(rows,owner,branch))
