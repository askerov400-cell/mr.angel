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
    def test_last_sent_ordinal(self):
        with patch.object(monitor, "_request", return_value=[{"state_value": 739700}]) as req:
            self.assertEqual(monitor.last_sent(123), 739700)
        self.assertIn("state_key", req.call_args.kwargs["params"])

    def test_last_sent_missing(self):
        with patch.object(monitor, "_request", return_value=[]):
            self.assertIsNone(monitor.last_sent(123))

    def test_last_sent_ignores_bool(self):
        with patch.object(monitor, "_request", return_value=[{"state_value": True}]):
            self.assertIsNone(monitor.last_sent(123))

    def test_claim_first_write(self):
        with patch.object(monitor, "_request", return_value=[{"saved": True}]) as req:
            self.assertTrue(monitor.claim(123, date(2026, 11, 15)))
        record = req.call_args.kwargs["record"]
        self.assertEqual(record["p_key"], monitor.KEY)
        self.assertEqual(record["p_value"], date(2026, 11, 15).toordinal())
        self.assertEqual(record["p_confidence"], 1.0)

    def test_claim_repeat_false(self):
        with patch.object(monitor, "_request", return_value=[{"saved": False}]):
            self.assertFalse(monitor.claim(123, date(2026, 11, 15)))


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

    async def test_after_0905_claims_and_sends(self):
        m = self.monitor()
        now = datetime(2026, 11, 16, 9, 5, tzinfo=ZONE)
        yesterday = now.date() - timedelta(days=1)
        with patch.object(monitor, "last_sent", return_value=None), \
             patch.object(monitor, "claim", return_value=True) as claim, \
             patch.object(statistics, "summary", new=AsyncMock(return_value="сводка")) as summary:
            await m.tick(now)
        summary.assert_awaited_once()
        self.assertEqual(summary.call_args.args[0], yesterday)
        claim.assert_called_once()
        m.bot.send_message.assert_awaited_once()

    async def test_already_sent_skips(self):
        m = self.monitor()
        now = datetime(2026, 11, 16, 9, 5, tzinfo=ZONE)
        target = (now.date() - timedelta(days=1)).toordinal()
        with patch.object(monitor, "last_sent", return_value=target), \
             patch.object(statistics, "summary", new=AsyncMock()) as summary, \
             patch.object(monitor, "claim") as claim:
            await m.tick(now)
        summary.assert_not_awaited()
        claim.assert_not_called()
        m.bot.send_message.assert_not_awaited()

    async def test_claim_false_no_send(self):
        m = self.monitor()
        now = datetime(2026, 11, 16, 9, 5, tzinfo=ZONE)
        with patch.object(monitor, "last_sent", return_value=None), \
             patch.object(monitor, "claim", return_value=False) as claim, \
             patch.object(statistics, "summary", new=AsyncMock(return_value="сводка")):
            await m.tick(now)
        claim.assert_called_once()
        m.bot.send_message.assert_not_awaited()

    async def test_kaspi_error_no_claim_no_send(self):
        m = self.monitor()
        now = datetime(2026, 11, 16, 9, 5, tzinfo=ZONE)
        with patch.object(monitor, "last_sent", return_value=None), \
             patch.object(monitor, "claim") as claim, \
             patch.object(statistics, "summary", new=AsyncMock(side_effect=KaspiError("unavailable"))):
            await m.tick(now)
        claim.assert_not_called()
        m.bot.send_message.assert_not_awaited()

    async def test_claim_failure_no_send(self):
        m = self.monitor()
        now = datetime(2026, 11, 16, 9, 5, tzinfo=ZONE)
        with patch.object(monitor, "last_sent", return_value=None), \
             patch.object(monitor, "claim", side_effect=RuntimeError("db down")), \
             patch.object(statistics, "summary", new=AsyncMock(return_value="сводка")):
            await m.tick(now)
        m.bot.send_message.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
