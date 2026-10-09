import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch
from interface import menu
from memory.journal import dialogue_from_rows

def incoming(text='',owner=12,chat=12,kind='private'):
 return NS(message=NS(text=text),effective_user=NS(id=owner),effective_chat=NS(id=chat,type=kind))

class InterfaceTests(unittest.IsolatedAsyncioTestCase):
 def context(self):return NS(user_data={},args=[])
 async def test_buttons_bypass_dialogue(self):
  handlers={'memory':AsyncMock(),'remember':AsyncMock()};context=self.context()
  with patch.object(menu,'send_reply',new=AsyncMock()):
   self.assertTrue(await menu.text(incoming(menu.MEMORY),context,handlers))
   self.assertTrue(await menu.text(incoming(menu.SAVE),context,handlers))
   self.assertTrue(await menu.text(incoming('Synthetic fact'),context,handlers))
  handlers['memory'].assert_awaited_once();handlers['remember'].assert_awaited_once()
  self.assertNotIn('interface_input',context.user_data)
 async def test_cancel_does_not_save_next_message(self):
  handlers={'memory':AsyncMock(),'remember':AsyncMock()};context=self.context()
  with patch.object(menu,'send_reply',new=AsyncMock()):
   await menu.text(incoming(menu.SAVE),context,handlers);await menu.cancel(incoming(),context)
   self.assertFalse(await menu.text(incoming('hello'),context,handlers))
  handlers['remember'].assert_not_awaited()
 async def test_group_cannot_use_memory_buttons(self):
  handlers={'memory':AsyncMock(),'remember':AsyncMock()}
  self.assertFalse(await menu.text(incoming(menu.MEMORY,chat=-100,kind='group'),self.context(),handlers))
  handlers['memory'].assert_not_awaited()
 async def test_clear_confirmation_is_owner_scoped_and_single_use(self):
  context=self.context();context.user_data['interface_clear']='safe-test';clear=AsyncMock()
  request=incoming();request.callback_query=NS(answer=AsyncMock(),data='guardian:clear:safe-test',message=NS())
  with patch.object(menu,'send_reply',new=AsyncMock()) as reply:
   await menu.callback(request,self.context(),clear);clear.assert_not_awaited()
   self.assertIs(reply.await_args.args[0].message,request.callback_query.message)
   self.assertTrue(reply.await_args.args[1].startswith('Подтверждение уже не действует.'))
   await menu.callback(request,context,clear);await menu.callback(request,context,clear)
  clear.assert_awaited_once()
 def test_menu_not_restored_as_chat_context(self):
  rows=[dict(role='assistant',content='Хранитель\nMenu',telegram_message_id=2),dict(role='user',content=menu.CHAT,telegram_message_id=1)]
  self.assertEqual(dialogue_from_rows(rows,99),[])
