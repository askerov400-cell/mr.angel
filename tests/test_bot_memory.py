import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import bot


def update(chat_type="private", chat_id=12):
    return SimpleNamespace(
        message=SimpleNamespace(text="Synthetic message", reply_text=AsyncMock()),
        effective_user=SimpleNamespace(id=12),
        effective_chat=SimpleNamespace(id=chat_id, type=chat_type),
    )


class BotMemoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        bot.conversation_memory.clear()

    async def test_private_message_saves_then_uses_memory(self):
        incoming = update()
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Test reply"))])
        ctx = SimpleNamespace(bot=SimpleNamespace(send_chat_action=AsyncMock()))
        with patch.object(bot, "BACKEND", "supabase"), \
                patch.object(bot.automatic_memory, "process", new=AsyncMock(return_value="saved")) as process, \
                patch.object(bot.automatic_memory, "context", new=AsyncMock(return_value="FACT: synthetic")), \
                patch.object(bot.deepseek.chat.completions, "create", new=AsyncMock(return_value=response)) as answer:
            await bot.handle_message(incoming, ctx)
            process.assert_awaited_once_with(12, "Synthetic message")
            system = answer.call_args.kwargs["messages"][1]["content"]
            self.assertIn("FACT: synthetic", system)
            self.assertIn("saved", system)
            incoming.message.reply_text.assert_awaited_once_with("Test reply")

    async def test_group_cannot_read_or_write_private_memory(self):
        incoming = update("group", -100)
        bot.conversation_memory[(12, 12)] = [{"role": "user", "content": "private marker"}]
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Test reply"))])
        ctx = SimpleNamespace(bot=SimpleNamespace(send_chat_action=AsyncMock()))
        with patch.object(bot, "BACKEND", "supabase"), \
                patch.object(bot.automatic_memory, "process", new=AsyncMock()) as process, \
                patch.object(bot.automatic_memory, "context", new=AsyncMock()) as memory, \
                patch.object(bot.deepseek.chat.completions, "create", new=AsyncMock(return_value=response)) as answer:
            await bot.handle_message(incoming, ctx)
            process.assert_not_awaited()
            memory.assert_not_awaited()
            self.assertNotIn("private marker", str(answer.call_args.kwargs["messages"]))

    async def test_memory_command_in_group_does_not_read_database(self):
        incoming = update("group", -100)
        with patch.object(bot.automatic_memory, "context", new=AsyncMock()) as memory:
            await bot.show_memory(incoming, SimpleNamespace())
            memory.assert_not_awaited()
            incoming.message.reply_text.assert_awaited_once()
