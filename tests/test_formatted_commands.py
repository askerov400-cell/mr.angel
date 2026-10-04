import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import bot
from memory.commands import parse


class FormattedCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_formatted_memory_uses_command_handler(self):
        update = SimpleNamespace(message=SimpleNamespace(text="/memory"))
        context = SimpleNamespace(bot=SimpleNamespace(username="guardian"))
        with patch.object(bot, "show_memory", new=AsyncMock()) as memory, \
                patch.object(bot.automatic_memory, "process", new=AsyncMock()) as classifier:
            await bot.handle_formatted_command(update, context)
            memory.assert_awaited_once_with(update, context)
            classifier.assert_not_awaited()

    async def test_clear_erases_only_current_dialogue(self):
        update = SimpleNamespace(message=SimpleNamespace(text="/clear", reply_text=AsyncMock()),
                                 effective_user=SimpleNamespace(id=12),
                                 effective_chat=SimpleNamespace(id=12))
        bot.conversation_memory.clear()
        bot.conversation_memory[(12, 12)] = [{"role": "user", "content": "test"}]
        bot.conversation_memory[(13, 13)] = [{"role": "user", "content": "other"}]
        with patch.object(bot, "send_reply", new=AsyncMock()):
            await bot.handle_formatted_command(update, SimpleNamespace(bot=SimpleNamespace(username="guardian")))
        self.assertEqual(bot.conversation_memory[(12, 12)], [])
        self.assertEqual(len(bot.conversation_memory[(13, 13)]), 1)

    def test_owner_and_standalone_text(self):
        self.assertEqual(parse(" /clear@Guardian ", "guardian"), "clear")
        self.assertIsNone(parse("/clear@other", "guardian"))
        self.assertIsNone(parse("/clear everything", "guardian"))
