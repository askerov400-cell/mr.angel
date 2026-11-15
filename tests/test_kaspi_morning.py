import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from kaspi import monitor, statistics
from kaspi.client import KaspiError

ZONE = ZoneInfo("Asia/Qyzylorda")
ENV = {"KASPI_OWNER_ID": "123"}


class StoreTests(unittest.TestCase):
    def test_last_sent_plain_string(self):
        with patch.object(monitor, "_request", return_value=[{"state_value": "2026-11-15"}]) as req:
            self.assertEqual(monitor.last_sent(123), "2026-11-15")
        self.assertIn("state_key", req.call_args.kwargs["params"])

    def test_last_sent_missing(self):
        with patch.object(monitor, "_request", return_value=[]):
            self.assertIsNone(monitor.last_sent(123))

    def test_mark_sent_writes_state(self):
        with patch.object(monitor, "_request") as req:
            monitor.mark_sent(123, date(2026, 11, 15))
        record = req.call_args.kwargs["record"]
        self.assertEqual(record["p_key"], monitor.KEY)
        self.assertEqual(record["p_value"], '"2026-11-15"')
        self.assertEqual(record["p_confidence"], 1.0)


class TickTests(unittest.IsolatedAsyncioTestCase):
    def monitor(self):
        return monitor.Monitor(NS(send_message=AsyncMock()), "123")

    async def test_before_0905_does_nothing(self):
        m = self.monitor()
        early = datetime(2026, 11, 16, 9, 4, tzinfo=ZONE)
        with patch.object(statistics, "summary", new=AsyncMock()) as summary:
            await m.tick(early)
        summary.assert_not_awaited()
        m.bot.send_message.assert_not_awaited()

    async def test_after_0905_sends_yesterday_summary(self):
        m = self.monitor()
        now = datetime(2026, 11, 16, 9, 5, tzinfo=ZONE)
        yesterday = now.date() - timedelta(days=1)
        with patch.object(monitor, "last_sent", return_value=None), \
             patch.object(monitor, "mark_sent") as mark, \
             patch.object(statistics, "summary", new=AsyncMock(return_value="сводка")) as summary:
            await m.tick(now)
        summary.assert_awaited_once()
        self.assertEqual(summary.call_args.args[0], yesterday)
        mark.assert_called_once()
        m.bot.send_message.assert_awaited_once()

    async def test_already_sent_today_skips(self):
        m = self.monitor()
        now = datetime(2026, 11, 16, 9, 5, tzinfo=ZONE)
        with patch.object(monitor, "last_sent", return_value=(now.date() - timedelta(days=1)).isoformat()), \
             patch.object(statistics, "summary", new=AsyncMock()) as summary, \
             patch.object(monitor, "mark_sent") as mark:
            await m.tick(now)
        summary.assert_not_awaited()
        mark.assert_not_called()
        m.bot.send_message.assert_not_awaited()

    async def test_kaspi_error_no_mark_no_send(self):
        m = self.monitor()
        now = datetime(2026, 11, 16, 9, 5, tzinfo=ZONE)
        with patch.object(monitor, "last_sent", return_value=None), \
             patch.object(monitor, "mark_sent") as mark, \
             patch.object(statistics, "summary", new=AsyncMock(side_effect=KaspiError("unavailable"))):
            await m.tick(now)
        mark.assert_not_called()
        m.bot.send_message.assert_not_awaited()

    async def test_mark_failure_no_send(self):
        m = self.monitor()
        now = datetime(2026, 11, 16, 9, 5, tzinfo=ZONE)
        with patch.object(monitor, "last_sent", return_value=None), \
             patch.object(monitor, "mark_sent", side_effect=RuntimeError("db down")), \
             patch.object(statistics, "summary", new=AsyncMock(return_value="сводка")):
            await m.tick(now)
        m.bot.send_message.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
