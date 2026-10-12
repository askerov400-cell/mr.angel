import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from x2pos import client, reports

START=date(2026,9,1)
END=date(2026,9,30)

def order(oid='1', total='100.10', **extra):
    return dict(id=oid, branch_id='7', order_date='2026-09-01 00:00:00',
                status='completed', is_return='0', total=total,
                discount_value='5', order_items={'1':{'discount_fact':'10'}},
                payments={'1':{'sum':'999999'}}, **extra)

def page(*rows):
    return {'status':'success','orders':list(rows)}

class SalesTests(unittest.TestCase):
    def calculate(self, responses):
        with patch.object(client,'employee',return_value={'branch':'7'}),patch.object(client,'request',side_effect=responses) as request:
            result=reports.sales(START,END)
        return result, request

    def test_sequential_pages_returns_cancel_and_no_double_discount(self):
        returned=order('2','-20.05'); returned['is_return']='1'
        canceled=order('3','999'); canceled['status']='canceled'
        result,request=self.calculate([page(order(),returned),page(canceled,order('4','10')),page()])
        self.assertEqual(result['total'],Decimal('90.05'))
        self.assertEqual(result['sales_total'],Decimal('110.10'))
        self.assertEqual(result['returns_total'],Decimal('-20.05'))
        self.assertEqual((result['sales_count'],result['returns_count'],result['canceled_count']),(2,1,1))
        self.assertEqual([x.args[1]['page'] for x in request.call_args_list],[1,2,3])
        for call in request.call_args_list:
            self.assertEqual(call.args[0],'/orders')
            self.assertEqual(call.args[1],dict(branch_id='7',date_start='2026-09-01',date_end='2026-09-30',per_page=500,page=call.args[1]['page']))

    def test_utc_to_local_and_inclusive_boundary(self):
        row=order();row['order_date']='2026-08-31 19:00:00'
        self.assertEqual(self.calculate([page(row),page()])[0]['sales_count'],1)
        self.assertEqual(reports.local_day('2026-09-30T18:59:59Z'),END)
        self.assertEqual(reports.local_day('2026-09-30T19:00:00Z'),date(2026,10,1))

    def test_empty_is_confirmed_zero(self):
        result,_=self.calculate([page()])
        self.assertEqual(result['total'],0)

    def test_bad_schema_or_rows_never_partial_total(self):
        variants=[{'status':'success'}, {'status':'error','orders':[]}, page(order(),order()),
                  page({**order(),'branch_id':'8'}),page({**order(),'total':None}),
                  page({**order(),'total':'NaN'}),page({**order(),'is_return':'1'}),
                  page({**order(),'total':'-1'}),page({**order(),'status':None}),
                  page({**order(),'order_date':'2026-10-01 00:00:00'}),
                  page({**order(),'is_deleted':'1'})]
        for response in variants:
            with self.subTest(response_type=type(response).__name__),self.assertRaises(client.X2Error):
                self.calculate([response,page()])

    def test_page_error_duplicate_and_gate_release(self):
        for responses in ([page(order()),client.X2Error('X2POS вернул HTTP 429.')],
                          [page(order()),page(order())]):
            with self.assertRaises(client.X2Error): self.calculate(responses)
            self.assertFalse(reports.GATE.locked())

    def test_competing_report_does_not_request(self):
        reports.GATE.acquire()
        try:
            with patch.object(client,'employee') as request,self.assertRaises(client.X2Error):
                reports.sales(START,END)
            request.assert_not_called()
        finally:
            reports.GATE.release()

    def test_deadline_no_partial_result(self):
        with patch.object(reports.time,'monotonic',side_effect=[0,181]),patch.object(client,'employee',return_value={'branch':'7'}),patch.object(client,'request') as request:
            with self.assertRaises(client.X2Error): reports.sales(START,END)
            request.assert_not_called()
        self.assertFalse(reports.GATE.locked())
