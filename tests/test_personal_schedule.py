import asyncio
import json
import os
import unittest
from datetime import datetime
from types import SimpleNamespace as N
from unittest.mock import AsyncMock, patch

import personal_schedule as ps

ENV = {'X2POS_OWNER_ID': '123'}


class StoreTests(unittest.TestCase):
    def test_load_returns_text_from_dict(self):
        with patch.dict(os.environ, ENV), \
             patch.object(ps, '_request', return_value=[{'state_value': {'text': 'Пн: работа'}}]):
            self.assertEqual(ps.load(123), 'Пн: работа')

    def test_load_parses_json_string(self):
        with patch.object(ps, '_request', return_value=[{'state_value': json.dumps({'text': 'Вт: спорт'})}]):
            self.assertEqual(ps.load(123), 'Вт: спорт')

    def test_missing_state_gives_empty(self):
        with patch.object(ps, '_request', return_value=[]):
            self.assertEqual(ps.load(123), '')

    def test_save_limits_and_wraps(self):
        with patch.object(ps, '_request') as request:
            saved = ps.save(123, 'x' * 5000)
        self.assertEqual(len(saved), ps.LIMIT)
        record = request.call_args.kwargs['record']
        self.assertEqual(record['p_key'], ps.KEY)
        self.assertEqual(json.loads(record['p_value'])['text'], 'x' * ps.LIMIT)

    def test_context_mentions_today_and_text(self):
        moment = datetime(2026, 10, 26, 8, 0, tzinfo=ps.ZONE)
        with patch.object(ps, 'load', return_value='Пн: планёрка в 10'):
            text = ps.context_text(123, moment)
        self.assertIn('Сегодня понедельник', text)
        self.assertIn('Пн: планёрка', text)

    def test_context_empty_when_no_schedule(self):
        with patch.object(ps, 'load', return_value=''):
            self.assertEqual(ps.context_text(123), '')


class HandlerTests(unittest.TestCase):
    def test_non_owner_is_rejected(self):
        message = N(reply_text=AsyncMock())
        update = N(effective_user=N(id=999), effective_chat=N(type='private'), message=message)
        with patch.dict(os.environ, ENV):
            asyncio.run(ps.panel(update, N(user_data={})))
        self.assertIn('только владельцу', message.reply_text.call_args.args[0])

    def test_owner_sees_schedule(self):
        message = N(reply_text=AsyncMock())
        update = N(effective_user=N(id=123), effective_chat=N(type='private'), message=message)
        with patch.dict(os.environ, ENV), patch.object(ps, 'load', return_value='Пн: планёрка'):
            asyncio.run(ps.panel(update, N(user_data={})))
        self.assertIn('Пн: планёрка', message.reply_text.call_args.args[0])

    def test_accept_ignores_regular_text(self):
        context = N(user_data={})
        update = N(effective_user=N(id=123), message=N(reply_text=AsyncMock()))
        self.assertFalse(asyncio.run(ps.accept(update, context, 'просто вопрос')))

    def test_accept_saves_and_clears_flag(self):
        context = N(user_data={'schedule_edit': True})
        update = N(effective_user=N(id=123), message=N(reply_text=AsyncMock()))
        with patch.object(ps, 'save', return_value='Пн: бег') as save:
            self.assertTrue(asyncio.run(ps.accept(update, context, 'Пн: бег')))
        save.assert_called_once_with(123, 'Пн: бег')
        self.assertNotIn('schedule_edit', context.user_data)
        self.assertIn('сохранён', update.message.reply_text.call_args.args[0])

    def test_accept_rejects_too_short_text(self):
        context = N(user_data={'schedule_edit': True})
        update = N(effective_user=N(id=123), message=N(reply_text=AsyncMock()))
        self.assertTrue(asyncio.run(ps.accept(update, context, 'ок')))
        self.assertNotIn('schedule_edit', context.user_data)
        self.assertIn('Слишком коротко', update.message.reply_text.call_args.args[0])
