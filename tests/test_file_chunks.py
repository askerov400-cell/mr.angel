import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from attachments import analysis, extract


class ChunkTests(unittest.TestCase):
    def test_chunking_preserves_all_text_and_line_boundaries(self):
        text = ('строка документа 17\n'*15000)+'LAST MARKER'
        parts = analysis.chunks(text)
        self.assertEqual(''.join(parts),text)
        self.assertTrue(all(len(p)<=analysis.CHUNK_SIZE for p in parts))
        self.assertTrue(parts[-1].endswith('LAST MARKER'))

    def test_accepts_old_limit_and_exact_new_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'large.txt'
            for length in (60001,300001,extract.MAX_TEXT):
                path.write_text('x'*length,encoding='utf-8')
                self.assertEqual(len(extract.extract(path,'.txt')['text']),length)
            path.write_text('x'*(extract.MAX_TEXT+1),encoding='utf-8')
            with self.assertRaises(extract.LimitError):extract.extract(path,'.txt')


class AnalysisTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.gate = patch.object(analysis,'MODEL_GATE',asyncio.Semaphore(2))
        self.gate.start();self.addCleanup(self.gate.stop)

    def client(self,create):
        return NS(chat=NS(completions=NS(create=create)))

    def reply(self,text,reason='stop'):
        return NS(choices=[NS(message=NS(content=text),finish_reason=reason)])

    async def test_last_chunk_contributes_to_final_answer(self):
        async def create(**kw):
            text=kw['messages'][-1]['content']
            if 'Сейчас обрабатывается' in kw['messages'][0]['content']:
                if 'Фрагмент 1/2' in text:return self.reply('First part irrelevant')
                if 'Фрагмент 2/2' in text:return self.reply('LAST MARKER 250')
            return self.reply('Last part contains 250' if 'LAST MARKER 250' in text else 'missing')
        create_mock=AsyncMock(side_effect=create)
        text='x'*analysis.CHUNK_SIZE+'LAST MARKER 250'
        result=await analysis.answer(self.client(create_mock),text,'What is the final value?')
        self.assertIn('250',result)
        self.assertEqual(create_mock.await_count,3)
        self.assertTrue(all(len(c.kwargs['messages'][-1]['content']) < 60000 for c in create_mock.call_args_list))

    async def test_followup_reexamines_original_last_part(self):
        create=AsyncMock(return_value=self.reply('Evidence 17'))
        client=self.client(create);text='x'*analysis.CHUNK_SIZE+'ORIGINAL LAST VALUE 17'
        await analysis.evidence(client,text,'First question')
        create.reset_mock()
        await analysis.evidence(client,text,'New question about last value')
        self.assertEqual(create.await_count,2)
        self.assertIn('ORIGINAL LAST VALUE 17',str(create.call_args_list))

    async def test_failure_does_not_create_final_success(self):
        create=AsyncMock(side_effect=TimeoutError())
        with self.assertRaises(TimeoutError):
            await analysis.answer(self.client(create),'x'*(analysis.CHUNK_SIZE+1),'Question')
        self.assertLessEqual(create.await_count,2)

    async def test_empty_or_truncated_response_rejected(self):
        for text,reason in (('', 'stop'),('partial','length')):
            create=AsyncMock(return_value=self.reply(text,reason))
            with self.assertRaises(ValueError):
                await analysis.answer(self.client(create),'short document','Question')

    async def test_small_file_only_needs_one_request(self):
        create=AsyncMock(return_value=self.reply('Answer'))
        self.assertEqual(await analysis.answer(self.client(create),'short document','Question'),'Answer')
        self.assertEqual(create.await_count,1)

    async def test_large_evidence_merges_all_parts_without_losing_tail(self):
        reads=[];merges=[]
        async def create(**kw):
            system=kw['messages'][0]['content'];text=kw['messages'][-1]['content']
            self.assertLess(len(text),41000)
            if 'Сейчас обрабатывается' in system:
                reads.append(text)
                tail='LAST VALUE 987654' if 'LAST VALUE 987654' in text else 'No value'
                return self.reply('context '*1200+tail)
            if 'Объедини промежуточные' in system:
                merges.append(text)
                return self.reply('LAST VALUE 987654' if 'LAST VALUE 987654' in text else 'No relevant data')
            return self.reply('987654' if 'LAST VALUE 987654' in text else 'missing')
        source='x'*(analysis.CHUNK_SIZE*8)+'LAST VALUE 987654'
        result=await analysis.answer(self.client(AsyncMock(side_effect=create)),source,'What is the last value?')
        self.assertEqual(len(reads),9)
        self.assertGreater(len(merges),0)
        self.assertEqual(result,'987654')

    async def test_merge_failure_does_not_claim_complete_analysis(self):
        async def create(**kw):
            system=kw['messages'][0]['content']
            if 'Сейчас обрабатывается' in system:return self.reply('context '*1200)
            if 'Объедини промежуточные' in system:raise TimeoutError()
            self.fail('Final answer must not run after incomplete reduction')
        with self.assertRaises(TimeoutError):
            await analysis.answer(self.client(AsyncMock(side_effect=create)),
                                  'x'*(analysis.CHUNK_SIZE*8),'Summarize')
