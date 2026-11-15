import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

from archive import handlers as archive


def incoming(text="", owner=12, chat=12, kind="private"):
    return NS(
        message=NS(text=text),
        effective_user=NS(id=owner),
        effective_chat=NS(id=chat, type=kind),
    )


def callback(data, owner=12, chat=12, kind="private"):
    update = NS(
        callback_query=NS(answer=AsyncMock(), data=data, message=NS()),
        effective_user=NS(id=owner),
        effective_chat=NS(id=chat, type=kind),
    )
    return update


class ArchivePanelTests(unittest.IsolatedAsyncioTestCase):
    def context(self):
        return NS(user_data={})

    async def test_panel_private_only(self):
        context = self.context()
        with patch.object(archive, "send_reply", new=AsyncMock()) as reply:
            await archive.panel(incoming(kind="group"), context)
        reply.assert_awaited_once()

    async def test_panel_shows_keyboard(self):
        context = self.context()
        context.user_data[archive.PENDING_KEY] = "car"
        with patch.object(archive, "send_reply", new=AsyncMock()) as reply:
            await archive.panel(incoming(), context)
        self.assertNotIn(archive.PENDING_KEY, context.user_data)
        self.assertIsNotNone(reply.await_args.kwargs.get("reply_markup"))

    async def test_callback_select_sets_pending(self):
        context = self.context()
        update = callback("archive:recipes")
        with patch.object(archive, "send_reply", new=AsyncMock()) as reply:
            await archive.callback(update, context)
        self.assertEqual(context.user_data[archive.PENDING_KEY], "recipes")
        self.assertTrue(reply.await_args.args[1].startswith("Архив · Рецепты еды"))

    async def test_callback_unknown_section(self):
        context = self.context()
        update = callback("archive:nope")
        with patch.object(archive, "send_reply", new=AsyncMock()) as reply:
            await archive.callback(update, context)
        self.assertNotIn(archive.PENDING_KEY, context.user_data)
        self.assertTrue(reply.await_args.args[1].startswith("Архив: раздел не найден"))

    async def test_callback_cancel_clears_pending(self):
        context = self.context()
        context.user_data[archive.PENDING_KEY] = "car"
        update = callback("archive:cancel")
        with patch.object(archive, "send_reply", new=AsyncMock()):
            await archive.callback(update, context)
        self.assertNotIn(archive.PENDING_KEY, context.user_data)

    async def test_callback_group_ignored(self):
        context = self.context()
        update = callback("archive:car", kind="group")
        with patch.object(archive, "send_reply", new=AsyncMock()) as reply:
            await archive.callback(update, context)
        self.assertNotIn(archive.PENDING_KEY, context.user_data)
        reply.assert_not_awaited()


class ArchiveSaveTests(unittest.IsolatedAsyncioTestCase):
    def context(self):
        return NS(user_data={})

    async def test_no_pending_returns_false(self):
        context = self.context()
        self.assertFalse(await archive.save_pending(incoming("hello"), context, "hello"))

    async def test_save_text_fact_with_category(self):
        context = self.context()
        context.user_data[archive.PENDING_KEY] = "work_photos"
        with patch.object(archive, "send_reply", new=AsyncMock()), \
             patch.object(archive, "add_fact", new=MagicMock(return_value=1)) as add:
            self.assertTrue(await archive.save_pending(incoming("Отчёт за день"), context, "Отчёт за день"))
        add.assert_called_once_with(
            telegram_user_id=12,
            category="Рабочие фото",
            fact_text="Отчёт за день",
            source="user_explicit",
            confidence=1.0,
        )
        self.assertNotIn(archive.PENDING_KEY, context.user_data)

    async def test_empty_text_not_saved(self):
        context = self.context()
        context.user_data[archive.PENDING_KEY] = "car"
        with patch.object(archive, "send_reply", new=AsyncMock()), \
             patch.object(archive, "add_fact", new=MagicMock()) as add:
            self.assertTrue(await archive.save_pending(incoming(""), context, "   "))
        add.assert_not_called()
        self.assertNotIn(archive.PENDING_KEY, context.user_data)

    async def test_clear_pending(self):
        context = self.context()
        context.user_data[archive.PENDING_KEY] = "car"
        archive.clear_pending(context)
        self.assertNotIn(archive.PENDING_KEY, context.user_data)


if __name__ == "__main__":
    unittest.main()
