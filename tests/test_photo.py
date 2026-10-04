import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from vision import handler


class PhotoTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.remote = NS(file_size=3, download_as_bytearray=AsyncMock(return_value=b"jpg"))
        self.photo = NS(file_size=3, get_file=AsyncMock(return_value=self.remote))
        self.update = NS(message=NS(photo=[self.photo], caption="Что это?"),
                         effective_user=NS(id=1), effective_chat=NS(id=1, type="private"))
        self.history = {}

    async def run_photo(self, answer="Это чашка.", key="test-key", error=None):
        with patch.dict("os.environ", {"GROQ_API_KEY": key}), \
             patch.object(handler, "describe", AsyncMock(return_value=answer, side_effect=error)) as model, \
             patch.object(handler, "record", AsyncMock()) as record, \
             patch.object(handler, "send_reply", AsyncMock()) as reply:
            await handler.handle_photo(self.update, NS(), self.history)
            return model, record, reply

    async def test_success(self):
        model, record, reply = await self.run_photo()
        self.assertEqual(model.call_args.args[:2], (b"jpg", "Что это?"))
        self.assertEqual(record.call_args.kwargs["text"], "[Фото] Что это?")
        self.assertEqual(self.history[(1, 1)][-1]["content"], "Это чашка.")
        reply.assert_awaited_once_with(self.update, "Это чашка.")

    async def test_group(self):
        self.update.effective_chat.type = "group"
        model, record, reply = await self.run_photo()
        model.assert_not_awaited()
        record.assert_not_awaited()
        self.photo.get_file.assert_not_awaited()

    async def test_no_key(self):
        await self.run_photo(key="")
        self.photo.get_file.assert_not_awaited()

    async def test_size(self):
        self.photo.file_size = handler.MAX_BYTES + 1
        await self.run_photo()
        self.photo.get_file.assert_not_awaited()

    async def test_error(self):
        await self.run_photo(error=TimeoutError())
        self.assertEqual(self.history, {})

    async def test_empty(self):
        await self.run_photo(answer="")
        self.assertEqual(self.history, {})

    async def test_provider_request(self):
        result = NS(choices=[NS(message=NS(content="cup"))])
        client = NS(chat=NS(completions=NS(create=AsyncMock(return_value=result))))
        with patch.object(handler, "AsyncOpenAI") as factory:
            factory.return_value.__aenter__ = AsyncMock(return_value=client)
            factory.return_value.__aexit__ = AsyncMock(return_value=None)
            self.assertEqual(await handler.describe(b"jpg", "question", "key"), "cup")
        args = client.chat.completions.create.call_args.kwargs
        self.assertEqual(args["model"], "qwen/qwen3.8-27b")
        self.assertTrue(args["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
