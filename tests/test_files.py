import asyncio
import io
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from attachments import extract, handler


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def parse(self, ext, data):
        p = self.root/('input'+ext)
        p.write_bytes(data)
        return extract.extract(p, ext)

    def zip_parse(self, ext, name, text):
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as z:
            z.writestr(name, text)
        return self.parse(ext, out.getvalue())

    def test_direct_formats_and_encoding(self):
        for ext in ('.txt','.md','.json'):
            self.assertIn('число 17',self.parse(ext,'число 17'.encode())['text'])
        self.assertEqual(self.parse('.txt','Привет'.encode('cp1251'))['text'],'Привет')

    def test_csv_structure_and_limits(self):
        result=self.parse('.csv',b'name;price\nitem;17')
        self.assertIn('Строка 2: ["item", "17"]',result['text'])
        with self.assertRaises(extract.LimitError):
            self.parse('.csv', ('a\n'*2001).encode())

    def test_text_limit(self):
        with self.assertRaises(extract.LimitError):
            self.parse('.txt',b'x'*(extract.MAX_TEXT+1))

    def test_html_does_not_execute_or_read_external_content(self):
        result=self.parse('.html',b'<p>visible</p><script>hidden</script><style>hidden2</style><img src="http://localhost/private">')
        self.assertIn('visible',result['text'])
        self.assertNotIn('hidden',result['text'])

    def test_docx_paragraph_and_table(self):
        xml='<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Alpha</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>17</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>'
        result=self.zip_parse('.docx','word/document.xml',xml)
        self.assertIn('Alpha',result['text']);self.assertIn('17',result['text'])

    def test_odt_and_pptx(self):
        odt='<office:document xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><text:p>ODT text</text:p></office:document>'
        self.assertIn('ODT text',self.zip_parse('.odt','content.xml',odt)['text'])
        ppt='<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:p><a:r><a:t>Slide text</a:t></a:r></a:p></p:sld>'
        self.assertIn('Slide text',self.zip_parse('.pptx','ppt/slides/slide1.xml',ppt)['text'])

    def test_xml_entities_rejected(self):
        xml='<!DOCTYPE x [<!ENTITY e SYSTEM "file:///private">]><x>&e;</x>'
        with self.assertRaises(Exception):
            self.zip_parse('.odt','content.xml',xml)

    def test_archive_expansion_limit(self):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w',compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('word/document.xml', b'x'*(41*1024*1024))
        with self.assertRaises(extract.LimitError):
            self.parse('.docx',data.getvalue())

    def test_real_xlsx_addresses_and_formula(self):
        from openpyxl import Workbook
        book=Workbook();sheet=book.active;sheet.title='Prices'
        sheet.append(['item',17,'=B1*2'])
        stream=io.BytesIO();book.save(stream);book.close()
        result=self.parse('.xlsx',stream.getvalue())
        self.assertIn('Prices!строка 1',result['text'])
        self.assertIn('B1=17',result['text']);self.assertIn('C1==B1*2',result['text'])

    def test_pdf_text_scan_and_encryption(self):
        import pymupdf
        with pymupdf.open() as doc:
            doc.new_page().insert_text((72,72),'Synthetic page 17')
            self.assertIn('Synthetic page 17',self.parse('.pdf',doc.tobytes())['text'])
            encrypted=doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256,owner_pw='owner',user_pw='pass')
            with self.assertRaises(extract.LimitError):
                self.parse('.pdf',encrypted)
        with pymupdf.open() as doc:
            doc.new_page()
            result=self.parse('.pdf',doc.tobytes())
            self.assertEqual(len(result['images']),1)

    def test_scanned_page_limit(self):
        import pymupdf
        with pymupdf.open() as doc:
            for _ in range(6):doc.new_page()
            with self.assertRaises(extract.LimitError):
                self.parse('.pdf',doc.tobytes())

    def test_image_converted_to_jpeg(self):
        from PIL import Image
        for ext,fmt in (('.png','PNG'),('.jpg','JPEG'),('.webp','WEBP')):
            stream=io.BytesIO();Image.new('RGB',(10,10)).save(stream,format=fmt)
            result=self.parse(ext,stream.getvalue())
            self.assertEqual(len(result['images']),1)

    def test_real_legacy_xls(self):
        data=(Path(__file__).parent/'fixtures'/'synthetic.xls').read_bytes()
        result=self.parse('.xls',data)
        self.assertIn('Legacy!строка 1',result['text'])
        self.assertIn('17.0',result['text'])
        self.assertIn('2026-10-12',result['text'])


def incoming(kind='private',ext='.txt',size=3):
    doc=NS(file_name='../../unsafe'+ext,file_size=size,get_file=AsyncMock())
    update=NS(message=NS(document=doc,caption='Summarize',message_id=12),
              effective_user=NS(id=17),effective_chat=NS(id=17,type=kind))
    return update,NS(user_data={})


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_group_and_limits_rejected_before_download(self):
        for kind,ext,size in (('group','.txt',3),('private','.exe',3),('private','.txt',handler.MAX_BYTES+1)):
            update,ctx=incoming(kind,ext,size)
            with patch.object(handler,'send_reply',new=AsyncMock()):
                await handler.handle_document(update,ctx,NS(),{})
            update.message.document.get_file.assert_not_awaited()

    async def test_temp_deleted_success_and_failure(self):
        for failure in (False,True):
            update,ctx=incoming();paths=[]
            async def download(custom_path):
                paths.append(custom_path);custom_path.write_bytes(b'abc')
            update.message.document.get_file.return_value=NS(file_size=3,download_to_drive=AsyncMock(side_effect=download))
            client=NS(chat=NS(completions=NS(create=AsyncMock(return_value=NS(choices=[NS(message=NS(content='Summary'))])))))
            with patch.object(handler,'parse',new=AsyncMock(return_value={'text':'abc','images':[]},side_effect=ValueError() if failure else None)),patch.object(handler,'send_reply',new=AsyncMock()),patch.object(handler,'record',new=AsyncMock()):
                await handler.handle_document(update,ctx,client,{})
            self.assertTrue(paths);self.assertFalse(paths[0].exists())
            self.assertEqual(bool(handler.current(update,ctx)),not failure)

    async def test_cache_owner_expiry_and_clear(self):
        update,ctx=incoming()
        handler.remember_context(update,ctx,'private text')
        self.assertIsNotNone(handler.current(update,ctx))
        ctx.user_data['document_context']['owner']=99
        self.assertIsNone(handler.current(update,ctx))
        handler.remember_context(update,ctx,'private text')
        ctx.user_data['document_context']['expires']=0
        self.assertIsNone(handler.current(update,ctx))
        handler.remember_context(update,ctx,'private text');handler.clear(ctx)
        self.assertIsNone(handler.current(update,ctx))

    async def test_subprocess_reads_real_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'test.txt';path.write_text('child text',encoding='utf-8')
            self.assertEqual((await handler.parse(path,'.txt'))['text'],'child text')

    async def test_timeout_kills_child(self):
        proc=NS(returncode=None,communicate=lambda:None,kill=lambda:None,wait=AsyncMock())
        with patch.object(asyncio,'create_subprocess_exec',new=AsyncMock(return_value=proc)),patch.object(asyncio,'wait_for',new=AsyncMock(side_effect=TimeoutError())),patch.object(proc,'kill') as kill:
            with self.assertRaises(TimeoutError):
                await handler.parse('dummy.txt','.txt')
            kill.assert_called_once();proc.wait.assert_awaited_once()

    async def test_ocr_success_and_failure_never_saves_raw_to_journal(self):
        from vision import handler as vision
        for failure in (False,True):
            update,ctx=incoming(ext='.png')
            async def download(custom_path):custom_path.write_bytes(b'png')
            update.message.document.get_file.return_value=NS(file_size=3,download_to_drive=AsyncMock(side_effect=download))
            client=NS(chat=NS(completions=NS(create=AsyncMock(return_value=NS(choices=[NS(message=NS(content='OCR answer'))])))))
            with patch.dict('os.environ',{'GROQ_API_KEY':'synthetic-test-key'}),patch.object(handler,'parse',new=AsyncMock(return_value={'text':'[Нужен OCR страницы 1]','images':[{'page':1,'jpeg':'YWJj'}]})),patch.object(vision,'describe',new=AsyncMock(return_value='OCR synthetic 17',side_effect=ValueError() if failure else None)),patch.object(handler,'record',new=AsyncMock()) as journal,patch.object(handler,'send_reply',new=AsyncMock()):
                await handler.handle_document(update,ctx,client,{})
            self.assertNotIn('OCR synthetic 17',str(journal.call_args))
            self.assertEqual(bool(handler.current(update,ctx)),not failure)
            if not failure:self.assertIn('OCR synthetic 17',handler.current(update,ctx)['text'])

    async def test_file_followup_does_not_autosave(self):
        import bot
        update,ctx=incoming();ctx.bot=NS(send_chat_action=AsyncMock())
        handler.remember_context(update,ctx,'Document fact 17')
        reply=NS(choices=[NS(message=NS(content='File answer'))])
        bot.conversation_memory.clear()
        with patch.object(bot,'BACKEND','supabase'),patch.object(bot.automatic_memory,'process',new=AsyncMock()) as save,patch.object(bot.automatic_memory,'context',new=AsyncMock(return_value='memory')),patch.object(bot,'restore_dialogue',new=AsyncMock(return_value=[])),patch.object(bot,'send_reply',new=AsyncMock()),patch.object(bot.deepseek.chat.completions,'create',new=AsyncMock(return_value=reply)) as model:
            await bot.handle_text(update,ctx,'What does this mean?')
        save.assert_not_awaited()
        self.assertIn('Document fact 17',str(model.call_args.kwargs['messages']))
