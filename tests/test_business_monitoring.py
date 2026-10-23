import asyncio
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace as N
from unittest.mock import AsyncMock, patch
import notifications
from x2pos import reports, business_store as store, analytics, monitor, dialogue, client, expenses
from tests.test_sales_reports import order, page

NOW=datetime(2026,10,12,12,0,tzinfo=analytics.ZONE)
ENV={'X2POS_OWNER_ID':'123','X2POS_BRANCH_ID':'7'}

def data():
    rows={}
    for i in range(90):
        d=NOW.date()-timedelta(days=i)
        m=reports.empty_day()
        m.update(total=Decimal('20000'),sales_total=Decimal('20000'),sales_count=4)
        m['hours'][10]=Decimal('20000')
        rows[d.isoformat()]=m
    return rows

class AnalyticsTests(unittest.TestCase):
    def test_daily_aggregation_and_unknown_cost(self):
        row=order();row['order_items']={'1':{'buy_total_fifo':'60','buy_total_average':'65'}}
        with patch.object(client,'employee',return_value={'branch':'7'}),patch.object(client,'request',side_effect=[page(row),page()]):
            result=reports.sales(date(2026,9,1),date(2026,9,2),daily=True)
        self.assertEqual(len(result['daily']),2)
        m=result['daily']['2026-09-01']
        self.assertEqual(m['hours'][5],Decimal('100.10'))
        self.assertEqual(m['cost_fifo'],60)
        self.assertEqual(result['daily']['2026-09-02']['total'],0)
        self.assertIsNone(reports.costs(order(),'0')['cost_fifo'])

    def test_alert_threshold_and_same_completed_hours(self):
        rows=data();current=rows[NOW.date().isoformat()]
        current['hours'][10]=Decimal('10000')
        current['hours'][12]=Decimal('999999')
        text=analytics.drop_alert(rows,NOW)
        self.assertIn('50.0%',text)
        self.assertIn('причина',text)
        self.assertIsNone(analytics.drop_alert(rows,NOW.replace(hour=11)))
        current['hours'][10]=Decimal('15000')
        self.assertIsNone(analytics.drop_alert(rows,NOW))
        rows.pop((NOW.date()-timedelta(days=7)).isoformat())
        self.assertIsNone(analytics.drop_alert(rows,NOW))

    def test_stale_context_and_no_private_identifiers(self):
        text=analytics.context_text({'last_success':(NOW-timedelta(minutes=20)).isoformat()},data(),
            [{'day':'2026-10-11','recorded_at':NOW.isoformat(),'owner':999,'branch':'private'}],NOW)
        self.assertIn('устарели',text)
        self.assertNotIn('"owner"',text)
        self.assertNotIn('private',text)

    def test_other_owner_cannot_read(self):
        with patch.dict('os.environ',ENV),patch.object(store,'_request') as request:
            with self.assertRaises(Exception):store.read(999)
            request.assert_not_called()

    def test_business_context_only_private_owner(self):
        with patch.dict('os.environ',ENV):
            for uid,kind,expected in ((123,'private',True),(999,'private',False),(123,'group',False)):
                update=N(effective_user=N(id=uid),effective_chat=N(id=uid,type=kind))
                self.assertEqual(dialogue.active(update,N(user_data={}), 'Как идут продажи?'),expected)

class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_claim_prevents_duplicate_sends_and_busy_skips(self):
        worker=monitor.Monitor(N(send_message=AsyncMock()))
        with patch.dict('os.environ',ENV),patch.object(notifications,'ALLOWED',{'business'}),patch.object(store,'claim',side_effect=[True,False]):
            await worker.notify('daily',NOW.date(),'synthetic')
            await worker.notify('daily',NOW.date(),'synthetic')
        worker.bot.send_message.assert_awaited_once()
        with patch.object(expenses,'report',side_effect=reports.Busy('busy')),patch.object(store,'save') as save:
            await worker.tick(NOW)
            save.assert_not_called()
        self.assertEqual(worker.failures,0)

    async def test_notifications_off_by_default(self):
        worker=monitor.Monitor(N(send_message=AsyncMock()))
        with patch.dict('os.environ',ENV),patch.object(store,'claim') as claim:
            sent=await worker.notify('daily',NOW.date(),'synthetic')
        self.assertFalse(sent)
        claim.assert_not_called()
        worker.bot.send_message.assert_not_awaited()

    async def test_failed_sync_keeps_previous_snapshot(self):
        worker=monitor.Monitor(N(send_message=AsyncMock()))
        with patch.object(expenses,'report',side_effect=client.X2Error('unavailable')),patch.object(store,'error'),patch.object(store,'save') as save,patch.object(worker,'notify',new=AsyncMock()) as notify:
            for _ in range(3):await worker.tick(NOW)
            save.assert_not_called()
            notify.assert_awaited_once()
            self.assertEqual(notify.call_args.args[0],'failure')

    async def test_successful_sync_precedes_notifications(self):
        worker=monitor.Monitor(N(send_message=AsyncMock()))
        with patch.object(expenses,'report',return_value={'daily':data()}) as fetch,patch.object(store,'save') as save,patch.object(worker,'notify',new=AsyncMock()) as notify:
            await worker.tick(NOW)
            self.assertEqual(fetch.call_args.kwargs,{})
            self.assertEqual((fetch.call_args.args[1]-fetch.call_args.args[0]).days+1,90)
            save.assert_called_once()
            notify.assert_awaited_once()
            self.assertEqual(notify.call_args.args[0],'daily')


class PeriodTests(unittest.TestCase):
    def test_explicit_period_and_named_month(self):
        self.assertEqual(dialogue.period('Продажи 01.09.2026 — 30.09.2026',NOW),(date(2026,9,1),date(2026,9,30)))
        self.assertEqual(dialogue.period('Продажи за сентябрь',NOW),(date(2026,9,1),date(2026,9,30)))
        self.assertEqual(dialogue.period('Продажи за прошлый месяц',NOW),(date(2026,9,1),date(2026,9,30)))
        start,end=dialogue.period('Продажи за 730 дней',NOW)
        self.assertEqual((end-start).days+1,730)
