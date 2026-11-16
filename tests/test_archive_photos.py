import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from archive import photos


class LoadSaveTests(unittest.TestCase):
    def test_load_json_string(self):
        with patch.object(photos, "_request", return_value=[{"state_value": '[{"file_id":"A","caption":"стеллаж №3"}]'}]):
            self.assertEqual(photos._load(123), [{"file_id": "A", "caption": "стеллаж №3"}])

    def test_load_missing(self):
        with patch.object(photos, "_request", return_value=[]):
            self.assertEqual(photos._load(123), [])

    def test_load_invalid(self):
        with patch.object(photos, "_request", return_value=[{"state_value": "not json"}]):
            self.assertEqual(photos._load(123), [])

    def test_add_appends_and_caps(self):
        with patch.object(photos, "_load", return_value=[]), \
             patch.object(photos, "_save") as save:
            photos.add(123, "Рабочие фото", "file_1", "стеллаж №1")
        record = save.call_args.args[1][0]
        self.assertEqual(record["section"], "Рабочие фото")
        self.assertEqual(record["file_id"], "file_1")
        self.assertEqual(record["caption"], "стеллаж №1")
        self.assertIn("added_at", record)


class FindTests(unittest.TestCase):
    PHOTOS = [
        {"file_id": "1", "caption": "стеллаж №3 верхняя полка", "section": "Рабочие фото"},
        {"file_id": "2", "caption": "стеллаж №5 масло", "section": "Рабочие фото"},
        {"file_id": "3", "caption": "борщ рецепт", "section": "Рецепты еды"},
    ]

    def test_find_by_word(self):
        with patch.object(photos, "_load", return_value=self.PHOTOS):
            result = photos.find(123, "покажи фото стеллажа №3")
        self.assertEqual([p["file_id"] for p in result], ["1"])

    def test_find_by_plain_word_no_photo(self):
        with patch.object(photos, "_load", return_value=self.PHOTOS):
            result = photos.find(123, "стеллаж")
        self.assertEqual([p["file_id"] for p in result], ["1", "2"])

    def test_find_by_declension(self):
        with patch.object(photos, "_load", return_value=self.PHOTOS):
            result = photos.find(123, "фото масло")
        self.assertEqual([p["file_id"] for p in result], ["2"])

    def test_no_words_returns_recent(self):
        with patch.object(photos, "_load", return_value=self.PHOTOS):
            result = photos.find(123, "покажи фото")
        self.assertEqual(len(result), 3)

    def test_no_match_empty(self):
        with patch.object(photos, "_load", return_value=self.PHOTOS):
            result = photos.find(123, "фото сахар")
        self.assertEqual(result, [])

    def test_partial_match_falls_back(self):
        with patch.object(photos, "_load", return_value=self.PHOTOS):
            result = photos.find(123, "стеллаж борщ")
        # Точного совпадения нет; частично покрыты все три фото.
        self.assertEqual(len(result), 3)

    def test_is_request(self):
        self.assertTrue(photos.is_request("покажи фото стеллажа"))
        self.assertTrue(photos.is_request("СНИМОК"))
        self.assertFalse(photos.is_request("как дела"))


class MessageTests(unittest.IsolatedAsyncioTestCase):
    def update(self, caption="стеллаж", file_id="F"):
        photo = NS(file_id=file_id)
        message = NS(photo=[photo], caption=caption, reply_photo=AsyncMock())
        return NS(message=message, effective_user=NS(id=123))

    async def test_save_with_caption(self):
        update = self.update(caption="стеллаж №3")
        with patch.object(photos, "add") as add, \
             patch("memory.journal.send_reply", new=AsyncMock()):
            self.assertTrue(await photos.save_from_message(update, NS(user_data={}), "Рабочие фото"))
        add.assert_called_once()

    async def test_save_without_caption_waits(self):
        update = self.update(caption="")
        context = NS(user_data={})
        with patch.object(photos, "add") as add, \
             patch("memory.journal.send_reply", new=AsyncMock()):
            self.assertFalse(await photos.save_from_message(update, context, "Рабочие фото"))
        add.assert_not_called()
        self.assertEqual(context.user_data[photos.PENDING_PHOTO]["file_id"], "F")

    async def test_caption_saves_pending_photo(self):
        context = NS(user_data={photos.PENDING_PHOTO: {"section": "Рабочие фото", "file_id": "F"}})
        update = self.update(caption="")
        with patch.object(photos, "add") as add, \
             patch("memory.journal.send_reply", new=AsyncMock()):
            self.assertTrue(await photos.try_save_caption(update, context, "стеллаж №3"))
        add.assert_called_once_with(123, "Рабочие фото", "F", "стеллаж №3")
        self.assertNotIn(photos.PENDING_PHOTO, context.user_data)

    async def test_caption_no_pending_returns_false(self):
        update = self.update(caption="")
        with patch.object(photos, "add") as add:
            self.assertFalse(await photos.try_save_caption(update, NS(user_data={}), "стеллаж"))
        add.assert_not_called()

    async def test_try_find_sends_photos(self):
        update = self.update()
        with patch.object(photos, "find", return_value=[{"file_id": "F", "caption": "стеллаж"}]), \
             patch("memory.journal.send_reply", new=AsyncMock()):
            self.assertTrue(await photos.try_find(update, NS(), "стеллаж"))
        update.message.reply_photo.assert_awaited_once_with("F", caption="стеллаж")

    async def test_try_find_explicit_no_match_replies(self):
        update = self.update()
        with patch.object(photos, "find", return_value=[]), \
             patch("memory.journal.send_reply", new=AsyncMock()) as reply:
            self.assertTrue(await photos.try_find(update, NS(), "фото сахар"))
        update.message.reply_photo.assert_not_awaited()
        reply.assert_awaited_once()

    async def test_try_find_plain_no_match_returns_false(self):
        update = self.update()
        with patch.object(photos, "find", return_value=[]), \
             patch("memory.journal.send_reply", new=AsyncMock()) as reply:
            self.assertFalse(await photos.try_find(update, NS(), "сахар"))
        update.message.reply_photo.assert_not_awaited()
        reply.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
