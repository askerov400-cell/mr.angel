import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from acquaintance import handlers
from memory import profile, service

QID = '11111111-1111-1111-1111-111111111111'


class ProfileTests(unittest.TestCase):
    def test_profile_is_first_in_memory_context(self):
        groups = {'facts': [], 'memory_entries': [{'memory_type': 'FACT', 'memory_text': 'Любит тишину'}],
                  'user_states': [{'state_key': 'owner_profile', 'state_value': 'Личность: спокойный', 'unit': None}]}
        text = service.format_memory(groups)
        self.assertTrue(text.startswith('ПРОФИЛЬ ВЛАДЕЛЬЦА'))
        self.assertIn('Личность: спокойный', text)
        self.assertIn('Любит тишину', text)
        self.assertNotIn('owner_profile:', text)

    def test_staleness(self):
        with patch.object(profile, 'saved', return_value=(None, None)):
            self.assertTrue(profile.stale(1))
        now = datetime.now(timezone.utc)
        with patch.object(profile, 'saved', return_value=('x', (now - timedelta(hours=30)).isoformat())):
            self.assertTrue(profile.stale(1))
        with patch.object(profile, 'saved', return_value=('x', now.isoformat())):
            self.assertFalse(profile.stale(1))


class SuggestTests(unittest.IsolatedAsyncioTestCase):
    def update(self, text, reply=None):
        message = NS(reply_text=AsyncMock(), text=text, reply_to_message=reply)
        return NS(message=message, effective_user=NS(id=1), effective_chat=NS(type='private', id=1))

    async def test_recent_question_is_offered_as_answer(self):
        pending = {'id': QID, 'question_text': 'Что любишь?', 'sent_at': datetime.now(timezone.utc).isoformat()}
        context = NS(user_data={})
        update = self.update('Люблю тишину')
        with patch.object(handlers, 'available', return_value=True), \
             patch.object(handlers.store, 'action', AsyncMock(return_value=[{'pending': pending}])):
            await handlers.suggest(update, context)
        self.assertEqual(context.user_data['aq_candidate'], {'id': QID, 'text': 'Люблю тишину'})
        markup = update.message.reply_text.call_args.kwargs['reply_markup']
        buttons = [button.callback_data for row in markup.inline_keyboard for button in row]
        self.assertIn('aq:link:' + QID, buttons)

    async def test_old_question_is_not_suggested(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        pending = {'id': QID, 'question_text': 'Что любишь?', 'sent_at': old}
        context = NS(user_data={})
        update = self.update('Люблю тишину')
        with patch.object(handlers, 'available', return_value=True), \
             patch.object(handlers.store, 'action', AsyncMock(return_value=[{'pending': pending}])):
            await handlers.suggest(update, context)
        update.message.reply_text.assert_not_awaited()
        self.assertNotIn('aq_candidate', context.user_data)

    async def test_reply_to_question_is_not_suggested(self):
        update = self.update('Люблю тишину', reply=NS(from_user=NS(id=2)))
        with patch.object(handlers, 'available', return_value=True), \
             patch.object(handlers.store, 'action', AsyncMock()) as action:
            await handlers.suggest(update, NS(user_data={}))
        action.assert_not_awaited()


class Lock:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *args):
        return False


class LinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_link_saves_free_answer(self):
        worker = NS(lock=lambda owner: Lock(), client=None)
        context = NS(user_data={'aq_candidate': {'id': QID, 'text': 'Люблю тишину'}},
                     application=NS(bot_data={'acquaintance_worker': worker}))
        message = NS(reply_text=AsyncMock())
        query = NS(data='aq:link:' + QID, message=message, answer=AsyncMock())
        update = NS(callback_query=query, message=message, effective_user=NS(id=1), effective_chat=NS(type='private', id=1))
        calls = []
        async def action(owner, name, question_id=None, **data):
            calls.append((name, question_id, data))
            if name == 'get':
                return [{'status': 'sent', 'question_text': 'Что любишь?'}]
            if name == 'answer':
                return [{'saved': True}]
            return []
        with patch.object(handlers, 'available', return_value=True), \
             patch.object(handlers, 'private', return_value=True), \
             patch.object(handlers.store, 'action', side_effect=action), \
             patch.object(handlers.answers, 'summarize', AsyncMock(return_value='- любит тишину')):
            await handlers.callback(update, context)
        names = [row[0] for row in calls]
        self.assertEqual(names, ['get', 'answer'])
        answer_call = calls[1]
        self.assertEqual(answer_call[2]['text'], 'Люблю тишину')
        self.assertIn('сохранён', message.reply_text.call_args.args[0])

    async def test_nolink_does_not_touch_question(self):
        worker = NS(lock=lambda owner: Lock(), client=None)
        context = NS(user_data={'aq_candidate': {'id': QID, 'text': 'x'}},
                     application=NS(bot_data={'acquaintance_worker': worker}))
        message = NS(reply_text=AsyncMock())
        query = NS(data='aq:nolink:' + QID, message=message, answer=AsyncMock())
        update = NS(callback_query=query, message=message, effective_user=NS(id=1), effective_chat=NS(type='private', id=1))
        with patch.object(handlers, 'available', return_value=True), \
             patch.object(handlers, 'private', return_value=True), \
             patch.object(handlers.store, 'action', AsyncMock()) as action:
            await handlers.callback(update, context)
        action.assert_not_awaited()
        self.assertNotIn('aq_candidate', context.user_data)


if __name__ == '__main__':
    unittest.main()
