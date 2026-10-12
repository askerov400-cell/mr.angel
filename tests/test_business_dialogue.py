import unittest
from types import SimpleNamespace as N
from unittest.mock import AsyncMock, patch
import bot

class DialogueTests(unittest.IsolatedAsyncioTestCase):
    async def test_owner_business_question_uses_snapshot_and_skips_personal_memory(self):
        bot.conversation_memory.clear()
        update=N(effective_user=N(id=123),effective_chat=N(id=123,type='private'),message=N(text='Как идут продажи?'))
        ctx=N(user_data={},bot=N(send_chat_action=AsyncMock()))
        reply=N(choices=[N(message=N(content='Synthetic business answer'))])
        with patch.dict('os.environ',{'X2POS_OWNER_ID':'123'}),patch.object(bot,'BACKEND','supabase'),patch.object(bot,'restore_dialogue',new=AsyncMock(return_value=[])),patch.object(bot.automatic_memory,'process',new=AsyncMock()) as personal,patch.object(bot.automatic_memory,'context',new=AsyncMock(return_value='personal')),patch.object(bot.business_dialogue,'context',new=AsyncMock(return_value='X2POS snapshot: total=100; last_success=TEST')) as data,patch.object(bot.deepseek.chat.completions,'create',new=AsyncMock(return_value=reply)) as model,patch.object(bot,'send_reply',new=AsyncMock()):
            await bot.handle_text(update,ctx,update.message.text)
            data.assert_awaited_once_with(123)
            personal.assert_not_awaited()
            messages=model.call_args.kwargs['messages']
            self.assertTrue(any('X2POS snapshot' in row['content'] for row in messages if row['role']=='system'))
            self.assertTrue(any('Не записывай их в личную память' in row['content'] for row in messages))

    async def test_clear_resets_business_topic(self):
        ctx=N(user_data={'business_until':99999999999})
        update=N(effective_user=N(id=123),effective_chat=N(id=123,type='private'),message=N())
        with patch.object(bot,'send_reply',new=AsyncMock()):
            await bot.clear_memory(update,ctx)
        self.assertNotIn('business_until',ctx.user_data)
