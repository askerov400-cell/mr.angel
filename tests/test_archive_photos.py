import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from archive import photos


def state(rows):
    return rows


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

    def test_mark_sent_record_shape(self):
        with patch.object(photos, "_load", return_value=[]), \
             patch.object(photos, "_save") as save:
            photos.add(1, "Рецепты еды", "f", "борщ")
        with patch.object(photos, "_request") as req:
            photos._save(1, [{"a": 1}])
        record = req.call_args.kwargs["record"]
        self.assertEqual(record["p_key"], photos.KEY)
        self.assertEqual(record["p_confidence"], 1.0)


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

    def test_is_request(self):
        self.assertTrue(photos.is_request("покажи фото стеллажа"))
        self.assertTrue(photos.is_request("СНИМОК"))
        self.assertFalse(photos.is_request("как дела"))


class MessageTests(unittest.IsolatedAsyncioTestCase):
    def update(self, caption="стеллаж", file_id="F"):
        photo = NS(file_id=file_id)
        message = NS(photo=[photo], caption=caption, reply_photo=AsyncMock())
        return NS(message=message, effective_user=NS(id=123))

    async def test_save_requires_caption(self):
        update = self.update(caption="")
        with patch.object(photos, "add") as add, \
             patch.object(photos, "send_reply", new=AsyncMock()) if hasattr(photos, "send_reply") else patch("memory.journal.send_reply", new=AsyncMock()):
            self.assertFalse(await photos.save_from_message(update, NS(), "Рабочие фото"))
        add.assert_not_called()

    async def test_save_with_caption(self):
        update = self.update(caption="стеллаж №3")
        with patch.object(photos, "add") as add, \
             patch("memory.journal.send_reply", new=AsyncMock()):
            self.assertTrue(await photos.save_from_message(update, NS(), "Рабочие фото"))
        add.assert_called_once()

    async def test_send_matches_sends_photos(self):
        update = self.update()
        with patch.object(photos, "find", return_value=[{"file_id": "F", "caption": "стеллаж"}]), \
             patch("memory.journal.send_reply", new=AsyncMock()):
            self.assertTrue(await photos.send_matches(update, NS(), "фото стеллаж"))
        update.message.reply_photo.assert_awaited_once_with("F", caption="стеллаж")

    async def test_send_no_match_replies(self):
        update = self.update()
        with patch.object(photos, "find", return_value=[]), \
             patch("memory.journal.send_reply", new=AsyncMock()) as reply:
            self.assertTrue(await photos.send_matches(update, NS(), "фото сахар"))
        update.message.reply_photo.assert_not_awaited()
        reply.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
