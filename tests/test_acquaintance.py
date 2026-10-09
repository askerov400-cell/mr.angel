import asyncio
import os
import random
import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from acquaintance import schedule, handlers, store, questions
from acquaintance.worker import Scheduler
from storage.supabase_store import StorageError
from interface import menu

QID='11111111-1111-4111-8111-111111111111'

def incoming(reply=True,owner=12,kind='private'):
    original=NS(message_id=90,from_user=NS(id=99)) if reply else None
    return NS(message=NS(text='Synthetic answer',reply_to_message=original,reply_text=AsyncMock()),
              effective_user=NS(id=owner),effective_chat=NS(id=owner if kind=='private' else -100,type=kind))

class ScheduleTests(unittest.TestCase):
    def test_slots_are_spread_and_random(self):
        first=schedule.slots(date(2026,10,9),random.Random(1))
        second=schedule.slots(date(2026,10,9),random.Random(2))
        self.assertEqual(len(first),10);self.assertNotEqual(first,second)
        times=[datetime.fromisoformat(x['at']) for x in first]
        self.assertTrue(all(schedule.in_window(x) for x in times))
        self.assertTrue(all(b-a>=timedelta(minutes=20) for a,b in zip(times,times[1:])))
    def test_window_uses_owner_timezone_and_exclusive_end(self):
        self.assertFalse(schedule.in_window(datetime(2026,10,9,4,59,tzinfo=timezone.utc)))
        self.assertTrue(schedule.in_window(datetime(2026,10,9,5,tzinfo=timezone.utc)))
        self.assertFalse(schedule.in_window(datetime(2026,10,9,18,tzinfo=timezone.utc)))

class AnswerTests(unittest.IsolatedAsyncioTestCase):
    def context(self):return NS(bot=NS(id=99))
    async def test_ordinary_chat_does_not_call_question_store(self):
        with patch.dict(os.environ,{'MEMORY_BACKEND':'supabase'}),patch.object(store,'action',new=AsyncMock()) as call:
            self.assertFalse(await handlers.answer(incoming(False),self.context()))
            self.assertFalse(await handlers.answer(incoming(kind='group'),self.context()))
            call.assert_not_awaited()
    async def test_linked_answer_saved_before_confirmation(self):
        calls=[]
        async def action(owner,name,qid=None,**data):
            calls.append((owner,name,qid,data))
            return [{'id':QID,'status':'sent'}] if name=='by_message' else [{'saved':True}]
        with patch.dict(os.environ,{'MEMORY_BACKEND':'supabase'}),patch.object(store,'action',new=action),patch.object(handlers,'send_reply',new=AsyncMock()) as reply:
            self.assertTrue(await handlers.answer(incoming(),self.context()))
            self.assertEqual(calls[1],(12,'answer',QID,{'text':'Synthetic answer'}))
            self.assertIn('сохранён',reply.await_args.args[1])
    async def test_failure_never_claims_answer_saved(self):
        with patch.dict(os.environ,{'MEMORY_BACKEND':'supabase'}),patch.object(store,'action',new=AsyncMock(side_effect=StorageError('safe'))),patch.object(handlers,'send_reply',new=AsyncMock()) as reply:
            self.assertTrue(await handlers.answer(incoming(),self.context()))
            self.assertIn('Не удалось подтвердить',reply.await_args.args[1])
    async def test_stale_answer_not_overwritten(self):
        with patch.dict(os.environ,{'MEMORY_BACKEND':'supabase'}),patch.object(store,'action',new=AsyncMock(return_value=[{'id':QID,'status':'answered'}])) as call,patch.object(handlers,'send_reply',new=AsyncMock()):
            self.assertTrue(await handlers.answer(incoming(),self.context()))
            call.assert_awaited_once_with(12,'by_message',message_id=90)
    async def test_other_owner_response_rejected(self):
        with patch.object(store,'_request',return_value=[{'telegram_user_id':13}]):
            with self.assertRaises(StorageError):await store.action(12,'status')
    async def test_group_menu_responds_without_private_memory(self):
        with patch.object(menu,'send_reply',new=AsyncMock()) as reply:
            await menu.home(incoming(kind='group'),NS(user_data={}))
            reply.assert_awaited_once()

class WorkerTests(unittest.IsolatedAsyncioTestCase):
    def worker(self):return Scheduler(NS(send_message=AsyncMock(return_value=NS(message_id=90))),NS())
    async def test_restart_reuses_existing_plan(self):
        first=self.worker();second=self.worker()
        with patch.object(store,'action',new=AsyncMock(return_value=[{'planned':True}])) as call:
            await first.ensure_plan(12);await first.ensure_plan(12);await second.ensure_plan(12)
            self.assertEqual(call.await_count,4)
    async def test_closed_window_does_not_claim_or_send(self):
        worker=self.worker()
        with patch.object(schedule,'in_window',return_value=False),patch.object(store,'action',new=AsyncMock()) as call:
            self.assertIsNone(await worker.deliver(12));call.assert_not_awaited();worker.bot.send_message.assert_not_awaited()
    async def test_unknown_delivery_never_retries(self):
        worker=self.worker();worker.bot.send_message.side_effect=TimeoutError()
        async def action(owner,name,qid=None,**data):
            if name=='test':return [{'id':QID}]
            if name=='prepare':return [{'id':QID,'question_text':'Synthetic question?'}]
            return [{'planned':True}]
        with patch.object(store,'action',new=AsyncMock(side_effect=action)) as call,patch.object(questions,'generate',new=AsyncMock(return_value='Synthetic question?')):
            await worker.deliver(12,manual=True)
            self.assertEqual(worker.bot.send_message.await_count,1)
            self.assertNotIn('sent',[x.args[1] for x in call.await_args_list])
            self.assertNotIn('skip',[x.args[1] for x in call.await_args_list])
    async def test_memory_failure_suppresses_question(self):
        worker=self.worker()
        async def action(owner,name,qid=None,**data):return [{'id':QID}] if name=='test' else [{'planned':True}]
        with patch.object(store,'action',new=AsyncMock(side_effect=action)) as call,patch.object(questions,'generate',new=AsyncMock(side_effect=RuntimeError('safe'))):
            await worker.deliver(12,manual=True)
            worker.bot.send_message.assert_not_awaited()
            self.assertIn('skip',[x.args[1] for x in call.await_args_list])
    async def test_pause_winning_prepare_prevents_delivery(self):
        worker=self.worker()
        async def action(owner,name,qid=None,**data):
            if name=='test':return [{'id':QID}]
            return [] if name=='prepare' else [{'planned':True}]
        with patch.object(store,'action',new=AsyncMock(side_effect=action)),patch.object(questions,'generate',new=AsyncMock(return_value='Synthetic question?')):
            await worker.deliver(12,manual=True);worker.bot.send_message.assert_not_awaited()

class CallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_foreign_question_cannot_be_answered_or_skipped(self):
        request=incoming();request.callback_query=NS(answer=AsyncMock(),data='aq:skip:'+QID,message=request.message)
        worker=Scheduler(NS(),NS())
        context=NS(application=NS(bot_data={'acquaintance_worker':worker}))
        with patch.dict(os.environ,{'MEMORY_BACKEND':'supabase'}),patch.object(store,'action',new=AsyncMock(return_value=[])) as call,patch.object(handlers,'send_reply',new=AsyncMock()):
            await handlers.callback(request,context)
            call.assert_awaited_once_with(12,'get',QID)
    async def test_answer_prompt_binding_persists_before_later_reply(self):
        request=incoming();request.callback_query=NS(answer=AsyncMock(),data='aq:answer:'+QID,message=request.message)
        context=NS(application=NS(bot_data={'acquaintance_worker':Scheduler(NS(),NS())}))
        with patch.dict(os.environ,{'MEMORY_BACKEND':'supabase'}),patch.object(store,'action',new=AsyncMock(return_value=[{'id':QID,'status':'sent','question_text':'Synthetic question?'}])) as call,patch.object(handlers,'send_reply',new=AsyncMock(return_value=NS(message_id=91))):
            await handlers.callback(request,context)
            self.assertEqual(call.await_args.args,(12,'prompt',QID))
            self.assertEqual(call.await_args.kwargs,{'message_id':91})
    async def test_repeated_test_does_not_resend_pending_question(self):
        worker=Scheduler(NS(send_message=AsyncMock()),NS())
        with patch.object(worker,'ensure_plan',new=AsyncMock()),patch.object(store,'action',new=AsyncMock(return_value=[])),patch.object(questions,'generate',new=AsyncMock()) as generate:
            await worker.deliver(12,manual=True);worker.bot.send_message.assert_not_awaited();generate.assert_not_awaited()
