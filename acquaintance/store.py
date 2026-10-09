"""Owner-filtered, server-only RPC access for acquaintance."""
import asyncio
from uuid import UUID
from storage.supabase_store import _request, _user_id, StorageError

async def action(owner, name, question_id=None, **data):
    owner = _user_id(owner)
    if question_id is not None:
        question_id = str(UUID(str(question_id)))
    rows = await asyncio.to_thread(_request, 'rpc/acquaintance_action', record={
        'p_owner': owner, 'p_action': name, 'p_id': question_id, 'p_data': data,
    })
    if any(row.get('telegram_user_id') != owner for row in rows):
        raise StorageError('Unexpected acquaintance owner')
    return rows

async def enabled_owners():
    rows = await asyncio.to_thread(_request, 'acquaintance_profiles', params={
        'select': 'telegram_user_id', 'enabled': 'eq.true',
    })
    return [_user_id(row['telegram_user_id']) for row in rows]
