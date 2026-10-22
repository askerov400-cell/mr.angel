import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from motivation import store, texts, worker, handlers

MOMENT = datetime(2026, 10, 22, 10, 0, tzinfo=store.ZONE)


class PlanTests(unittest.TestCase):
    def test_six_nudges_with_area_counts(self):
        rows = store.plan(MOMENT.date(), rng=__import__('random').Random(1))
        self.assertEqual(len(rows), 6)
        counts = {}
        for row in rows:
            counts[row['area']] = counts.get(row['area'], 0) + 1
            moment = datetime.fromisoformat(row['at'])
            self.assertTrue(9 <= moment.hour < 22, row)
        self.assertEqual(counts, {'sport': 2, 'business': 2, 'guardian': 1, 'family': 1})

    def test_due_includes_later_and_plan(self):
        data = {'plan': [{'area': 'sport', 'at': (MOMENT - timedelta(minutes=5)).isoformat(), 'sent': False},
                         {'area': 'family', 'at': (MOMENT + timedelta(hours=3)).isoformat(), 'sent': False}],
                'later': {'area': 'business', 'at': (MOMENT - timedelta(minutes=1)).isoformat(), 'sent': False}}
        rows = store.due(data, MOMENT)
        self.assertEqual([kind for kind, _ in rows], ['later', 'plan'])
        self.assertEqual(rows[1][1]['area'], 'sport')

    def test_fresh_keeps_done_and_enabled(self):
        data = store.fresh(MOMENT.date(), {'enabled': False, 'done': {'sport': 2}})
        self.assertFalse(data['enabled'])
        self.assertEqual(data['done'], {'sport': 2})
        self.assertEqual(len(data['plan']), 6)

    def test_texts_cover_all_areas_and_mention_streak(self):
        for area in store.AREAS:
            self.assertTrue(texts.build(area, 0))
        self.assertIn('уже отмечено', texts.build('sport', 3))


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    def data(self):
        return {'enabled': True, 'day': MOMENT.date().isoformat(),
                'plan': [{'area': 'sport', 'at': (MOMENT - timedelta(minutes=2)).isoformat(), 'sent': False}],
                'done': {}, 'later': None}

    def app(self, last=0):
        return NS(bot=NS(send_message=AsyncMock()), bot_data={'last_activity': {1: last}})

    async def test_sends_due_nudge_and_marks_sent(self):
        app = self.app()
        item = worker.Worker(app, 1)
        data = self.data()
        with patch.object(store, 'load', return_value=data), patch.object(store, 'save') as save:
            await item.tick(MOMENT)
        app.bot.send_message.assert_awaited_once()
        self.assertTrue(data['plan'][0]['sent'])
        save.assert_called_once()

    async def test_recent_activity_blocks_sending(self):
        app = self.app(last=MOMENT.timestamp())
        item = worker.Worker(app, 1)
        with patch.object(store, 'load', return_value=self.data()), patch.object(store, 'save'):
            await item.tick(MOMENT)
        app.bot.send_message.assert_not_awaited()

    async def test_pause_and_quiet_hours_block_sending(self):
        app = self.app()
        item = worker.Worker(app, 1)
        paused = self.data(); paused['enabled'] = False
        with patch.object(store, 'load', return_value=paused), patch.object(store, 'save'):
            await item.tick(MOMENT)
        night = MOMENT.replace(hour=23, minute=30)
        with patch.object(store, 'load', return_value=self.data()), patch.object(store, 'save'):
            await item.tick(night)
        app.bot.send_message.assert_not_awaited()

    async def test_long_overdue_nudge_bypasses_idle_guard(self):
        app = self.app(last=MOMENT.timestamp())
        item = worker.Worker(app, 1)
        data = {'enabled': True, 'day': MOMENT.date().isoformat(), 'done': {}, 'later': None,
                'plan': [{'area': 'business', 'at': (MOMENT - timedelta(hours=3)).isoformat(), 'sent': False}]}
        with patch.object(store, 'load', return_value=data), patch.object(store, 'save'):
            await item.tick(MOMENT)
        app.bot.send_message.assert_awaited_once()


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    def update(self, data):
        message = NS(reply_text=AsyncMock())
        query = NS(data=data, message=message, answer=AsyncMock())
        return NS(callback_query=query, message=message, effective_user=NS(id=1),
                  effective_chat=NS(type='private', id=1))

    async def test_done_increments_and_writes_event(self):
        update = self.update('mot:done:sport')
        data = {'enabled': True, 'day': store.local_now().date().isoformat(), 'plan': [], 'done': {}}
        with patch.object(handlers, 'owner_allowed', return_value=True), \
             patch.object(store, 'load', return_value=data), \
             patch.object(store, 'save') as save, \
             patch.object(store, 'remember') as remember:
            await handlers.callback(update, NS(user_data={}))
        self.assertEqual(data['done']['sport'], 1)
        save.assert_called_once()
        remember.assert_called_once()
        self.assertIn('отмечено', update.callback_query.message.reply_text.call_args.args[0])

    async def test_later_schedules_two_hours(self):
        update = self.update('mot:later:family')
        data = {'enabled': True, 'day': store.local_now().date().isoformat(), 'plan': [], 'done': {}}
        with patch.object(handlers, 'owner_allowed', return_value=True), \
             patch.object(store, 'load', return_value=data), patch.object(store, 'save') as save:
            await handlers.callback(update, NS(user_data={}))
        self.assertEqual(data['later']['area'], 'family')
        save.assert_called_once()


if __name__ == '__main__':
    unittest.main()
