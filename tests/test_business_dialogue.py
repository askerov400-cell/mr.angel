import unittest
from types import SimpleNamespace as N
from unittest.mock import AsyncMock, patch
import bot
from datetime import date,datetime
from decimal import Decimal
from x2pos import analytics,dialogue,reports,expenses

class DialogueTests(unittest.IsolatedAsyncioTestCase):
    async def test_screenshot_request_uses_complete_month_even_after_old_refusal(self):
        days={date(2026,9,i).isoformat():{**reports.empty_day(),**expenses.empty_day(),
            'total':Decimal(100),'sales_total':Decimal(100),'sales_count':1,
            'cost_fifo':Decimal(50),'cost_average':Decimal(55),'expenses_total':Decimal(10),
            'expenses_count':1,'expense_categories':{'2':Decimal(10)}} for i in range(1,31)}
        update=N(effective_user=N(id=123),effective_chat=N(id=123,type='private'),message=N(reply_text=AsyncMock()))
        ctx=N(user_data={},bot=N(send_chat_action=AsyncMock()))
        old=[{'role':'user','content':'Прибыль за сентябрь?'},{'role':'assistant','content':'Нет полного сентября. Пришли выгрузку.'}]
        bot.conversation_memory[(123,123)]=old.copy()
        stamp=datetime.now(analytics.ZONE).isoformat()
        with patch.dict('os.environ',{'X2POS_OWNER_ID':'123','X2POS_LLM_ENABLED':'1','X2POS_EXPENSES_COMPLETE':'1'}),patch.object(bot,'BACKEND','supabase'),patch.object(dialogue.store,'identity',return_value=(123,'7')),patch.object(expenses,'report',return_value={'daily':days}),patch.object(bot.deepseek.chat.completions,'create',new=AsyncMock()) as model,patch.object(bot.automatic_memory,'process',new=AsyncMock()) as memory:
            await bot.handle_text(update,ctx,'Покажи расходы и чистую прибыль за сентябрь')
        model.assert_not_awaited();memory.assert_not_awaited()
        text=update.message.reply_text.call_args.args[0]
        self.assertIn('01.09.2026 — 30.09.2026',text)
        self.assertIn('300,00',text)
        self.assertIn('1 200,00',text)
        self.assertIn('1 050,00',text)
        self.assertNotIn('выгрузку',text)
        self.assertEqual(bot.conversation_memory[(123,123)],old)

    def test_report_routing_keeps_analysis_with_model(self):
        self.assertTrue(dialogue.report_requested('Покажи расходы и чистую прибыль за сентябрь'))
        self.assertTrue(dialogue.report_requested('Продажи за сегодня'))
        self.assertFalse(dialogue.report_requested('Почему продажи упали за сентябрь?'))
        self.assertFalse(dialogue.report_requested('Сравни прибыль за сентябрь и август'))
        self.assertFalse(dialogue.report_requested('Как идут продажи?'))

    def test_month_coverage_marks_missing_day_and_ready_totals(self):
        days={date(2026,9,i).isoformat():reports.empty_day() for i in range(1,31)}
        now=datetime(2026,10,12,tzinfo=analytics.ZONE)
        state={'last_success':now.isoformat()}
        self.assertIn('Месяц 2026-09: 30/30 дней; ПОЛНЫЙ МЕСЯЦ.',analytics.context_text(state,days,[],now))
        del days['2026-09-03']
        self.assertIn('Месяц 2026-09: 29/30 дней; НЕПОЛНЫЙ МЕСЯЦ',analytics.context_text(state,days,[],now))

    async def test_owner_business_question_uses_snapshot_and_skips_personal_memory(self):
        bot.conversation_memory.clear()
        update=N(effective_user=N(id=123),effective_chat=N(id=123,type='private'),message=N(text='Как идут продажи?'))
        ctx=N(user_data={},bot=N(send_chat_action=AsyncMock()))
        reply=N(choices=[N(message=N(content='Synthetic business answer'))])
        with patch.dict('os.environ',{'X2POS_OWNER_ID':'123','X2POS_LLM_ENABLED':'1'}),patch.object(bot,'BACKEND','supabase'),patch.object(bot,'restore_dialogue',new=AsyncMock(return_value=[])),patch.object(bot.automatic_memory,'process',new=AsyncMock()) as personal,patch.object(bot.automatic_memory,'context',new=AsyncMock(return_value='personal')),patch.object(bot.business_dialogue,'context',new=AsyncMock(return_value='X2POS snapshot: total=100; last_success=TEST')) as data,patch.object(bot.deepseek.chat.completions,'create',new=AsyncMock(return_value=reply)) as model,patch.object(bot,'send_reply',new=AsyncMock()):
            await bot.handle_text(update,ctx,update.message.text)
            data.assert_awaited_once_with(123,'')
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


    async def test_no_consent_direct_answer_never_calls_external_model(self):
        bot.conversation_memory.clear()
        update=N(effective_user=N(id=123),effective_chat=N(id=123,type='private'),message=N(reply_text=AsyncMock()))
        ctx=N(user_data={},bot=N(send_chat_action=AsyncMock()))
        with patch.dict('os.environ',{'X2POS_OWNER_ID':'123','X2POS_LLM_ENABLED':'0'}),patch.object(bot,'BACKEND','supabase'),patch.object(bot,'restore_dialogue',new=AsyncMock(return_value=[])),patch.object(bot.business_dialogue,'direct_answer',new=AsyncMock(return_value='Synthetic local aggregate')),patch.object(bot.automatic_memory,'process',new=AsyncMock()) as memory,patch.object(bot.deepseek.chat.completions,'create',new=AsyncMock()) as model:
            await bot.handle_text(update,ctx,'Продажи за сегодня')
            model.assert_not_awaited()
            memory.assert_not_awaited()
            update.message.reply_text.assert_awaited_once_with('Synthetic local aggregate')
            self.assertEqual(bot.conversation_memory[(123,123)],[])
