import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from video import handler, analysis, extract
from speech.handler import reliable_text

class SpeechQualityTests(unittest.TestCase):
    def segment(self,text,**kwargs):
        return {'text':text,'no_speech_prob':0.01,'avg_logprob':-0.1,'compression_ratio':1.1,**kwargs}
    def test_silence_and_uncertain_segments_are_not_saved_as_speech(self):
        result=NS(segments=[self.segment('clear'),self.segment('silence',no_speech_prob=.9),
                            self.segment('unclear',avg_logprob=-2),self.segment('repeated',compression_ratio=3)])
        self.assertEqual(reliable_text(result),'clear')
    def test_missing_or_nonfinite_metadata_fails_closed(self):
        self.assertEqual(reliable_text(NS(text='hallucination')), '')
        self.assertEqual(reliable_text(NS(segments=[self.segment('bad',avg_logprob=float('nan'))])), '')

class VideoTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.path=None
        async def download(custom_path):
            self.path=custom_path;custom_path.write_bytes(b'synthetic video')
        self.remote=NS(file_size=10,download_to_drive=AsyncMock(side_effect=download))
        self.clip=NS(file_size=10,duration=20,get_file=AsyncMock(return_value=self.remote))
        self.message=NS(video=self.clip,video_note=None,document=None,caption='Question')
        self.update=NS(message=self.message,effective_user=NS(id=12),effective_chat=NS(id=12,type='private'))
        self.history={}
    async def run_video(self,speech='recognized speech',audio=True,stt_error=None,extract_error=None,key='test-key'):
        async def extracted(path,directory):
            if extract_error:raise extract_error
            sound=Path(directory)/'speech.flac' if audio else None
            if sound:sound.write_bytes(b'audio')
            return 20,[(2,b'jpg1'),(10,b'jpg2'),(18,b'jpg3')],sound
        with patch.dict('os.environ',{'GROQ_API_KEY':key}),patch.object(handler,'extract',new=AsyncMock(side_effect=extracted)) as decode,patch.object(handler,'transcribe',new=AsyncMock(return_value=speech,side_effect=stt_error)) as stt,patch.object(handler,'describe',new=AsyncMock(return_value='Synthetic analysis')) as model,patch.object(handler,'record',new=AsyncMock()) as record,patch.object(handler,'send_reply',new=AsyncMock()) as reply:
            await handler.handle_video(self.update,NS(),self.history)
            return decode,stt,model,record,reply
    async def test_video_combines_frames_speech_and_cleans_files(self):
        decode,stt,model,record,reply=await self.run_video()
        self.assertFalse(self.path.exists())
        self.assertEqual(model.await_args.args[2:5],('recognized speech','recognized',20))
        self.assertEqual(record.await_args.kwargs['text'],'[Видео] Question')
        self.assertIn('трём кадрам',self.history[(12,12)][-1]['content'])
    async def test_video_note_and_document(self):
        self.message.video=None;self.message.video_note=self.clip
        await self.run_video()
        self.message.video_note=None;self.clip.file_name='clip.MOV';self.message.document=self.clip
        await self.run_video();self.assertEqual(self.path.suffix,'.mov')
    async def test_group_never_downloads_or_calls_provider(self):
        self.update.effective_chat.type='group'
        decode,stt,model,record,reply=await self.run_video()
        self.clip.get_file.assert_not_awaited();model.assert_not_awaited();record.assert_not_awaited()
    async def test_missing_key_and_metadata_limit_prevent_download(self):
        await self.run_video(key='');self.clip.get_file.assert_not_awaited()
        self.clip.file_size=handler.MAX_BYTES+1
        await self.run_video();self.clip.get_file.assert_not_awaited()
        self.clip.file_size=10;self.clip.duration=121
        await self.run_video();self.clip.get_file.assert_not_awaited()
    async def test_actual_duration_validation_and_cleanup(self):
        decode,stt,model,record,reply=await self.run_video(extract_error=extract.InvalidVideo('safe'))
        self.assertFalse(self.path.exists());model.assert_not_awaited();record.assert_not_awaited()
        self.assertEqual(self.history,{})
    async def test_silent_video_is_analysed_without_invented_speech(self):
        decode,stt,model,record,reply=await self.run_video(audio=False)
        stt.assert_not_awaited();self.assertEqual(model.await_args.args[3],'no_audio')
        self.assertIn('нет звуковой дорожки',reply.await_args.args[1])
    async def test_failed_transcription_is_explicit_visual_only_result(self):
        decode,stt,model,record,reply=await self.run_video(stt_error=TimeoutError())
        self.assertEqual(model.await_args.args[2:4],('','unavailable'))
        self.assertIn('только по кадрам',reply.await_args.args[1])
    async def test_decode_timeout_cleans_files_and_does_not_enter_history(self):
        decode,stt,model,record,reply=await self.run_video(extract_error=TimeoutError())
        self.assertFalse(self.path.exists());model.assert_not_awaited();self.assertEqual(self.history,{})
    async def test_provider_receives_three_byte_images_not_telegram_urls(self):
        client=NS(chat=NS(completions=NS(create=AsyncMock(return_value=NS(choices=[NS(message=NS(content='analysis'))])))))
        with patch.object(analysis,'AsyncOpenAI') as factory:
            factory.return_value.__aenter__=AsyncMock(return_value=client)
            factory.return_value.__aexit__=AsyncMock(return_value=None)
            await analysis.describe([(1,b'a'),(2,b'b'),(3,b'c')],'question','speech','recognized',5,'key')
        content=client.chat.completions.create.await_args.kwargs['messages'][1]['content']
        images=[part['image_url']['url'] for part in content if part['type']=='image_url']
        self.assertEqual(len(images),3);self.assertTrue(all(x.startswith('data:image/jpeg;base64,') for x in images))

class MetadataTests(unittest.TestCase):
    def test_duration_and_audio_track(self):
        self.assertEqual(extract.metadata('Duration: 00:01:20.00\nStream #0:0: Video: h264\nStream #0:1: Audio: aac'),(80,True))
    def test_missing_or_long_video_rejected(self):
        for value in ('garbage','Duration: 00:10:00.00\nStream #0:0: Video: h264'):
            with self.assertRaises(extract.InvalidVideo):extract.metadata(value)

class RealDecoderTests(unittest.IsolatedAsyncioTestCase):
    async def test_synthetic_video_and_audio_extraction(self):
        with TemporaryDirectory(prefix='guardian-test-video-') as directory:
            path=Path(directory)/'synthetic.mp4'
            await extract.run('-y','-f','lavfi','-i','testsrc=size=160x120:rate=5','-f','lavfi','-i','sine=frequency=440:sample_rate=16000',
                              '-t','2','-c:v','libx264','-threads','1','-pix_fmt','yuv420p','-c:a','aac',path)
            duration,frames,audio=await extract.extract(path,directory)
            self.assertAlmostEqual(duration,2,places=1);self.assertEqual(len(frames),3)
            self.assertTrue(all(data.startswith(b'\xff\xd8') for time,data in frames))
            self.assertTrue(audio.exists());self.assertLess(audio.stat().st_size,extract.MAX_AUDIO_BYTES)

class ProcessCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_decoder_is_killed_on_timeout(self):
        original=asyncio.create_subprocess_exec
        children=[]
        async def spawn(*args,**kwargs):
            process=await original(*args,**kwargs);children.append(process);return process
        with patch.object(extract.asyncio,'create_subprocess_exec',new=spawn):
            with self.assertRaises(TimeoutError):
                await extract.run('-re','-f','lavfi','-i','testsrc=size=160x120:rate=5','-t','30','-f','null','-',timeout=.1)
        self.assertEqual(len(children),1);self.assertIsNotNone(children[0].returncode)
