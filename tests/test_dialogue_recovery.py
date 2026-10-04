import unittest
from types import SimpleNamespace
from unittest.mock import patch
from memory.journal import dialogue_from_rows, restore_dialogue


def row(mid, role, text):
    return {"telegram_message_id": mid, "role": role, "content": text,
            "telegram_user_id": 12, "chat_id": 12}


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    def test_current_message_is_not_duplicated(self):
        result = dialogue_from_rows([row(3,"user","new"),row(2,"assistant","answer"),row(1,"user","old")],3)
        self.assertEqual([r["content"] for r in result], ["old","answer"])

    def test_clear_is_barrier_and_command_responses_are_skipped(self):
        rows = [row(8,"user","new"),row(7,"assistant","part2"),row(6,"assistant","part1"),
                row(5,"user","/memory"),row(4,"user","after clear"),row(3,"assistant","Память текущего диалога очищена.\nДолговременная память сохранена."),
                row(2,"user","/clear"),row(1,"user","before clear")]
        self.assertEqual(dialogue_from_rows(rows,8),[{"role":"user","content":"after clear"}])

    def test_unexecuted_clear_does_not_erase_previous_dialogue(self):
        rows = [row(3,"user","new"),row(2,"user","/clear@another_bot"),row(1,"user","old")]
        self.assertEqual(dialogue_from_rows(rows,3),[{"role":"user","content":"old"}])

    async def test_foreign_owner_is_rejected(self):
        update=SimpleNamespace(message=SimpleNamespace(message_id=3),effective_user=SimpleNamespace(id=12),
                               effective_chat=SimpleNamespace(id=12,type="private"))
        foreign=row(1,"user","private");foreign["telegram_user_id"]=13
        with patch("memory.journal._request",return_value=[foreign]):
            self.assertEqual(await restore_dialogue(update),[])

    async def test_read_failure_is_safe(self):
        update=SimpleNamespace(message=SimpleNamespace(message_id=3),effective_user=SimpleNamespace(id=12),
                               effective_chat=SimpleNamespace(id=12,type="private"))
        with patch("memory.journal._request",side_effect=TimeoutError):
            self.assertEqual(await restore_dialogue(update),[])
