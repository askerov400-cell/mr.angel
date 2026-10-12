import unittest
from datetime import date,datetime
from decimal import Decimal
from types import SimpleNamespace as N
from unittest.mock import patch
from x2pos import month_ranking as ranking,dialogue,analytics,expenses,reports,client
from tests.test_sales_reports import order,page
from tests.test_expenses import payment,payments

NOW=datetime(2026,10,12,tzinfo=analytics.ZONE)
TEXT='Какой из месяцев за всё время был самый доходный'
def row(total,fifo,average,expense=0):
    value=reports.empty_day();value.update(expenses.empty_day())
    value.update(total=Decimal(total),sales_total=Decimal(total),cost_fifo=Decimal(fifo),cost_average=Decimal(average),expenses_total=Decimal(expense))
    return value

class RankingTests(unittest.TestCase):
    def test_confirmed_debt_collection_excluded_other_expenses_included(self):
        debt={**payment('1'),'operation_type_id':'270','is_debt_payment':'1'}
        collection={**payment('2'),'operation_type_id':'1'}
        tax={**payment('3'),'operation_type_id':'154'}
        returned={**payment('4'),'operation_type_id':'270','is_debt_payment':'1','is_returned':'1'}
        with patch.dict('os.environ',{'X2POS_EXPENSE_CATEGORY_IDS':'3,30,154','X2POS_EXCLUDED_PAYMENT_CATEGORY_IDS':'1,270'}),patch.object(client,'employee',return_value={'branch':'7'}),patch.object(client,'request',side_effect=[payments(debt,collection,tax,returned),payments()]):
            data=expenses.fetch(date(2026,9,1),date(2026,9,30))['2026-09-01']
        self.assertEqual(data['excluded_count'],2)
        self.assertEqual(data['expenses_count'],1)
        self.assertEqual(data['unknown_count'],1)

    def test_exact_request_after_restart_and_scope(self):
        self.assertTrue(ranking.requested(TEXT));self.assertTrue(dialogue.report_requested(TEXT))
        with patch.dict('os.environ',{'X2POS_OWNER_ID':'123'}):
            self.assertTrue(dialogue.active(N(effective_user=N(id=123),effective_chat=N(id=123,type='private')),N(user_data={}),TEXT))
        self.assertEqual(ranking.bounds(TEXT,NOW),(date.min,NOW.date()))
        self.assertEqual(ranking.bounds('Какой месяц самый прибыльный в 2025 году',NOW),(date(2025,1,1),date(2025,12,31)))

    def test_different_profit_winners_current_month_excluded(self):
        days={'2026-07-05':row(100,20,80),'2026-08-05':row(110,90,10),'2026-09-05':row(120,110,110), '2026-10-05':row(999999,0,0)}
        values=ranking.months(days,date.min,NOW.date(),NOW)
        text=ranking.format_ranking(values,days,TEXT,NOW)
        self.assertEqual(len(values),3)
        self.assertIn('FIFO: 2026-07 — 80,00',text)
        self.assertIn('по средней: 2026-08 — 100,00',text)
        self.assertNotIn('FIFO: 2026-10',text)
        revenue=ranking.format_ranking(values,days,'Какой месяц был самый большой по выручке',NOW)
        self.assertIn('Выручка с возвратами: 2026-09 — 120,00',revenue)

    def test_empty_intermediate_month_and_missing_cost_no_absolute_claim(self):
        days={'2026-07-05':row(100,120,120),'2026-09-05':row(100,200,200)}
        values=ranking.months(days,date.min,NOW.date(),NOW)
        self.assertEqual(analytics.profit(values['2026-08'],'cost_fifo'),0)
        days['2026-09-05']['cost_fifo']=None
        values=ranking.months(days,date.min,NOW.date(),NOW)
        text=ranking.format_ranking(values,days,TEXT,NOW)
        self.assertIn('Абсолютный лидер за всё время не подтверждён',text)
        self.assertIn('FIFO: 2026-08',text)

    def test_empty_and_current_only(self):
        self.assertEqual(ranking.months({},date.min,NOW.date(),NOW),{})
        days={'2026-10-05':row(100,0,0)}
        self.assertEqual(ranking.months(days,date.min,NOW.date(),NOW),{})
        self.assertIn('нет завершённых месяцев',ranking.format_ranking({},days,TEXT,NOW))

    def test_sparse_history_merges_payments_only_days(self):
        sale=order();sale['order_items']={'1':{'buy_total_fifo':'60','buy_total_average':'65'}}
        expense={**payment(),'date_of_payment':'2026-08-01 00:00:00'}
        with patch.dict('os.environ',{'X2POS_EXPENSE_CATEGORY_IDS':'2'}),patch.object(client,'employee',return_value={'branch':'7'}),patch.object(client,'request',side_effect=[page(sale),page(),payments(expense),payments()]):
            result=expenses.report(date.min,NOW.date(),sparse=True)
        self.assertEqual(set(result['daily']),{'2026-09-01','2026-08-01'})
        self.assertEqual(result['daily']['2026-09-01']['expenses_total'],0)
        self.assertEqual(result['daily']['2026-08-01']['total'],0)
        self.assertEqual(result['expenses_total'],Decimal('25.05'))

class RankingRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_route_uses_all_time_ranking(self):
        with patch.object(dialogue.store,'identity',return_value=(123,'7')),patch.object(ranking,'answer',return_value='Full history ranking') as rank,patch.object(dialogue,'requested_snapshot') as current:
            text=await dialogue.direct_answer(123,TEXT)
        self.assertEqual(text,'Full history ranking');rank.assert_called_once();current.assert_not_called()
