import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from x2pos import client, warehouse, handlers


def row(identifier, name, retail="100", wholesale="80", unit="шт"):
    return {"id": identifier, "name": name, "variation": "", "retail": retail,
            "wholesale": wholesale, "unit": unit}


class CollectTests(unittest.TestCase):
    def collect(self, products, stock):
        with patch.object(client, "employee", return_value={"branch": "7", "user": "user"}), \
             patch.object(client, "products", side_effect=products), \
             patch.object(client, "stock", return_value=stock):
            return warehouse.collect()

    def test_totals_and_missing_entries(self):
        data = self.collect([[row("1", "Стеллаж"), row("2", "Полка")], []],
                            {"1": "3", "2": "0"})
        self.assertEqual(data["known"], 2)
        self.assertEqual(data["missing"], 0)
        self.assertEqual(data["units"], 3)
        self.assertEqual(data["retail"], 300)
        self.assertEqual(data["wholesale"], 240)

    def test_missing_stock_is_not_zero(self):
        data = self.collect([[row("1", "Стеллаж"), row("2", "Полка")], []], {"1": "3"})
        self.assertEqual(data["known"], 1)
        self.assertEqual(data["missing"], 1)
        self.assertIsNone(data["rows"][1]["quantity"])
        self.assertEqual(data["units"], 3)

    def test_free_stock_is_excluded(self):
        data = self.collect([[row("1", "Стеллаж")], []], {"1": "0.5"})
        self.assertEqual(data["units"], 0.5)
        self.assertEqual(data["retail"], 50)

    def test_stray_and_unpriced(self):
        data = self.collect([[row("1", "Без цены", retail=None, wholesale=None)], []],
                            {"1": "2", "9": "4"})
        self.assertEqual(data["unpriced"], 1)
        self.assertEqual(data["stray"], 1)
        self.assertEqual(data["retail"], 0)


class TextTests(unittest.TestCase):
    def data(self):
        rows = [row(str(i), "Товар " + str(i)) for i in range(10)]
        for item in rows:
            item["quantity"] = warehouse._dec("1")
        return {"branch": "7", "rows": rows, "known": 10, "missing": 2, "unpriced": 0,
                "units": warehouse._dec("10"), "retail": warehouse._dec("1000"),
                "wholesale": warehouse._dec("800"), "stray": 1}

    def test_summary_names_sources_and_gaps(self):
        text = warehouse.summary_text(self.data())
        self.assertIn("Позиций в каталоге: 10", text)
        self.assertIn("без данных: 2", text)
        self.assertIn("Закупочная: нет данных", text)
        self.assertIn("вне каталога", text)

    def test_list_pages(self):
        data = self.data()
        first, pages = warehouse.list_text(data, 0)
        self.assertEqual(pages, 2)
        self.assertIn("Товар 0", first)
        self.assertNotIn("Товар 9", first)
        second, _ = warehouse.list_text(data, 1)
        self.assertIn("Товар 8", second)


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_summary_uses_cache_without_network(self):
        message = NS(reply_text=AsyncMock())
        context = NS(user_data={"warehouse": TextTests().data()})
        with patch.object(warehouse, "collect") as collect:
            await handlers.warehouse_view(message, context)
        collect.assert_not_called()
        self.assertIn("Остаток на складе", message.reply_text.call_args.args[0])

    async def test_fresh_view_fetches_once(self):
        message = NS(reply_text=AsyncMock())
        context = NS(user_data={})
        data = TextTests().data()
        with patch.object(warehouse, "collect", return_value=data) as collect:
            await handlers.warehouse_view(message, context, refresh=True)
        collect.assert_called_once()
        self.assertIn("warehouse", context.user_data)

    async def test_stock_page_renders_from_cache(self):
        message = NS(reply_text=AsyncMock())
        context = NS(user_data={"warehouse": TextTests().data()})
        with patch.object(warehouse, "collect") as collect:
            await handlers.stock_page(message, context, 1)
        collect.assert_not_called()
        self.assertIn("Товар 8", message.reply_text.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
