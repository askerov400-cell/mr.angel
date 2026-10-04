import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from speech import handler


class AudioTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.remote = NS(file_size=100, download_to_drive=AsyncMock(side_effect=self.download))
        self.audio = NS(duration=10, file_size=100, get_file=AsyncMock(return_value=self.remote))
        self.update = NS(message=NS(voice=self.audio, audio=None),
                         effective_user=NS(id=1), effective_chat=NS(id=1, type="private"))
        self.respond = AsyncMock()
        self.path = None

    async def download(self, custom_path):
        self.path = custom_path
        custom_path.write_bytes(b"test audio")

    async def run_audio(self, transcript="hello", error=None, key="test-key"):
        with patch.dict("os.environ", {"GROQ_API_KEY": key}), \
             patch.object(handler, "transcribe", AsyncMock(return_value=transcript, side_effect=error)) as stt, \
             patch.object(handler, "record", AsyncMock()) as record, \
             patch.object(handler, "send_reply", AsyncMock()) as reply:
            await handler.handle_audio(self.update, NS(), self.respond)
            return stt, record, reply

    async def test_voice_transcript_and_cleanup(self):
        stt, record, reply = await self.run_audio()
        self.respond.assert_awaited_once()
        self.assertEqual(self.respond.call_args.args[2], "hello")
        self.assertEqual(record.call_args.kwargs["text"], "hello")
        self.assertFalse(self.path.exists())
        reply.assert_not_awaited()

    async def test_audio_file(self):
        self.audio.file_name = "music.MP3"
        self.update.message.voice = None
        self.update.message.audio = self.audio
        await self.run_audio()
        self.assertEqual(self.path.suffix, ".mp3")
        self.respond.assert_awaited_once()

    async def test_group_never_downloads(self):
        self.update.effective_chat.type = "group"
        await self.run_audio()
        self.audio.get_file.assert_not_awaited()
        self.respond.assert_not_awaited()

    async def test_missing_key(self):
        await self.run_audio(key="")
        self.audio.get_file.assert_not_awaited()

    async def test_oversize(self):
        self.audio.file_size = handler.MAX_BYTES + 1
        await self.run_audio()
        self.audio.get_file.assert_not_awaited()

    async def test_long_audio(self):
        self.audio.duration = 301
        await self.run_audio()
        self.audio.get_file.assert_not_awaited()

    async def test_timeout_cleanup_no_memory(self):
        stt, record, reply = await self.run_audio(error=TimeoutError())
        self.assertFalse(self.path.exists())
        record.assert_not_awaited()
        self.respond.assert_not_awaited()
        reply.assert_awaited_once()

    async def test_empty_does_not_enter_dialogue(self):
        stt, record, reply = await self.run_audio(transcript="")
        record.assert_not_awaited()
        self.respond.assert_not_awaited()
        self.assertFalse(self.path.exists())
