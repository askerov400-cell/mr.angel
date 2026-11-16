import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from archive import photos


class LoadSaveTests(unittest.TestCase):
    def test_load_json_string(self):
        with patch.object(photos, "_request", return_value=[{"state_value": '[{"storage_path":"p1","caption":"стеллаж №3"}]'}]):
            self.assertEqual(photos._load(123), [{"storage_path": "p1", "caption": "стеллаж №3"}])

    def test_load_missing(self):
        with patch.object(photos, "_request", return_value=[]):
            self.assertEqual(photos._load(123), [])

    def test_load_invalid(self):
        with patch.object(photos, "_request", return_value=[{"state_value": "not json"}]):
            self.assertEqual(photos._load(123), [])

    def test_add_appends(self):
        with patch.object(photos, "_load", return_value=[]), \
             patch.object(photos, "_save") as save:
            photos.add(123, "Рабочие фото", "owner/abc.jpg", "стеллаж №1")
        record = save.call_args.args[1][0]
        self.assertEqual(record["section"], "Рабочие фото")
        self.assertEqual(record["storage_path"], "owner/abc.jpg")
        self.assertEqual(record["caption"], "стеллаж №1")
        self.assertIn("added_at", record)
        self.assertNotIn("file_id", record)


class StorageTests(unittest.TestCase):
    def test_storage_put_returns_path(self):
        env = {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SECRET_KEY": "k"}
        with patch.dict("os.environ", env, clear=False), \
             patch.object(photos, "urlopen") as urlopen:
            resp = urlopen.return_value.__enter__.return_value
            resp.read.return_value = b""
            path = photos.storage_put(123, b"data")
        self.assertTrue(path.startswith("123/"))
        self.assertTrue(path.endswith(".jpg"))
        self.assertIn("storage/v1/object/archive-media/123/", urlopen.call_args.args[0].full_url)

    def test_storage_get_returns_bytes(self):
        env = {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SECRET_KEY": "k"}
        with patch.dict("os.environ", env, clear=False), \
             patch.object(photos, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b"jpg"
            self.assertEqual(photos.storage_get("123/a.jpg"), b"jpg")


class FindTests(unittest.TestCase):
    PHOTOS = [
        {"storage_path": "1", "caption": "стеллаж №3 верхняя полка", "section": "Рабочие фото"},
        {"storage_path": "2", "caption": "стеллаж №5 масло", "section": "Рабочие фото"},
        {"storage_path": "3", "caption": "борщ рецепт", "section": "Рецепты еды"},
    ]

    def test_find_by_word(self):
        with patch.object(photos, "_load", return_value=self.PHOTOS):
            result = photos.find(123, "покажи фото стеллажа №3")
        self.assertEqual([p["storage_path"] for p in result], ["1"])

    def test_find_by_plain_word_no_photo(self):
        with patch.object(photos, "_load", return_value=self.PHOTOS):
            result = photos.find(123, "стеллаж")
        self.assertEqual([p["storage_path"] for p in result], ["1", "2"])

    def test_partial_match_falls_back(self):
        with patch.object(photos, "_load", return_value=self.PHOTOS):
            result = photos.find(123, "стеллаж борщ")
        self.assertEqual(len(result), 3)

    def test_is_request(self):
        self.assertTrue(photos.is_request("покажи фото стеллажа"))
        self.assertFalse(photos.is_request("как дела"))


class MessageTests(unittest.IsolatedAsyncioTestCase):
    def update(self, caption="стеллаж", file_id="F"):
        photo = NS(file_id=file_id, get_file=AsyncMock())
        message = NS(photo=[photo], caption=caption, reply_photo=AsyncMock())
        return NS(message=message, effective_user=NS(id=123))

    async def test_save_with_caption_uploads_to_storage(self):
        update = self.update(caption="стеллаж №3")
        remote = NS(download_as_bytearray=AsyncMock(return_value=b"jpg"))
        update.message.photo[-1].get_file.return_value = remote
        with patch.object(photos, "storage_put", return_value="123/a.jpg") as put, \
             patch.object(photos, "add") as add, \
             patch("memory.journal.send_reply", new=AsyncMock()):
            self.assertTrue(await photos.save_from_message(update, NS(user_data={}), "Рабочие фото"))
        put.assert_called_once()
        add.assert_called_once_with(123, "Рабочие фото", "123/a.jpg", "стеллаж №3")

    async def test_save_without_caption_waits(self):
        update = self.update(caption="")
        context = NS(user_data={})
        with patch.object(photos, "add") as add, \
             patch("memory.journal.send_reply", new=AsyncMock()):
            self.assertFalse(await photos.save_from_message(update, context, "Рабочие фото"))
        add.assert_not_called()
        self.assertEqual(context.user_data[photos.PENDING_PHOTO]["file_id"], "F")

    async def test_caption_saves_pending_photo(self):
        context = NS(user_data={photos.PENDING_PHOTO: {"section": "Рабочие фото", "file_id": "F"}},
                     bot=NS(get_file=AsyncMock()))
        remote = NS(download_as_bytearray=AsyncMock(return_value=b"jpg"))
        context.bot.get_file.return_value = remote
        update = self.update(caption="")
        with patch.object(photos, "storage_put", return_value="123/b.jpg"), \
             patch.object(photos, "add") as add, \
             patch("memory.journal.send_reply", new=AsyncMock()):
            self.assertTrue(await photos.try_save_caption(update, context, "стеллаж №3"))
        add.assert_called_once_with(123, "Рабочие фото", "123/b.jpg", "стеллаж №3")
        self.assertNotIn(photos.PENDING_PHOTO, context.user_data)

    async def test_try_find_sends_from_storage(self):
        update = self.update()
        with patch.object(photos, "find", return_value=[{"storage_path": "123/a.jpg", "caption": "стеллаж"}]), \
             patch.object(photos, "storage_get", return_value=b"jpg") as get, \
             patch("memory.journal.send_reply", new=AsyncMock()):
            self.assertTrue(await photos.try_find(update, NS(), "стеллаж"))
        get.assert_called_once_with("123/a.jpg")
        update.message.reply_photo.assert_awaited_once()

    async def test_try_find_falls_back_to_file_id(self):
        update = self.update()
        with patch.object(photos, "find", return_value=[{"file_id": "F", "caption": "старое"}]), \
             patch("memory.journal.send_reply", new=AsyncMock()):
            self.assertTrue(await photos.try_find(update, NS(), "старое"))
        update.message.reply_photo.assert_awaited_once_with("F", caption="старое")


if __name__ == "__main__":
    unittest.main()
