import json
import unittest
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from kids import store, report, worker, handlers
from memory import service

THU = datetime(2026, 10, 22, 17, 5, tzinfo=store.ZONE)


class ScheduleTests(unittest.TestCase):
    def test_seed_has_lessons_and_last_ends(self):
        self.assertEqual(len(store.lessons(store.SEED, 'mon')), 8)
        _, last = report.pickup_points(store.SEED, 'thu')
        self.assertEqual(last['end'], '17:25')
        self.assertEqual(last['subject'], 'Англ яз')
        _, friday = report.pickup_points(store.SEED, 'fri')
        self.assertEqual(friday['end'], '19:05')

    def test_reminder_moments_are_twenty_minutes_before(self):
        before, end, last = report.reminder_moments(store.SEED, 'thu', THU)
        self.assertEqual(before.strftime('%H:%M'), '17:05')
        self.assertEqual(end.strftime('%H:%M'), '17:25')
        self.assertEqual(last['name'], 'Мария')

    def test_day_text_lists_lessons_and_pickup(self):
        text = report.day_text(store.SEED, 'mon')
        self.assertIn('13:15–13:55', text)
        self.assertIn('Последний урок', text)
        self.assertIn('19:25', text)

    def test_weekend_has_no_lessons(self):
        self.assertEqual(store.lessons(store.SEED, 'sat'), [])


class IdentityTests(unittest.TestCase):
    def test_seed_names_maria_with_birthday(self):
        child = store.SEED['children']['middle']
        self.assertEqual(child['name'], 'Мария')
        self.assertEqual(child['birthday'], '2016-02-21')

    def test_ensure_migrates_old_placeholder(self):
        data = {'children': {'middle': {'name': 'Средняя дочь', 'grade': '5 А', 'week': {}}},
                'enabled': True, 'sent': {}}
        with patch.object(store, 'load', return_value=data), patch.object(store, 'save') as save:
            store.ensure(1)
        child = data['children']['middle']
        self.assertEqual(child['name'], 'Мария')
        self.assertEqual(child['birthday'], '2016-02-21')
        save.assert_called_once()

    def test_memory_has_compact_kids_line(self):
        value = json.dumps({'children': {'middle': {'name': 'Мария', 'birthday': '2016-02-21', 'grade': '5 А'}}},
                           ensure_ascii=False)
        self.assertEqual(service.kids_line(value), 'ДЕТИ: Мария, дата рождения 2016-02-21, класс 5 А')
        groups = {'facts': [], 'memory_entries': [],
                  'user_states': [{'state_key': 'kids_schedule', 'state_value': value, 'unit': None}]}
        text = service.format_memory(groups)
        self.assertIn('Мария', text)
        self.assertNotIn('children', text)

    def test_day_text_names_maria(self):
        self.assertIn('Мария', report.day_text(store.SEED, 'wed'))


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    def app(self):
        return NS(bot=NS(send_message=AsyncMock()), bot_data={})

    async def test_sends_before_and_at_the_end_once(self):
        app = self.app()
        item = worker.Worker(app, 1)
        data = {'enabled': True, 'children': store.SEED['children'], 'sent': {}}
        with patch.object(store, 'ensure', return_value=data), patch.object(store, 'save') as save:
            await item.tick(THU)                      # 17:05 — до конца
            await item.tick(THU)                      # повторно не отправляет
            await item.tick(THU.replace(hour=17, minute=25))
        self.assertEqual(app.bot.send_message.await_count, 2)
        self.assertTrue(data['sent'][THU.date().isoformat()]['before'])
        self.assertTrue(data['sent'][THU.date().isoformat()]['end'])
        self.assertEqual(save.call_count, 2)

    async def test_paused_or_weekend_does_not_send(self):
        app = self.app()
        item = worker.Worker(app, 1)
        paused = {'enabled': False, 'children': store.SEED['children'], 'sent': {}}
        with patch.object(store, 'ensure', return_value=paused), patch.object(store, 'save'):
            await item.tick(THU)
        saturday = THU.replace(day=24)
        with patch.object(store, 'ensure', return_value={'enabled': True, 'children': store.SEED['children'], 'sent': {}}), \
             patch.object(store, 'save'):
            await item.tick(saturday)
        app.bot.send_message.assert_not_awaited()


class PanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_done_closes_reminders_for_today(self):
        message = NS(reply_text=AsyncMock())
        query = NS(data='kids:done:thu', message=message, answer=AsyncMock())
        update = NS(callback_query=query, message=message, effective_user=NS(id=1),
                    effective_chat=NS(type='private', id=1))
        data = {'enabled': True, 'children': store.SEED['children'], 'sent': {}}
        with patch.object(handlers, 'owner_allowed', return_value=True), \
             patch.object(store, 'ensure', return_value=data), \
             patch.object(store, 'save') as save:
            await handlers.callback(update, NS(user_data={}))
        marks = data['sent'][store.local_now().date().isoformat()]
        self.assertTrue(marks['before'] and marks['end'])
        save.assert_called_once()
        self.assertIn('забрал', message.reply_text.call_args.args[0].lower())


if __name__ == '__main__':
    unittest.main()
