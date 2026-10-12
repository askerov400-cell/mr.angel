import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from x2pos import expenses,client,analytics,reports,monitor
from tests.test_sales_reports import order,page

START=date(2026,9,1);END=date(2026,9,30)
ENV={'X2POS_EXPENSE_CATEGORY_IDS':'2,5','X2POS_EXPENSES_COMPLETE':'1'}
def payment(pid='1',**kw):
    return dict(id=pid,branch_id='7',operation='credit',date_of_payment='2026-08-31 19:00:00',
        amount='-25.05',operation_type_id='2',is_deleted='0',is_returned='0',**kw)
def payments(*rows):return {'status':'success','payments':list(rows)}

class ExpenseTests(unittest.TestCase):
    def fetch(self,responses):
        with patch.dict('os.environ',ENV),patch.object(client,'employee',return_value={'branch':'7'}),patch.object(client,'request',side_effect=responses) as req:
            return expenses.fetch(START,END),req

    def test_all_pages_expenses_exclusions_unknown_and_empty_days(self):
        rows=[payment(),payment('2',order_id='99'),payment('3',procurement_id='66'),
            payment('4',source_account_id='77'),{**payment('5'),'operation_type_id':'999'},
            {**payment('6'),'is_returned':'1'},{**payment('7'),'is_deleted':'1'}]
        result,req=self.fetch([payments(*rows[:3]),payments(*rows[3:]),payments()])
        first=result['2026-09-01']
        self.assertEqual(first['expenses_total'],Decimal('25.05'))
        self.assertEqual(first['excluded_count'],3)
        self.assertEqual(first['unknown_count'],2)
        self.assertEqual(first['expense_categories'],{'2':Decimal('25.05')})
        self.assertEqual(result['2026-09-02']['expenses_total'],0)
        self.assertEqual([c.args[1]['page'] for c in req.call_args_list],[1,2,3])
        self.assertTrue(all(c.args[0]=='/payments' and c.args[1]['operation']=='credit' for c in req.call_args_list))

    def test_bad_data_never_returns_partial_and_releases_lock(self):
        for row in ({**payment(),'amount':'1'},{**payment(),'amount':'NaN'},
            {**payment(),'branch_id':'8'},{**payment(),'operation':'debit'},
            {**payment(),'date_of_payment':'2026-10-01 00:00:00'},
            {**payment(),'is_deleted':None},{**payment(),'amount':None}):
            with self.subTest(keys=list(row)),self.assertRaises(client.X2Error):self.fetch([payments(row),payments()])
            self.assertFalse(reports.GATE.locked())
        for responses in ([payments(payment()),payments(payment())],
                [payments(payment()),client.X2Error('429')],[{'status':'success','payments':{}}]):
            with self.assertRaises(client.X2Error):self.fetch(responses)
            self.assertFalse(reports.GATE.locked())

    def test_busy_no_network(self):
        reports.GATE.acquire()
        try:
            with patch.object(client,'employee') as req,self.assertRaises(reports.Busy):expenses.fetch(START,END)
            req.assert_not_called()
        finally:reports.GATE.release()

    def test_two_profit_methods_returns_and_missing_data(self):
        row=reports.empty_day();row.update(expenses.empty_day())
        row.update(total=Decimal('80'),sales_total=Decimal('100'),returns_total=Decimal('-20'),
            cost_fifo=Decimal('45'),cost_average=Decimal('50'),expenses_total=Decimal('10'))
        self.assertEqual(analytics.profit(row,'cost_fifo'),25)
        self.assertEqual(analytics.profit(row,'cost_average'),20)
        with patch.dict('os.environ',ENV):self.assertIn('Чистая прибыль',analytics.finance_text(row))
        row['unknown_count']=1
        self.assertIsNone(analytics.profit(row,'cost_fifo'))
        row.pop('expenses_total')
        self.assertIsNone(analytics.profit(row,'cost_average'))

    def test_aggregate_period_unknown_not_zero_and_profit_computed(self):
        rows=[]
        for _ in range(2):
            row=reports.empty_day();row.update(expenses.empty_day())
            row.update(total=Decimal('100'),sales_total=Decimal('100'),cost_fifo=Decimal('50'),expenses_total=Decimal('10'),expense_categories={'2':Decimal('10')})
            rows.append(row)
        combined=analytics.aggregate(rows)
        self.assertEqual(analytics.profit(combined,'cost_fifo'),80)
        self.assertEqual(combined['expense_categories']['2'],20)
        rows[0].pop('expenses_total')
        self.assertIsNone(analytics.aggregate(rows)['expenses_total'])

    def test_report_integrates_full_lists_and_no_notes(self):
        row=order();row['order_items']={'1':{'buy_total_fifo':'60','buy_total_average':'65'}}
        with patch.dict('os.environ',ENV),patch.object(client,'employee',return_value={'branch':'7'}),patch.object(client,'request',side_effect=[page(row),page(),payments(payment(notes='PRIVATE')),payments()]):
            result=expenses.report(START,END)
        self.assertEqual(analytics.profit(result,'cost_fifo'),Decimal('15.05'))
        self.assertEqual(analytics.profit(result,'cost_average'),Decimal('10.05'))
        self.assertNotIn('PRIVATE',str(result))
        self.assertIn('Расходы',reports.format_report(START,END,result))

    def test_payment_failure_aborts_combined_report(self):
        with patch.object(reports,'sales',return_value={'daily':{}}),patch.object(expenses,'fetch',side_effect=client.X2Error('429')):
            with self.assertRaises(client.X2Error):expenses.report(START,END)
