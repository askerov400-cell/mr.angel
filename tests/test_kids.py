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
        self.assertEqual(len(store.lessons(store.SEED, 'mon')), 9)
        last = report.child_last(store.SEED, 'thu')['middle']
        self.assertEqual(last['end'], '17:25')
        self.assertEqual(last['subject'], 'Англ яз')
        self.assertEqual(report.child_last(store.SEED, 'fri')['middle']['end'], '19:05')
        self.assertEqual(report.child_last(store.SEED, 'thu')['elder']['end'], '12:30')

    def test_reminder_points_per_child(self):
        points = {row['child']: row for row in report.reminder_points(store.SEED, 'thu', THU)}
        self.assertEqual(points['middle']['before'].strftime('%H:%M'), '17:05')
        self.assertEqual(points['middle']['end'].strftime('%H:%M'), '17:25')
        self.assertEqual(points['elder']['before'].strftime('%H:%M'), '12:10')
        self.assertEqual(points['elder']['last']['subject'], 'колледж')

    def test_day_text_lists_lessons_and_pickup(self):
        text = report.day_text(store.SEED, 'mon')
        self.assertIn('13:15–13:55', text)
        self.assertIn('конец в 19:25', text)
        self.assertIn('19:25', text)

    def test_physics_renamed_to_physical_education(self):
        subjects = [subject for child in store.SEED['children'].values()
                    for lessons in child['week'].values() for _, _, subject in lessons]
        self.assertNotIn('физика', subjects)
        self.assertIn('физра', subjects)

    def test_stored_physics_is_normalized_on_load(self):
        stored = {'children': {'middle': {'name': 'Мария', 'week': {'tue': [['14:50', '15:35', 'физика']]}}}}
        with patch.object(store, '_request', return_value=[{'state_value': json.dumps(stored)}]):
            data = store.load(1)
        self.assertEqual(data['children']['middle']['week']['tue'][0][2], 'физра')

    def test_keyboard_has_all_week_days(self):
        markup = handlers.keyboard(store.SEED, 'mon')
        days = [button.callback_data for row in markup.inline_keyboard for button in row
                if button.callback_data.startswith('kids:day:')]
        self.assertEqual(days, ['kids:day:' + key for key in ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')])

    def test_other_day_is_reachable_from_monday(self):
        markup = handlers.keyboard(store.SEED, 'mon')
        labels = [button.callback_data for row in markup.inline_keyboard for button in row]
        self.assertIn('kids:day:fri', labels)
        self.assertIn('kids:day:sun', labels)

    def test_saturday_text_says_no_lessons(self):
        self.assertIn('Суббота: занятий нет.', report.day_text(store.SEED, 'sat'))

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
        self.assertEqual(service.kids_line(value), 'ДЕТИ: Мария, дата рождения 2016-02-21, 5 А')
        groups = {'facts': [], 'memory_entries': [],
                  'user_states': [{'state_key': 'kids_schedule', 'state_value': value, 'unit': None}]}
        text = service.format_memory(groups)
        self.assertIn('Мария', text)
        self.assertNotIn('children', text)

    def test_day_text_names_maria(self):
        self.assertIn('Мария', report.day_text(store.SEED, 'wed'))


    def test_seed_has_elder_daughter(self):
        elder = store.SEED['children']['elder']
        self.assertEqual(elder['name'], 'Ксения')
        self.assertEqual(elder['birthday'], '2011-07-18')
        self.assertEqual(elder['grade'], 'юридический колледж')
        self.assertEqual(elder['week']['mon'], [('08:00', '12:30', 'колледж')])

    def test_ensure_adds_elder_to_existing_data(self):
        data = {'children': {'middle': {'name': 'Мария', 'birthday': '2016-02-21', 'grade': '5 А',
                                        'week': {'mon': [('13:15', '13:55', 'матем')]}}},
                'enabled': True, 'sent': {}}
        with patch.object(store, 'load', return_value=data), patch.object(store, 'save') as save:
            store.ensure(1)
        self.assertEqual(data['children']['elder']['name'], 'Ксения')
        save.assert_called_once()

    def test_memory_line_lists_both_children(self):
        value = json.dumps({'children': store.SEED['children']}, ensure_ascii=False)
        line = service.kids_line(value)
        self.assertIn('Мария, дата рождения 2016-02-21, 5 А', line)
        self.assertIn('Ксения, дата рождения 2011-07-18, юридический колледж', line)

    def test_empty_day_mentions_missing_schedule(self):
        data = json.loads(json.dumps(store.SEED))
        data['children']['elder']['week'] = {}
        text = report.day_text(data, 'sat')
        self.assertIn('Ксения', text)
        self.assertIn('ещё не добавлено', text)


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
        marks = data['sent'][THU.date().isoformat()]['middle']
        self.assertTrue(marks['before'])
        self.assertTrue(marks['end'])
        self.assertEqual(save.call_count, 2)

    async def test_elder_gets_her_own_morning_reminder(self):
        app = self.app()
        item = worker.Worker(app, 1)
        data = {'enabled': True, 'children': store.SEED['children'], 'sent': {}}
        with patch.object(store, 'ensure', return_value=data), patch.object(store, 'save'):
            await item.tick(THU.replace(hour=12, minute=10))
        app.bot.send_message.assert_awaited_once()
        text = app.bot.send_message.call_args.args[1]
        self.assertIn('Ксения', text)

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
        query = NS(data='kids:done:middle', message=message, answer=AsyncMock())
        update = NS(callback_query=query, message=message, effective_user=NS(id=1),
                    effective_chat=NS(type='private', id=1))
        data = {'enabled': True, 'children': store.SEED['children'], 'sent': {}}
        with patch.object(handlers, 'owner_allowed', return_value=True), \
             patch.object(store, 'ensure', return_value=data), \
             patch.object(store, 'save') as save:
            await handlers.callback(update, NS(user_data={}))
        marks = data['sent'][store.local_now().date().isoformat()]['middle']
        self.assertTrue(marks['before'] and marks['end'])
        save.assert_called_once()
        self.assertIn('забрал', message.reply_text.call_args.args[0].lower())


if __name__ == '__main__':
    unittest.main()
