import asyncio
import unittest
from datetime import date
from types import SimpleNamespace as N
from unittest.mock import AsyncMock, patch
from x2pos import calendar_ui, handlers

def callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]

class CalendarTests(unittest.TestCase):
    def test_leap_year_and_year_navigation(self):
        now=date(2026,10,12)
        self.assertIn('x2pos:day:2024-02-29', callbacks(calendar_ui.keyboard(2024,2,now)))
        self.assertNotIn('x2pos:day:2025-02-29', callbacks(calendar_ui.keyboard(2025,2,now)))
        self.assertIn('x2pos:month:2025:1', callbacks(calendar_ui.keyboard(2024,12,now)))
        self.assertIn('x2pos:month:2024:12', callbacks(calendar_ui.keyboard(2025,1,now)))

    def test_future_and_invalid_dates(self):
        now=date(2026,10,12)
        values=callbacks(calendar_ui.keyboard(2026,10,now))
        self.assertIn('x2pos:day:2026-10-12',values)
        self.assertIn('x2pos:day:2026-10-13',values)
        self.assertIn('x2pos:day:2026-10-31',values)
        self.assertIn('x2pos:month:2026:11',values)
        self.assertIn('x2pos:day:2027-01-31',callbacks(calendar_ui.keyboard(2027,1,now)))
        self.assertEqual(calendar_ui.selected('1999-12-31',now),date(1999,12,31))
        for y,m in ((2026,0),(2026,13),(0,12),(10000,1)):
            with self.assertRaises(ValueError): calendar_ui.keyboard(y,m,now)
        for value in ('2025-02-29','2026-09-31','bad'):
            with self.assertRaises(ValueError): calendar_ui.selected(value,now)

    def test_callbacks_date_and_owner(self):
        for owner,data in ((123,'x2pos:day:2024-02-29'),(999,'x2pos:sales'),
                           (123,'x2pos:month:2026:13'),(123,'x2pos:check')):
            q=N(answer=AsyncMock(),edit_message_text=AsyncMock(),
                message=N(reply_text=AsyncMock()),data=data)
            update=N(effective_user=N(id=owner),effective_chat=N(id=owner,type='private'),callback_query=q)
            with patch.dict('os.environ',{'X2POS_OWNER_ID':'123'}),patch.object(calendar_ui,'today',return_value=date(2026,10,12)):
                asyncio.run(handlers.callback(update,N(user_data={})))
            if owner==999:
                q.message.reply_text.assert_not_awaited()
                q.edit_message_text.assert_not_awaited()
            elif data.startswith('x2pos:day'):
                self.assertIn('29.02.2024',q.edit_message_text.call_args.args[0])
                self.assertIn('Выбери конец периода',q.edit_message_text.call_args.args[0])
            elif data.startswith('x2pos:month'):
                self.assertIn('недоступна',q.message.reply_text.call_args.args[0])
            else:
                self.assertIn('Меню обновлено',q.message.reply_text.call_args.args[0])


    def test_range_preserved_on_month_navigation(self):
        start=date(2025,12,15)
        values=callbacks(calendar_ui.keyboard(2025,12,date(2026,10,12),start=start))
        self.assertIn('x2pos:month:2026:1:2025-12-15',values)
        self.assertIn('x2pos:day:2025-12-31:2025-12-15',values)
        self.assertIn('x2pos:sales',values)

    def test_inclusive_ranges_and_wrong_order(self):
        cases=[('2026-09-01','2026-09-30',30),
               ('2026-10-01','2026-10-31',31),
               ('2026-01-01','2027-12-31',730),
               ('1999-01-01','2000-12-31',731),
               ('2026-09-01','2026-09-01',1),
               ('2025-12-31','2026-01-01',2),
               ('2024-02-28','2024-03-01',3),
               ('2026-09-30','2026-09-01',None)]
        for start,end,days in cases:
            with self.subTest(start=start,end=end):
                q=N(answer=AsyncMock(),edit_message_text=AsyncMock(),
                    message=N(reply_text=AsyncMock()),data=f'x2pos:day:{end}:{start}')
                update=N(effective_user=N(id=123),effective_chat=N(id=123,type='private'),callback_query=q)
                with patch.dict('os.environ',{'X2POS_OWNER_ID':'123'}),patch.object(calendar_ui,'today',return_value=date(2026,10,12)):
                    asyncio.run(handlers.callback(update,N(user_data={})))
                result=q.edit_message_text.call_args.args[0]
                if days is None:
                    self.assertIn('не может быть раньше',result)
                    self.assertIn(f'x2pos:day:{end}:{start}',callbacks(q.edit_message_text.call_args.kwargs['reply_markup']))
                else:
                    self.assertIn(f'Дней: {days} ',result)
                    self.assertIn('пока не подключён',result)


    def test_calendar_date_boundaries(self):
        first=callbacks(calendar_ui.keyboard(1,1))
        last=callbacks(calendar_ui.keyboard(9999,12))
        self.assertIn('x2pos:day:0001-01-01',first)
        self.assertNotIn('x2pos:month:0:12',first)
        self.assertIn('x2pos:day:9999-12-31',last)
        self.assertNotIn('x2pos:month:10000:1',last)
