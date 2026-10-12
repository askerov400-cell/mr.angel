import unittest
from unittest.mock import patch
from datetime import date,datetime
from x2pos import dialogue,analytics,reports,expenses,client

NOW=datetime(2026,10,12,tzinfo=analytics.ZONE)
def month(year,number,days):
    return {date(year,number,i).isoformat():{**reports.empty_day(),**expenses.empty_day()} for i in range(1,days+1)}

class AnyMonthTests(unittest.IsolatedAsyncioTestCase):
    def test_months_years_and_followups(self):
        for text,year,number,length in [('Расходы за июнь 2025',2025,6,30),('Прибыль за май',2026,5,31),('За мая 2024',2024,5,31),('за мае 2023',2023,5,31),('за февраль 2024',2024,2,29)]:
            self.assertEqual(dialogue.period(text,NOW),(date(year,number,1),date(year,number,length)))
            self.assertTrue(dialogue.report_requested(text))

    async def test_historical_month_reads_api_not_ninety_day_cache(self):
        rows=month(2025,6,30)
        with patch.object(dialogue.store,'identity',return_value=(123,'7')),patch.object(dialogue.store,'read') as cache,patch.object(expenses,'report',return_value={'daily':rows}) as api:
            text=await dialogue.direct_answer(123,'Покажи расходы и прибыль за июнь 2025')
        api.assert_called_once_with(date(2025,6,1),date(2025,6,30));cache.assert_not_called()
        self.assertIn('01.06.2025 — 30.06.2025',text)
        self.assertIn('0,00',text)
        self.assertNotIn('Статистика продаж',text)

    async def test_analysis_context_also_loads_historical_period(self):
        with patch.object(dialogue.store,'identity',return_value=(123,'7')),patch.object(expenses,'report',return_value={'daily':month(2025,6,30)}) as api:
            text=await dialogue.context(123,'Почему продажи упали за июнь 2025?')
        self.assertIn('2025-06: 30/30 дней; ПОЛНЫЙ МЕСЯЦ.',text)
        api.assert_called_once_with(date(2025,6,1),date(2025,6,30))

    async def test_failed_api_no_partial_totals_and_owner_checked_first(self):
        with patch.object(dialogue.store,'identity',return_value=(123,'7')),patch.object(expenses,'report',side_effect=client.X2Error('HTTP 429')):
            text=await dialogue.direct_answer(123,'Продажи за июнь 2025')
        self.assertIn('Полный итог не рассчитан',text)
        self.assertNotIn('0,00',text)
        with patch.object(dialogue.store,'identity',side_effect=RuntimeError('owner')),patch.object(expenses,'report') as api:
            await dialogue.direct_answer(999,'Расходы за июнь 2025')
        api.assert_not_called()
