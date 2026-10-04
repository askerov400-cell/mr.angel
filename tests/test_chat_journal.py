import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from memory import journal


def event(chat_type="private"):
    message = SimpleNamespace(message_id=7, text="/memory", reply_text=AsyncMock())
    return SimpleNamespace(message=message, effective_user=SimpleNamespace(id=12),
                           effective_chat=SimpleNamespace(id=12, type=chat_type))


class JournalTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_is_recorded_and_scoped(self):
        incoming = event()
        with patch.dict("os.environ", {"MEMORY_BACKEND": "supabase"}), \
                patch.object(journal, "_request", return_value=[]) as request:
            await journal.capture_incoming(incoming, None)
            record = request.call_args.kwargs["record"]
            self.assertEqual(record["telegram_user_id"], 12)
            self.assertEqual(record["content"], "/memory")
            self.assertEqual(record["role"], "user")

    async def test_group_is_not_recorded(self):
        with patch.dict("os.environ", {"MEMORY_BACKEND": "supabase"}), \
                patch.object(journal, "_request") as request:
            await journal.capture_incoming(event("group"), None)
            request.assert_not_called()

    async def test_sent_reply_is_recorded_only_after_send(self):
        incoming = event()
        sent = SimpleNamespace(message_id=8, text="Actual reply")
        incoming.message.reply_text.return_value = sent
        with patch.object(journal, "record", new=AsyncMock()) as record:
            await journal.send_reply(incoming, "Actual reply")
            record.assert_awaited_once_with(incoming, "assistant", sent)
            incoming.message.reply_text.assert_awaited_once_with("Actual reply")

    async def test_failed_send_is_not_recorded(self):
        incoming = event()
        incoming.message.reply_text.side_effect = RuntimeError
        with patch.object(journal, "record", new=AsyncMock()) as record:
            with self.assertRaises(RuntimeError):
                await journal.send_reply(incoming, "Reply")
            record.assert_not_awaited()

    async def test_journal_failure_does_not_raise(self):
        with patch.dict("os.environ", {"MEMORY_BACKEND": "supabase"}), \
                patch.object(journal, "_request", side_effect=TimeoutError):
            await journal.capture_incoming(event(), None)

    def test_credentials_are_masked(self):
        with patch.dict("os.environ", {"SUPABASE_SECRET_KEY": "synthetic-secret-value"}):
            self.assertNotIn("synthetic-secret-value", journal.redact("key synthetic-secret-value"))
        self.assertNotIn("sb_secret_", journal.redact("sb_secret_test_credential"))
